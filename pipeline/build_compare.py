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
  unit_ambiguous         as posted it is outside the range, but if the price is per 1
                         billing unit it is inside. Both readings are stored. A reviewer
                         accepts the per-unit reading per system in config/pipeline.yaml.
  unit_unresolved        hospital unit missing or not convertible
  billing_unit_mismatch  ASP file dosage differs from config -> fix config
  no_benchmark           no ASP row for that HCPCS and quarter
  unit_conflict          NDC and description give different billing units -> check
  not_drug_price         same dollar amount for 3+ different drugs (flat rate / placeholder)
  discarded_drug         drug waste line (DISCARD in text or JW modifier)
  study_drug             clinical-trial study drug line (STUDY DRUG in text)
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
                     parse_hcpcs_dosage, paths, quarter_of, units_from_description)

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
    derive = bool(cfg.get("units_from_description", True))
    accept_per_unit = set(cfg.get("accept_per_billing_unit_reading") or [])
    drugs = {d["hcpcs"]: d for d in drugs_in_scope()}

    asp = pl.read_parquet(p["ref"] / "ref_asp.parquet").filter(
        pl.col("hcpcs").is_in(list(drugs)))
    quarters = sorted(asp["quarter"].unique().to_list())
    latest_q = quarters[-1] if quarters else None
    bench = {(r["hcpcs"], r["quarter"]): r for r in asp.iter_rows(named=True)}

    xw_map, fda_map = load_ndc_refs(p["ref"], set(drugs))

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

        # Unit order (CMS_Reference_Spec_interim section 8):
        # 1 posted mass unit, 2-3 NDC (crosswalk, FDA), 4 description, 5 reviewer.
        hdose = hospital_dose(r["drug_unit"], r["drug_unit_type"])
        units, reason = billing_units(hdose, conf_dose)
        method = "posted_unit" if units else None
        conflict = None
        if units is None:
            nu, nm, nnote = ndc_units(r, code, conf_dose, xw_map, fda_map)
            du = dm = dnote = None
            if derive:
                du, dm, dnote = units_from_description(r["description"], r["drug_unit"],
                                                       r["drug_unit_type"], conf_dose)
            if nu:
                units, reason, method = nu, nnote, nm
                # A description whose only strength equals one HCPCS billing unit
                # ("INJECTION, DENOSUMAB, 1 MG") repeats the code text; it is not the
                # product size. The NDC is used and no conflict is raised (decision
                # 2026-10-24, decisions_log.md).
                restates_code = du is not None and abs(du - 1.0) < 1e-9
                if du and abs(du - nu) / nu > 0.01 and not restates_code:
                    conflict = (f"NDC gives {nu:g} billing units; description gives {du:g} "
                                f"({dnote})")
                elif restates_code and abs(nu - 1.0) > 1e-9:
                    reason = f"{nnote}; description '1 unit' text treated as HCPCS code text"
            elif du:
                units, reason, method = du, dnote, dm
            else:
                reason = f"{reason}; {nnote}; {dnote or 'description not used'}"
        if units is None and hdose is None and assume_unit:
            units, reason, method = 1.0, "ASSUMED 1 billing unit (config flag)", "assumed"

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
                "billing_class": r["billing_class"], "modifiers": r["modifiers"],
                "payer_name": r["payer_name"] if per_payer else None,
                "plan_name": r["plan_name"] if per_payer else None,
                "payer_group": r["payer_group"] if per_payer else "All payers",
                "price_type": ptype, "price": price,
                "drug_unit": r["drug_unit"], "drug_unit_type": r["drug_unit_type"],
                "billing_units": units, "unit_note": reason, "unit_method": method,
                "benchmark_quarter": q,
                "asp_payment_limit": b["payment_limit"] if b else None,
                "asp_dosage": b["dosage_text"] if b else None,
                "price_per_billing_unit": None, "markup_multiple": None, "pct_over_asp": None,
                "alt_markup_per_unit": None,
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
            elif conflict:
                row["status"] = "unit_conflict"
                row["unit_note"] = conflict
            else:
                limit = b["payment_limit"]
                ppu = price / units
                m = ppu / limit
                # Second reading: the posted price is already per 1 billing unit.
                alt = price / limit if abs(units - 1) > 1e-9 else None
                row.update(price_per_billing_unit=ppu, markup_multiple=m,
                           pct_over_asp=(m - 1) * 100, alt_markup_per_unit=alt)
                if low <= m <= high:
                    row["status"] = "ok"
                elif alt is not None and low <= alt <= high:
                    if r["system"] in accept_per_unit:
                        row.update(price_per_billing_unit=price, markup_multiple=alt,
                                   pct_over_asp=(alt - 1) * 100, status="ok",
                                   unit_method="reviewer_per_billing_unit",
                                   unit_note=(f"reviewer accepted: price is per 1 billing unit "
                                              f"(package reading was {m:.3g}x)"))
                    else:
                        row["status"] = "unit_ambiguous"
                        row["unit_note"] = (f"{reason}. As posted: {m:.3g}x. If the price is "
                                            f"per 1 billing unit: {alt:.3g}x")
                else:
                    row["status"] = "review_range"
            out.append(row)

        # Contracts with no dollar figure at all: keep them visible, never priced.
        if per_payer_has_no_dollars(r):
            out.append({
                "hospital_key": key, "hospital_label": label, "system": r["system"],
                "locations": r["locations"], "hcpcs": code, "drug_name": drugs[code]["name"],
                "description": r["description"], "ndc11": r["ndc11"],
                "matched_via": r["matched_via"], "setting": r["setting"],
                "billing_class": r["billing_class"], "modifiers": r["modifiers"],
                "payer_name": r["payer_name"],
                "plan_name": r["plan_name"], "payer_group": r["payer_group"],
                "price_type": "contract_terms", "price": None,
                "drug_unit": r["drug_unit"], "drug_unit_type": r["drug_unit_type"],
                "billing_units": None, "unit_note": None, "unit_method": None,
                "benchmark_quarter": q,
                "asp_payment_limit": b["payment_limit"] if b else None,
                "asp_dosage": b["dosage_text"] if b else None,
                "price_per_billing_unit": None, "markup_multiple": None, "pct_over_asp": None,
                "alt_markup_per_unit": None,
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
        df = mark_not_drug_prices(df, int(cfg.get("flat_rate_min_drugs", 3)))
        before = len(df)
        df = dedupe(df)
        print(f"De-duplicated: {before:,} -> {len(df):,} rows "
              f"({before - len(df):,} exact repeats folded into duplicate_count)")
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


def load_ndc_refs(ref_dir, codes: set[str]) -> tuple[dict, dict]:
    """(ndc11, hcpcs) -> bill_units_pkg from the latest crosswalk quarter; ndc11 -> FDA row."""
    xw_map, fda_map = {}, {}
    xw = ref_dir / "ref_crosswalk.parquet"
    if xw.exists():
        df = (pl.read_parquet(xw, columns=["ndc11", "hcpcs", "bill_units_pkg", "quarter"])
              .filter(pl.col("hcpcs").is_in(list(codes)) & pl.col("bill_units_pkg").is_not_null())
              .sort("quarter"))
        xw_map = {(r["ndc11"], r["hcpcs"]): r for r in df.iter_rows(named=True)}
    fda = ref_dir / "ref_drug_fda.parquet"
    if fda.exists():
        df = pl.read_parquet(fda, columns=["ndc11", "mg_per_package", "package_amount",
                                           "package_unit", "package_description"])
        fda_map = {r["ndc11"]: r for r in df.iter_rows(named=True)}
    return xw_map, fda_map


def ndc_units(r: dict, code: str, billing: Dose, xw_map: dict, fda_map: dict):
    """Billing units from the row's NDC. Returns (units, method, note)."""
    ndc = r["ndc11"]
    if not ndc:
        return None, None, "no NDC on row"
    t = (r["drug_unit_type"] or "").strip().upper()
    qty = r["drug_unit"]
    xw = xw_map.get((ndc, code))
    if xw and xw["bill_units_pkg"] and t in ("", "EA"):
        n = qty if (t == "EA" and qty) else 1.0
        return (n * xw["bill_units_pkg"], "ndc_crosswalk",
                f"{n:g} package(s) x {xw['bill_units_pkg']:g} billing units/package "
                f"(CMS crosswalk {xw['quarter']}, NDC {ndc})")
    f = fda_map.get(ndc)
    if f and f["mg_per_package"] and billing.unit == "MG":
        if t == "ML" and qty and f["package_unit"] == "ML" and f["package_amount"]:
            mg = qty * f["mg_per_package"] / f["package_amount"]
            return (mg / billing.qty, "ndc_fda_concentration",
                    f"{qty:g} ML x {f['mg_per_package'] / f['package_amount']:g} mg/ML "
                    f"(FDA NDC {ndc}) = {mg:g} mg")
        if t in ("", "EA"):
            n = qty if (t == "EA" and qty) else 1.0
            mg = n * f["mg_per_package"]
            return (mg / billing.qty, "ndc_fda_package",
                    f"{n:g} package(s) x {f['mg_per_package']:g} mg (FDA NDC {ndc})")
    return None, None, f"NDC {ndc} not in crosswalk or FDA strength"


def mark_not_drug_prices(df: pl.DataFrame, min_drugs: int) -> pl.DataFrame:
    """Objective rules that need no benchmark:

    study_drug      description says STUDY DRUG (clinical-trial supply, not a market price).

    discarded_drug  description says DISCARD or the modifier is JW (drug waste).
    not_drug_price  one hospital file + payer + plan posts the same dollar amount for
                    min_drugs or more different drugs. A real drug price differs by drug;
                    an identical amount is a flat case rate, cap or placeholder.
    """
    if not len(df):
        return df
    discarded = (pl.col("description").fill_null("").str.to_uppercase().str.contains("DISCARD")
                 | pl.col("modifiers").fill_null("").str.to_uppercase().str.contains(r"\bJW\b"))
    study = pl.col("description").fill_null("").str.to_uppercase().str.contains(r"\bSTUDY DRUG\b")
    flat = (pl.col("hcpcs").n_unique()
            .over(["hospital_key", "payer_name", "plan_name", "price_type", "price"]) >= min_drugs)
    per_payer = pl.col("payer_name").is_not_null() & pl.col("price").is_not_null()
    priced = pl.col("price").is_not_null()
    keep_meta = ~pl.col("status").is_in(["percent_of_charges", "algorithm_only"])
    return df.with_columns(
        pl.when(study & keep_meta).then(pl.lit("study_drug"))
        .when(discarded & keep_meta).then(pl.lit("discarded_drug"))
        .when(per_payer & flat & keep_meta).then(pl.lit("not_drug_price"))
        .otherwise(pl.col("status")).alias("status"),
        pl.when(study & keep_meta).then(pl.lit("clinical-trial study drug line (STUDY DRUG)"))
        .when(discarded & keep_meta).then(pl.lit("drug waste line (DISCARD / JW)"))
        .when(per_payer & flat & keep_meta & priced)
        .then(pl.lit(f"same dollar amount for {min_drugs}+ different drugs (same payer, plan, file)"))
        .otherwise(pl.col("unit_note")).alias("unit_note"),
    )


def dedupe(df: pl.DataFrame) -> pl.DataFrame:
    """Fold rows that are identical in every column into one row.

    Hospital files often list the same drug, payer, plan and price under several
    charge codes. Those repeats would count one contract several times. The
    number of repeats is kept in duplicate_count.
    """
    return (df.group_by(df.columns, maintain_order=True).len()
            .rename({"len": "duplicate_count"}))


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
