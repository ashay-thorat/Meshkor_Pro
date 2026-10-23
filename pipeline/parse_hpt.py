"""Parse hospital price files (CMS template v2.x) into drug rate rows.

Input : data/raw/hospital_mrf/<system>/<date>/<price files>
        Formats: CMS JSON, CMS CSV "tall", CMS CSV "wide", and ZIPs holding them.
Output: data/hpt/norm/hpt_drug_rates.parquet   one row per item x setting x payer/plan
        data/hpt/norm/hpt_file_quality.parquet one row per file (what was found)

Only rows for drugs in config/drugs_in_scope.yaml are kept. A row is in scope
when it carries an in-scope HCPCS code, or an NDC that the CMS crosswalk maps
to an in-scope HCPCS code.

Run after pipeline.load_asp:  python -m pipeline.parse_hpt
"""
from __future__ import annotations

import csv
import io
import re
import sys
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Iterator

import ijson
import polars as pl

from .common import (drugs_in_scope, load_yaml, norm_hcpcs, norm_ndc, paths, payer_group,
                     rel, sha256, to_float)

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))

RATE_COLS = ["gross_charge", "discounted_cash", "negotiated_dollar", "negotiated_percentage",
             "estimated_amount", "median_amount", "p10_amount", "p90_amount"]


# ---------- scope ----------

class Scope:
    def __init__(self, ref_dir: Path):
        self.hcpcs = {d["hcpcs"] for d in drugs_in_scope()}
        self.ndc_to_hcpcs: dict[str, str] = {}
        xw = ref_dir / "ref_crosswalk.parquet"
        if xw.exists():
            df = (pl.read_parquet(xw, columns=["hcpcs", "ndc11"])
                  .filter(pl.col("hcpcs").is_in(list(self.hcpcs))).unique())
            self.ndc_to_hcpcs = dict(zip(df["ndc11"], df["hcpcs"]))

    def match(self, codes: list[tuple[str, str]]) -> tuple[str | None, str | None, str | None]:
        """codes = [(code, type)] -> (hcpcs, ndc11, matched_via)."""
        hcpcs = ndc = via = None
        for code, typ in codes:
            t = (typ or "").upper()
            if t in ("HCPCS", "CPT") or (not t and norm_hcpcs(code)):
                c = norm_hcpcs(code)
                if c in self.hcpcs:
                    hcpcs, via = c, "hcpcs"
            elif t == "NDC":
                n = norm_ndc(code)
                if n:
                    ndc = n
        if hcpcs is None and ndc and ndc in self.ndc_to_hcpcs:
            hcpcs, via = self.ndc_to_hcpcs[ndc], "ndc_crosswalk"
        return hcpcs, ndc, via


# ---------- file opening ----------

def _sniff_json(head: bytes) -> bool:
    s = head.lstrip(b"\xef\xbb\xbf \t\r\n")
    return s[:1] in (b"{", b"[")


def iter_sources(path: Path) -> Iterator[tuple[str, callable]]:
    """Yield (label, opener) for each price table in a file or ZIP."""
    if zipfile.is_zipfile(path):
        zf = zipfile.ZipFile(path)
        for m in zf.namelist():
            if m.endswith("/") or m.startswith("__MACOSX"):
                continue
            yield m, (lambda m=m: zf.open(m))
    else:
        yield path.name, (lambda: path.open("rb"))


# ---------- JSON ----------

def parse_json(opener, scope: Scope, stats: dict) -> Iterator[dict]:
    """Two streaming passes: header fields, then items. Memory stays small."""
    header: dict = {}
    with opener() as fh:
        for prefix, event, value in ijson.parse(fh):
            if prefix == "standard_charge_information" and event == "start_array":
                break
            if "." not in prefix and event in ("string", "number", "boolean"):
                header[prefix] = value
    stats["hospital_name"] = header.get("hospital_name")
    stats["file_last_updated"] = header.get("last_updated_on")
    stats["cms_version"] = header.get("version")
    stats["format"] = "json"
    with opener() as fh:
        yield from _json_items(fh, scope, stats)


