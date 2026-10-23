"""Convert hospital drug rates to price per HCPCS billing unit and compare with ASP.

Input : data/ref/ref_asp.parquet, data/hpt/norm/hpt_drug_rates.parquet,
        config/drugs_in_scope.yaml, config/pipeline.yaml
Output: data/mart/comparison.parquet   one row per hospital rate x price type
        data/mart/run_info.json        what this run used

Markup multiple = hospital price per billing unit / ASP payment limit (same unit).
The ASP payment limit is already ASP + 6%.

Status values (only "ok" and "review_range" carry a markup):
  ok                     converted, inside the review range
  review_range           converted, markup outside the range -> check by hand
  unit_unresolved        hospital unit missing or not convertible
  billing_unit_mismatch  ASP file dosage differs from config -> fix config
  no_benchmark           no ASP row for that HCPCS and quarter
  percent_of_charges     contract is a % of charges; no dollar amount posted
  algorithm_only         contract is a formula; no dollar amount posted

Run: python -m pipeline.build_compare
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone

import polars as pl

from .common import (Dose, billing_units, drugs_in_scope, hospital_dose, load_yaml,
                     parse_hcpcs_dosage, paths, quarter_of)

PRICE_TYPES = [
    # (column in hpt_drug_rates, price_type label, per payer?)
    ("negotiated_dollar", "negotiated_dollar", True),
    ("estimated_amount", "estimated_amount", True),
    ("median_amount", "median_allowed", True),
    ("discounted_cash", "cash", False),
    ("gross_charge", "gross_charge", False),
]


def hospital_key(system: str, source_file: str, member: str) -> str:
    return hashlib.sha1(f"{system}|{source_file}|{member}".encode()).hexdigest()[:10]


def main() -> int:
    p = paths()
    cfg = load_yaml("pipeline.yaml")
    low, high = cfg["review_range"]["low"], cfg["review_range"]["high"]
    assume_unit = bool(cfg.get("assume_hcpcs_unit_when_missing"))
    drugs = {d["hcpcs"]: d for d in drugs_in_scope()}

    asp = pl.read_parquet(p["ref"] / "ref_asp.parquet").filter(
        pl.col("hcpcs").is_in(list(drugs)))
    quarters = sorted(asp["quarter"].unique().to_list())
    latest_q = quarters[-1] if quarters else None
    bench = {(r["hcpcs"], r["quarter"]): r for r in asp.iter_rows(named=True)}

    rates = pl.read_parquet(p["hpt_norm"] / "hpt_drug_rates.parquet")
    out: list[dict] = []
    seen_hosp_level: set = set()

    for r in rates.iter_rows(named=True):
        code = r["hcpcs"]
        fq = quarter_of(r["file_last_updated"]) if r["file_last_updated"] else None
        if cfg.get("benchmark_quarter") == "file_date" and fq in quarters:
            q = fq
        else:
            q = latest_q
        b = bench.get((code, q))
        conf = drugs[code]["billing_unit"]
        conf_dose = Dose(float(conf["qty"]), str(conf["unit"]).upper())
        asp_dose = parse_hcpcs_dosage(b["dosage_text"]) if b else None

        hdose = hospital_dose(r["drug_unit"], r["drug_unit_type"])
        units, reason = billing_units(hdose, conf_dose)
        if units is None and hdose is None and assume_unit:
            units, reason = 1.0, "ASSUMED 1 billing unit (config flag)"

        key = hospital_key(r["system"], r["source_file"], r["source_member"])
        label = r["hospital_name"] or r["locations"] or r["source_member"]

        for col, ptype, per_payer in PRICE_TYPES:
            price = r[col]
            if price is None:
                continue
            if not per_payer:
                k = (key, code, r["description"], r["setting"], r["drug_unit"],
                     r["drug_unit_type"], ptype, price)
                if k in seen_hosp_level:
                    continue
                seen_hosp_level.add(k)

            row = {
                "hospital_key": key, "hospital_label": label, "system": r["system"],
                "locations": r["locations"], "hcpcs": code, "drug_name": drugs[code]["name"],
                "description": r["description"], "ndc11": r["ndc11"],
                "matched_via": r["matched_via"], "setting": r["setting"],
                "billing_class": r["billing_class"],
                "payer_name": r["payer_name"] if per_payer else None,
                "plan_name": r["plan_name"] if per_payer else None,
                "payer_group": r["payer_group"] if per_payer else "All payers",
                "price_type": ptype, "price": price,
                "drug_unit": r["drug_unit"], "drug_unit_type": r["drug_unit_type"],
                "billing_units": units, "unit_note": reason,
                "benchmark_quarter": q,
                "asp_payment_limit": b["payment_limit"] if b else None,
                "asp_dosage": b["dosage_text"] if b else None,
                "price_per_billing_unit": None, "markup_multiple": None, "pct_over_asp": None,
                "negotiated_percentage": r["negotiated_percentage"] if per_payer else None,
                "methodology": r["methodology"] if per_payer else None,
                "file_last_updated": r["file_last_updated"],
                "reviewed": drugs[code].get("reviewed_by") is not None,
                "source_file": r["source_file"], "source_member": r["source_member"],
                "source_sha256": r["source_sha256"],
            }
            if b is None or b["payment_limit"] is None:
                row["status"] = "no_benchmark"
            elif asp_dose is None or asp_dose != conf_dose:
                row["status"] = "billing_unit_mismatch"
                row["unit_note"] = (f"ASP dosage '{b['dosage_text']}' vs config "
                                    f"{conf['qty']} {conf['unit']}")
            elif units is None or units <= 0:
                row["status"] = "unit_unresolved"
            else:
                ppu = price / units
                m = ppu / b["payment_limit"]
                row.update(price_per_billing_unit=ppu, markup_multiple=m,
                           pct_over_asp=(m - 1) * 100,
                           status="ok" if low <= m <= high else "review_range")
            out.append(row)

        # Contracts with no dollar figure at all: keep them visible, never priced.
        if per_payer_has_no_dollars(r):
            out.append({
                "hospital_key": key, "hospital_label": label, "system": r["system"],
                "locations": r["locations"], "hcpcs": code, "drug_name": drugs[code]["name"],
                "description": r["description"], "ndc11": r["ndc11"],
                "matched_via": r["matched_via"], "setting": r["setting"],
                "billing_class": r["billing_class"], "payer_name": r["payer_name"],
                "plan_name": r["plan_name"], "payer_group": r["payer_group"],
                "price_type": "contract_terms", "price": None,
                "drug_unit": r["drug_unit"], "drug_unit_type": r["drug_unit_type"],
                "billing_units": None, "unit_note": None, "benchmark_quarter": q,
                "asp_payment_limit": b["payment_limit"] if b else None,
                "asp_dosage": b["dosage_text"] if b else None,
                "price_per_billing_unit": None, "markup_multiple": None, "pct_over_asp": None,
                "negotiated_percentage": r["negotiated_percentage"],
                "methodology": r["methodology"], "file_last_updated": r["file_last_updated"],
                "reviewed": drugs[code].get("reviewed_by") is not None,
                "source_file": r["source_file"], "source_member": r["source_member"],
                "source_sha256": r["source_sha256"],
                "status": ("percent_of_charges" if r["negotiated_percentage"] is not None
                           else "algorithm_only"),
            })

    p["mart"].mkdir(parents=True, exist_ok=True)
    df = pl.DataFrame(out, infer_schema_length=None)
    if len(df):
        df = unique_labels(df)
    df.write_parquet(p["mart"] / "comparison.parquet", compression="zstd")
    info = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "asp_quarters": quarters,
        "benchmark_rule": cfg.get("benchmark_quarter"),
        "review_range": [low, high],
        "assume_hcpcs_unit_when_missing": assume_unit,
        "drugs": list(drugs),
        "rows": len(df),
        "source_files": sorted(rates["source_file"].unique().to_list()) if len(rates) else [],
    }
    (p["mart"] / "run_info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    if len(df):
        print(df.group_by("status").len().sort("len", descending=True))
    print(f"Wrote {len(df):,} comparison rows")
    return 0


def unique_labels(df: pl.DataFrame) -> pl.DataFrame:
    """Two files with the same hospital name get the file name added, so they stay apart."""
    keys = df.select("hospital_key", "hospital_label", "source_member").unique("hospital_key")
    dup = keys.group_by("hospital_label").len().filter(pl.col("len") > 1)["hospital_label"]
    fix = {
        r["hospital_key"]: f'{r["hospital_label"]} · {r["source_member"].rsplit("/", 1)[-1][:40]}'
        for r in keys.filter(pl.col("hospital_label").is_in(dup.to_list())).iter_rows(named=True)
    }
    if not fix:
        return df
    return df.with_columns(
        pl.col("hospital_key").replace_strict(fix, default=pl.col("hospital_label"))
        .alias("hospital_label"))


def per_payer_has_no_dollars(r: dict) -> bool:
    return (r["payer_name"] is not None
            and r["negotiated_dollar"] is None
            and r["estimated_amount"] is None
            and r["median_amount"] is None
            and (r["negotiated_percentage"] is not None or r["negotiated_algorithm"]))


if __name__ == "__main__":
    sys.exit(main())
