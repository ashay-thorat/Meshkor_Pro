"""Load CMS ASP payment limit files and NDC-HCPCS crosswalks into Parquet.

Input : every *.zip under data/raw/cms_asp/ and data/raw/cms_crosswalk/
        whose name has a quarter month + year (january_2026, october_2026, ...).
        Seasonal vaccine files are ignored.
Output: data/ref/ref_asp.parquet        one row per HCPCS per quarter
        data/ref/ref_crosswalk.parquet  one row per NDC-HCPCS pair per quarter

Rules (developer guide 1.2):
  * "Payment Limit" is already 106% of ASP. It is stored as is.
  * The header row is found by searching for the HCPCS column, not assumed.
  * The script fails if more than 1% of payment limits are null.

Run: python -m pipeline.load_asp
"""
from __future__ import annotations

import csv
import io
import re
import sys
import zipfile
from pathlib import Path

import polars as pl

from .common import (norm_hcpcs, norm_ndc, parse_hcpcs_dosage, paths, quarter_bounds,
                     quarter_from_filename, rel, sha256, to_float)


def _key(s: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


# ---------- reading tables out of a ZIP ----------

def _rows_from_member(zf: zipfile.ZipFile, member: str) -> list[list[str]]:
    data = zf.read(member)
    low = member.lower()
    if low.endswith((".xlsx", ".xls")):
        df = pl.read_excel(io.BytesIO(data), engine="calamine", has_header=False,
                           infer_schema_length=0)
        return [["" if v is None else str(v) for v in row] for row in df.iter_rows()]
    if low.endswith((".csv", ".txt")):
        text = data.decode("utf-8-sig", errors="replace")
        return [row for row in csv.reader(io.StringIO(text))]
    return []


def _find_header(rows: list[list[str]], must: list[str]) -> int | None:
    """Index of the first row whose cells include every key in `must`."""
    for i, row in enumerate(rows[:40]):
        keys = {_key(c) for c in row}
        if all(any(m(k) for k in keys) for m in must):
            return i
    return None


def _is_hcpcs_col(k: str) -> bool:
    return k in ("hcpcs", "hcpcscode") or bool(re.fullmatch(r"\d{4}code", k))


def _pick(header: list[str], *options) -> int | None:
    keys = [_key(h) for h in header]
    for opt in options:
        for i, k in enumerate(keys):
            if (callable(opt) and opt(k)) or k == opt:
                return i
    return None


def _best_table(zip_path: Path, must) -> tuple[str, list[str], list[list[str]]]:
    """The member + header + data rows of the table that matches `must`."""
    with zipfile.ZipFile(zip_path) as zf:
        candidates = [m for m in zf.namelist()
                      if m.lower().endswith((".xlsx", ".xls", ".csv", ".txt"))
                      and not m.startswith("__MACOSX")]
        best = None
        for member in candidates:
            rows = _rows_from_member(zf, member)
            h = _find_header(rows, must)
            if h is None:
                continue
            data = rows[h + 1:]
            if best is None or len(data) > len(best[2]):
                best = (member, rows[h], data)
    if best is None:
        raise ValueError(f"No table with the expected columns in {zip_path.name}")
    return best


# ---------- loaders ----------

def load_payment_limit(zip_path: Path, quarter: str) -> pl.DataFrame:
    member, header, rows = _best_table(
        zip_path, [_is_hcpcs_col, lambda k: k == "paymentlimit"])
    i_code = _pick(header, _is_hcpcs_col)
    i_desc = _pick(header, "shortdescription", "description")
    i_dose = _pick(header, "hcpcscodedosage", "hcpcsdosage", "dosage")
    i_lim = _pick(header, "paymentlimit")
    start, end = quarter_bounds(quarter)
    digest = sha256(zip_path)
    out, bad_codes = [], 0
    for r in rows:
        if len(r) <= max(i_code, i_lim):
            continue
        code = norm_hcpcs(r[i_code])
        if code is None:
            if r[i_code].strip():
                bad_codes += 1   # notes, footers, disclaimers
            continue
        dose_text = r[i_dose].strip() if i_dose is not None else ""
        dose = parse_hcpcs_dosage(dose_text)
        out.append({
            "hcpcs": code,
            "short_description": r[i_desc].strip() if i_desc is not None else None,
            "dosage_text": dose_text or None,
            "billing_qty": dose.qty if dose else None,
            "billing_unit": dose.unit if dose else None,
            "payment_limit": to_float(r[i_lim]),
            "quarter": quarter,
            "effective_start": start,
            "effective_end": end,
            "source_file": rel(zip_path),
            "source_member": member,
            "source_sha256": digest,
        })
    df = pl.DataFrame(out)
    nulls = df["payment_limit"].null_count()
    if len(df) == 0 or nulls / len(df) > 0.01:
        raise ValueError(f"{zip_path.name}: {nulls} of {len(df)} payment limits are null "
                         f"(over 1%). Check the column mapping.")
    print(f"  ASP {quarter}: {len(df):,} codes ({nulls} null limits, "
          f"{bad_codes} non-code rows skipped) from {member}")
    return df


def load_crosswalk(zip_path: Path, quarter: str) -> pl.DataFrame:
    member, header, rows = _best_table(
        zip_path, [_is_hcpcs_col, lambda k: k.startswith("ndc")])
    i_code = _pick(header, _is_hcpcs_col)
    i_ndc = _pick(header, "ndc2", "ndc", "ndc11", lambda k: k.startswith("ndc"))
    i_name = _pick(header, "drugname")
    i_lab = _pick(header, "labelername", "labeler")
    i_dose = _pick(header, "hcpcsdosage", "hcpcscodedosage", "dosage")
    i_size = _pick(header, "pkgsize")
    i_pqty = _pick(header, "pkgqty")
    i_bu = _pick(header, "billunits")
    i_bup = _pick(header, "billunitspkg")
    start, end = quarter_bounds(quarter)
    digest = sha256(zip_path)

    def cell(r, i):
        return r[i].strip() if i is not None and i < len(r) else ""

    out, bad_ndc = [], 0
    for r in rows:
        code = norm_hcpcs(cell(r, i_code))
        if code is None:
            continue
        ndc = norm_ndc(cell(r, i_ndc))
        if ndc is None:
            bad_ndc += 1
            continue
        out.append({
            "hcpcs": code,
            "ndc11": ndc,
            "drug_name": cell(r, i_name) or None,
            "labeler": cell(r, i_lab) or None,
            "dosage_text": cell(r, i_dose) or None,
            "pkg_size": to_float(cell(r, i_size)),
            "pkg_qty": to_float(cell(r, i_pqty)),
            "bill_units": to_float(cell(r, i_bu)),
            "bill_units_pkg": to_float(cell(r, i_bup)),
            "quarter": quarter,
            "effective_start": start,
            "effective_end": end,
            "source_file": rel(zip_path),
            "source_member": member,
            "source_sha256": digest,
        })
    df = pl.DataFrame(out)
    print(f"  Crosswalk {quarter}: {len(df):,} NDC rows ({bad_ndc} rows with unusable NDC) "
          f"from {member}")
    return df


def classify(zip_path: Path) -> str | None:
    n = zip_path.name.lower()
    if "seasonal" in n or "vaccine" in n:
        return None
    if "crosswalk" in n:
        return "crosswalk"
    if "payment_limit" in n or "payment-limit" in n or "asp_pricing" in n or "pricing_file" in n:
        return "asp"
    return None


def main() -> int:
    p = paths()
    raw = p["raw"]
    zips = sorted({*raw.glob("cms_asp/**/*.zip"), *raw.glob("cms_crosswalk/**/*.zip")})
    chosen: dict[tuple[str, str], Path] = {}
    for z in zips:
        kind, q = classify(z), quarter_from_filename(z.name)
        if kind is None or q is None:
            print(f"  skip (not an ASP/crosswalk quarter file): {z.name}")
            continue
        if (kind, q) in chosen:
            print(f"  NOTE two {kind} files for {q}; using {z.name} over {chosen[(kind, q)].name}")
        chosen[(kind, q)] = z

    if not chosen:
        print("No ASP or crosswalk ZIPs found under", raw)
        return 1

    asp = [load_payment_limit(z, q) for (k, q), z in sorted(chosen.items()) if k == "asp"]
    xw = [load_crosswalk(z, q) for (k, q), z in sorted(chosen.items()) if k == "crosswalk"]

    p["ref"].mkdir(parents=True, exist_ok=True)
    if asp:
        pl.concat(asp).write_parquet(p["ref"] / "ref_asp.parquet", compression="zstd")
    if xw:
        pl.concat(xw).write_parquet(p["ref"] / "ref_crosswalk.parquet", compression="zstd")
    print(f"Wrote {len(asp)} ASP quarters and {len(xw)} crosswalk quarters to {rel(p['ref'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