def _json_items(fh, scope: Scope, stats: dict) -> Iterator[dict]:
    for item in ijson.items(fh, "standard_charge_information.item", use_float=True):
        stats["items_scanned"] += 1
        codes = [(str(c.get("code", "")), str(c.get("type", "")))
                 for c in item.get("code_information", []) or []]
        hcpcs, ndc, via = scope.match(codes)
        if hcpcs is None:
            continue
        drug = item.get("drug_information") or {}
        base = {
            "hcpcs": hcpcs, "ndc11": ndc, "matched_via": via,
            "description": item.get("description"),
            "drug_unit": to_float(drug.get("unit")),
            "drug_unit_type": drug.get("type"),
        }
        for sc in item.get("standard_charges", []) or []:
            common = {
                **base,
                "setting": sc.get("setting"),
                "billing_class": sc.get("billing_class"),
                "modifiers": ",".join(sc.get("modifier_code") or []) if isinstance(
                    sc.get("modifier_code"), list) else sc.get("modifier_code"),
                "gross_charge": to_float(sc.get("gross_charge")),
                "discounted_cash": to_float(sc.get("discounted_cash")),
            }
            payers = sc.get("payers_information") or []
            if not payers:
                yield {**common, "payer_name": None, "plan_name": None}
            for pi in payers:
                yield {
                    **common,
                    "payer_name": pi.get("payer_name"),
                    "plan_name": pi.get("plan_name"),
                    "negotiated_dollar": to_float(pi.get("standard_charge_dollar")),
                    "negotiated_percentage": to_float(pi.get("standard_charge_percentage")),
                    "negotiated_algorithm": pi.get("standard_charge_algorithm"),
                    "estimated_amount": to_float(pi.get("estimated_amount")),
                    "median_amount": to_float(pi.get("median_amount")),
                    "p10_amount": to_float(pi.get("10th_percentile")),
                    "p90_amount": to_float(pi.get("90th_percentile")),
                    "methodology": pi.get("methodology"),
                }


# ---------- CSV (tall and wide) ----------

def _csv_rows(fh) -> Iterator[list[str]]:
    text = io.TextIOWrapper(fh, encoding="utf-8-sig", errors="replace", newline="")
    yield from csv.reader(text)


def parse_csv(opener, scope: Scope, stats: dict) -> Iterator[dict]:
    with opener() as fh:
        yield from _csv_items(fh, scope, stats)


