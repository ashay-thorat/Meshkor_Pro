"""Load the FDA NDC Directory and NADAC into reference tables (ref_drug).

Input : data/raw/fda_ndc/<date>/ndctext.zip   (product.txt + package.txt, tab-delimited)
        data/raw/nadac/**/*.csv                 (NADAC weekly files, any years present)
Output: data/ref/ref_drug_fda.parquet   one row per 11-digit package NDC
        data/ref/ref_nadac.parquet      one row per NDC per NADAC effective date

ref_drug_fda keeps the package description and strength, and computes
mg_per_package when the strength and package volume can both be read
(e.g. 25 mg/mL x 4 mL = 100 mg). That value is a second, independent source
for unit conversion next to the CMS crosswalk.

NADAC is pharmacy acquisition cost, mostly for retail drugs. It is kept as a
reference only. It is never the benchmark.

Run: python -m pipeline.load_drug
"""
from __future__ import annotations

import io
import re
import sys
import zipfile
from datetime import date
from pathlib import Path

import polars as pl

from .common import norm_ndc, paths, rel, sha256


def _key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _col(df: pl.DataFrame, *names: str) -> str:
    keys = {_key(c): c for c in df.columns}
    for n in names:
        if _key(n) in keys:
            return keys[_key(n)]
    raise KeyError(f"none of {names} in columns {df.columns[:30]}")


def _read_tab(zf: zipfile.ZipFile, member_like: str) -> tuple[str, pl.DataFrame]:
    name = next(m for m in zf.namelist() if m.lower().endswith(member_like))
    raw = zf.read(name)
    text = raw.decode("utf-8", errors="replace") if raw[:3] != b"\xef\xbb\xbf" else raw[3:].decode()
    df = pl.read_csv(io.StringIO(text), separator="\t", infer_schema_length=0,
                     quote_char=None, truncate_ragged_lines=True)
    return name, df


# ---------- package volume and strength ----------

_SEG = re.compile(r"^\s*([\d.]+)\s+([A-Za-z ,\-]+?)\s+in\s+([\d.]+)\s+", re.I)


def package_amount(desc: str | None) -> tuple[float | None, str | None]:
    """'1 VIAL in 1 CARTON (0006-3026-02)  > 4 mL in 1 VIAL' -> (4.0, 'ML').

    Each '>' segment reads 'N UNIT in M CONTAINER'. The total is the product of
    N / M over the segments; the unit is the last segment's unit.
    """
    if not desc:
        return None, None
    total, unit = 1.0, None
    for seg in str(desc).split(">"):
        seg = re.sub(r"\([^)]*\)", "", seg)
        m = _SEG.match(seg)
        if not m:
            return None, None
        n, u, per = float(m.group(1)), m.group(2).strip().upper(), float(m.group(3))
        if per <= 0:
            return None, None
        total *= n / per
        unit = "ML" if u in ("ML", "MILLILITER") else u.split(",")[0].strip()
    return total, unit


def mg_per_package(strength: str | None, strength_unit: str | None,
                   amount: float | None, amount_unit: str | None) -> float | None:
    """Single-ingredient products only. 25 + 'mg/mL' + 4 ML -> 100; 100 + 'mg/1' + 1 VIAL -> 100."""
    if not strength or not strength_unit or amount is None:
        return None
    if ";" in str(strength) or ";" in str(strength_unit):
        return None                     # more than one active ingredient
    try:
        s = float(strength)
    except ValueError:
        return None
    u = str(strength_unit).strip().lower().replace(" ", "")
    m = re.fullmatch(r"(mg|g|ug|mcg)/(\d*\.?\d*)?(ml|1)", u)
    if not m:
        return None
    mass = {"mg": 1.0, "g": 1000.0, "ug": 0.001, "mcg": 0.001}[m.group(1)]
    per = float(m.group(2)) if m.group(2) else 1.0
    if m.group(3) == "ml":
        if amount_unit != "ML":
            return None
        return s * mass / per * amount
    # mg/1: per one count unit (vial, syringe, kit)
    if amount_unit == "ML":
        return None
    return s * mass / per * amount


# ---------- loaders ----------