def _csv_items(fh, scope: Scope, stats: dict) -> Iterator[dict]:
    rows = _csv_rows(fh)
    pre: list[list[str]] = []
    header = None
    for _ in range(6):
        r = next(rows, None)
        if r is None:
            break
        if any(c.strip().lower() == "description" for c in r):
            orig = [c.strip() for c in r]       # keeps payer/plan names as written
            header = [c.lower() for c in orig]
            break
        pre.append(r)
    if header is None:
        stats["format"] = "csv_unrecognized"
        stats["error"] = "no 'description' header row in the first 6 rows"
        return
    if len(pre) >= 2:
        meta = {k.strip().lower(): v for k, v in zip(pre[0], pre[1])}
        stats["hospital_name"] = meta.get("hospital_name")
        stats["file_last_updated"] = meta.get("last_updated_on")
        stats["cms_version"] = meta.get("version")

    idx = {h: i for i, h in enumerate(header)}
    code_cols = []
    for h, i in idx.items():
        m = re.fullmatch(r"code\|(\d+)", h)
        if m:
            code_cols.append((i, idx.get(f"code|{m.group(1)}|type")))

    tall = "payer_name" in idx
    stats["format"] = "csv_tall" if tall else "csv_wide"

    wide = {}   # (payer, plan) -> {field: col}
    if not tall:
        for i, h in enumerate(header):
            parts, oparts = h.split("|"), orig[i].split("|")
            if len(parts) == 4 and parts[0] == "standard_charge":
                wide.setdefault((oparts[1], oparts[2]), {})[parts[3]] = i
            elif len(parts) == 3 and parts[0] in ("estimated_amount", "median_amount",
                                                  "10th_percentile", "90th_percentile",
                                                  "additional_payer_notes"):
                wide.setdefault((oparts[1], oparts[2]), {})[parts[0]] = i

    def g(r, key):
        i = idx.get(key)
        return r[i].strip() if i is not None and i < len(r) and r[i].strip() != "" else None

    def gi(r, i):
        return r[i].strip() if i is not None and i < len(r) and r[i].strip() != "" else None

    for r in rows:
        stats["items_scanned"] += 1
        codes = [(gi(r, ci) or "", gi(r, ti) or "") for ci, ti in code_cols]
        hcpcs, ndc, via = scope.match(codes)
        if hcpcs is None:
            continue
        common = {
            "hcpcs": hcpcs, "ndc11": ndc, "matched_via": via,
            "description": g(r, "description"),
            "setting": g(r, "setting"),
            "billing_class": g(r, "billing_class"),
            "modifiers": g(r, "modifiers"),
            "drug_unit": to_float(g(r, "drug_unit_of_measurement")),
            "drug_unit_type": g(r, "drug_type_of_measurement"),
            "gross_charge": to_float(g(r, "standard_charge|gross")),
            "discounted_cash": to_float(g(r, "standard_charge|discounted_cash")),
        }
        if tall:
            yield {
                **common,
                "payer_name": g(r, "payer_name"),
                "plan_name": g(r, "plan_name"),
                "negotiated_dollar": to_float(g(r, "standard_charge|negotiated_dollar")),
                "negotiated_percentage": to_float(g(r, "standard_charge|negotiated_percentage")),
                "negotiated_algorithm": g(r, "standard_charge|negotiated_algorithm"),
                "estimated_amount": to_float(g(r, "estimated_amount")),
                "median_amount": to_float(g(r, "median_amount")),
                "p10_amount": to_float(g(r, "10th_percentile")),
                "p90_amount": to_float(g(r, "90th_percentile")),
                "methodology": g(r, "standard_charge|methodology"),
            }
        else:
            any_payer = False
            for (payer, plan), cols in wide.items():
                vals = {
                    "negotiated_dollar": to_float(gi(r, cols.get("negotiated_dollar"))),
                    "negotiated_percentage": to_float(gi(r, cols.get("negotiated_percentage"))),
                    "negotiated_algorithm": gi(r, cols.get("negotiated_algorithm")),
                    "estimated_amount": to_float(gi(r, cols.get("estimated_amount"))),
                    "median_amount": to_float(gi(r, cols.get("median_amount"))),
                    "p10_amount": to_float(gi(r, cols.get("10th_percentile"))),
                    "p90_amount": to_float(gi(r, cols.get("90th_percentile"))),
                    "methodology": gi(r, cols.get("methodology")),
                }
                if all(v is None for v in vals.values()):
                    continue
                any_payer = True
                yield {**common, "payer_name": payer, "plan_name": plan, **vals}
            if not any_payer:
                yield {**common, "payer_name": None, "plan_name": None}


# ---------- driver ----------

def _parse_date(s: object) -> date | None:
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d", "%m-%d-%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _download_log(raw: Path) -> dict[str, str]:
    log = raw / "hospital_mrf" / "mrf_download_log.csv"
    if not log.exists():
        return {}
    with log.open(newline="", encoding="utf-8") as f:
        return {r["file_name"]: r.get("locations", "") for r in csv.DictReader(f)
                if r.get("file_name")}


def price_files(raw: Path, skip: set[str]) -> Iterable[tuple[str, Path]]:
    root = raw / "hospital_mrf"
    for system_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        if system_dir.name in skip:
            continue
        for f in sorted(system_dir.glob("*/*")):
            if f.is_file() and f.name != "cms-hpt.txt" and not f.name.endswith(".part"):
                yield system_dir.name, f


def parse_file(system: str, path: Path, scope: Scope, locations: str) -> tuple[list[dict], list[dict]]:
    rows, quality = [], []
    digest = sha256(path)
    for label, opener in iter_sources(path):
        stats = {"system": system, "source_file": rel(path), "source_member": label,
                 "source_sha256": digest, "locations": locations, "items_scanned": 0,
                 "format": None, "error": None, "hospital_name": None,
                 "file_last_updated": None, "cms_version": None}
        out = []
        try:
            with opener() as fh:
                head = fh.read(4096)
            parser = parse_json if _sniff_json(head) else parse_csv
            for r in parser(opener, scope, stats):
                out.append(r)
        except Exception as e:  # noqa: BLE001  -- logged, never silently dropped
            stats["error"] = f"{type(e).__name__}: {e}"[:500]
        for r in out:
            for c in RATE_COLS:
                r.setdefault(c, None)
            r.setdefault("negotiated_algorithm", None)
            r.setdefault("methodology", None)
            r.update({
                "system": system,
                "hospital_name": stats["hospital_name"],
                "locations": locations,
                "file_last_updated": _parse_date(stats["file_last_updated"]),
                "cms_version": stats["cms_version"],
                "payer_group": payer_group(r.get("payer_name")),
                "source_file": rel(path),
                "source_member": label,
                "source_sha256": digest,
            })
        stats["drug_rows"] = len(out)
        stats["hcpcs_found"] = ",".join(sorted({r["hcpcs"] for r in out}))
        quality.append(stats)
        rows.extend(out)
        print(f"  [{system}] {label[:70]}: {stats['format']}, "
              f"{stats['items_scanned']:,} items, {len(out):,} drug rows"
              + (f"  ERROR {stats['error']}" if stats["error"] else ""))
    return rows, quality


SCHEMA = {
    "system": pl.Utf8, "hospital_name": pl.Utf8, "locations": pl.Utf8,
    "hcpcs": pl.Utf8, "ndc11": pl.Utf8, "matched_via": pl.Utf8, "description": pl.Utf8,
    "setting": pl.Utf8, "billing_class": pl.Utf8, "modifiers": pl.Utf8,
    "drug_unit": pl.Float64, "drug_unit_type": pl.Utf8,
    "payer_name": pl.Utf8, "plan_name": pl.Utf8, "payer_group": pl.Utf8,
    **{c: pl.Float64 for c in RATE_COLS},
    "negotiated_algorithm": pl.Utf8, "methodology": pl.Utf8,
    "file_last_updated": pl.Date, "cms_version": pl.Utf8,
    "source_file": pl.Utf8, "source_member": pl.Utf8, "source_sha256": pl.Utf8,
}


def main() -> int:
    p = paths()
    cfg = load_yaml("pipeline.yaml")
    scope = Scope(p["ref"])
    if not scope.ndc_to_hcpcs:
        print("NOTE: no crosswalk loaded; NDC-only rows cannot be matched. "
              "Run python -m pipeline.load_asp first.")
    logs = _download_log(p["raw"])
    all_rows, all_q = [], []
    for system, f in price_files(p["raw"], set(cfg.get("skip_systems") or [])):
        rows, q = parse_file(system, f, scope, logs.get(f.name, ""))
        all_rows += rows
        all_q += q
    p["hpt_norm"].mkdir(parents=True, exist_ok=True)
    rates = pl.DataFrame(all_rows, schema=SCHEMA) if all_rows else pl.DataFrame(schema=SCHEMA)
    rates.write_parquet(p["hpt_norm"] / "hpt_drug_rates.parquet", compression="zstd")
    pl.DataFrame(all_q, infer_schema_length=None).write_parquet(
        p["hpt_norm"] / "hpt_file_quality.parquet", compression="zstd")
    print(f"Wrote {len(rates):,} drug rate rows from {len(all_q)} tables")
    return 0


if __name__ == "__main__":
    sys.exit(main())