def load_fda(zip_path: Path) -> pl.DataFrame:
    digest = sha256(zip_path)
    snap = _snapshot_date(zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        pkg_name, pkg = _read_tab(zf, "package.txt")
        _, prod = _read_tab(zf, "product.txt")
    pkg = pkg.select(
        pl.col(_col(pkg, "PRODUCTID")).alias("product_id"),
        pl.col(_col(pkg, "PRODUCTNDC")).alias("product_ndc"),
        pl.col(_col(pkg, "NDCPACKAGECODE")).alias("ndc_raw"),
        pl.col(_col(pkg, "PACKAGEDESCRIPTION")).alias("package_description"),
    )
    prod = prod.select(
        pl.col(_col(prod, "PRODUCTID")).alias("product_id"),
        pl.col(_col(prod, "PROPRIETARYNAME")).alias("proprietary_name"),
        pl.col(_col(prod, "NONPROPRIETARYNAME")).alias("nonproprietary_name"),
        pl.col(_col(prod, "DOSAGEFORMNAME")).alias("dosage_form"),
        pl.col(_col(prod, "ROUTENAME")).alias("route"),
        pl.col(_col(prod, "LABELERNAME")).alias("labeler"),
        pl.col(_col(prod, "ACTIVE_NUMERATOR_STRENGTH")).alias("strength_value"),
        pl.col(_col(prod, "ACTIVE_INGRED_UNIT")).alias("strength_unit"),
    )
    df = pkg.join(prod, on="product_id", how="left")
    rows = []
    bad = 0
    for r in df.iter_rows(named=True):
        ndc = norm_ndc(r["ndc_raw"])
        if ndc is None:
            bad += 1
            continue
        amt, unit = package_amount(r["package_description"])
        rows.append({
            **{k: r[k] for k in ("product_ndc", "package_description", "proprietary_name",
                                 "nonproprietary_name", "dosage_form", "route", "labeler",
                                 "strength_value", "strength_unit")},
            "ndc11": ndc,
            "package_amount": amt, "package_unit": unit,
            "mg_per_package": mg_per_package(r["strength_value"], r["strength_unit"], amt, unit),
            "effective_start": snap, "effective_end": None,
            "source_file": rel(zip_path), "source_member": pkg_name, "source_sha256": digest,
        })
    out = pl.DataFrame(rows, infer_schema_length=None)
    out = out.unique("ndc11", keep="first")
    print(f"  FDA NDC: {len(out):,} packages ({bad} unusable NDCs); "
          f"mg_per_package found for {out['mg_per_package'].is_not_null().sum():,}")
    return out


def load_nadac(files: list[Path]) -> pl.DataFrame:
    frames = []
    for f in files:
        lf = pl.scan_csv(f, infer_schema_length=0)
        cols = lf.collect_schema().names()
        probe = pl.DataFrame({c: [] for c in cols})
        sel = lf.select(
            pl.col(_col(probe, "NDC")).alias("ndc_raw"),
            pl.col(_col(probe, "NDC Description")).alias("ndc_description"),
            pl.col(_col(probe, "NADAC Per Unit", "NADAC_Per_Unit")).alias("nadac_per_unit"),
            pl.col(_col(probe, "Pricing Unit", "Pricing_Unit")).alias("pricing_unit"),
            pl.col(_col(probe, "Effective Date", "Effective_Date")).alias("effective_date"),
            pl.col(_col(probe, "As of Date", "As_of_Date")).alias("as_of_date"),
        ).collect()
        sel = sel.with_columns(
            pl.col("ndc_raw").str.replace_all(r"\D", "").str.zfill(11).alias("ndc11"),
            pl.col("nadac_per_unit").str.replace_all(r"[$,]", "").cast(pl.Float64, strict=False),
            pl.col("effective_date").str.to_date("%m/%d/%Y", strict=False)
            .fill_null(pl.col("effective_date").str.to_date("%Y-%m-%d", strict=False)),
            pl.col("as_of_date").str.to_date("%m/%d/%Y", strict=False)
            .fill_null(pl.col("as_of_date").str.to_date("%Y-%m-%d", strict=False)),
            pl.lit(rel(f)).alias("source_file"), pl.lit(sha256(f)).alias("source_sha256"),
        ).filter(pl.col("ndc11").str.len_chars() == 11).drop("ndc_raw")
        nulls = sel["nadac_per_unit"].null_count()
        if len(sel) == 0 or nulls / len(sel) > 0.01:
            raise ValueError(f"{f.name}: {nulls} of {len(sel)} NADAC prices are null (over 1%)")
        print(f"  NADAC {f.name}: {len(sel):,} rows")
        frames.append(sel)
    df = pl.concat(frames).unique(["ndc11", "effective_date", "pricing_unit"], keep="last")
    return df.with_columns(pl.col("effective_date").alias("effective_start"),
                           pl.lit(None, dtype=pl.Date).alias("effective_end"))


def _snapshot_date(p: Path) -> date | None:
    m = re.search(r"(20\d\d)-(\d\d)-(\d\d)", p.parent.name)
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def main() -> int:
    p = paths()
    raw, ref = p["raw"], p["ref"]
    ref.mkdir(parents=True, exist_ok=True)
    fda = sorted(raw.glob("fda_ndc/**/*.zip"))
    if fda:
        load_fda(fda[-1]).write_parquet(ref / "ref_drug_fda.parquet", compression="zstd")
    else:
        print("  NOTE no FDA NDC zip under data/raw/fda_ndc/ - skipped")
    nadac = sorted(raw.glob("nadac/**/*.csv"))
    if nadac:
        load_nadac(nadac).write_parquet(ref / "ref_nadac.parquet", compression="zstd")
    else:
        print("  NOTE no NADAC csv under data/raw/nadac/ - skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
