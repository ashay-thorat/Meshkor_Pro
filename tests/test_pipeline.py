"""Pipeline tests on made-up TEST data (see conftest.py). Expected values are hand-computed."""
from datetime import date

import polars as pl
import pytest

from pipeline.common import (Dose, billing_units, hospital_dose, norm_hcpcs, norm_ndc,
                             parse_hcpcs_dosage, payer_group, quarter_from_filename)


# ---------- unit helpers ----------

@pytest.mark.parametrize("raw,expected", [
    ("00006-3026-02", "00006302602"),   # 5-4-2
    ("0006-3026-02", "00006302602"),    # 4-4-2
    ("57894-030-01", "57894003001"),    # 5-3-2
    ("57894-0030-1", "57894003001"),    # 5-4-1
    ("00006302602", "00006302602"),     # already 11
    ("0006302602", None),               # undashed 10 digits: ambiguous
    ("", None), (None, None), ("abc", None),
])
def test_norm_ndc(raw, expected):
    assert norm_ndc(raw) == expected


def test_norm_hcpcs():
    assert norm_hcpcs(" j9271 ") == "J9271"
    assert norm_hcpcs("Note:") is None
    assert norm_hcpcs("123456") is None


def test_dosage_parse():
    assert parse_hcpcs_dosage("10 MG") == Dose(10, "MG")
    assert parse_hcpcs_dosage("1 MG") == Dose(1, "MG")
    assert parse_hcpcs_dosage("100 UNITS") == Dose(100, "UNIT")
    assert parse_hcpcs_dosage("0.5 G") == Dose(500, "MG")


def test_billing_units():
    bu10 = Dose(10, "MG")
    assert billing_units(hospital_dose("100", "ME"), bu10)[0] == 10
    assert billing_units(hospital_dose("1", "GR"), bu10)[0] == 100
    assert billing_units(hospital_dose("1", "ML"), bu10)[0] is None
    assert billing_units(None, bu10)[0] is None
    assert billing_units(hospital_dose("100", "UN"), bu10)[0] is None   # unit mismatch


def test_quarter_and_payer():
    assert quarter_from_filename("october_2026_medicare_part_b_payment_limit_file.zip") == "2026Q4"
    assert quarter_from_filename("january_2026_ndc_hcpcs_crosswalk_updated_033026.zip") == "2026Q1"
    assert quarter_from_filename("2026-2027-seasonal-vaccine.zip") is None
    assert quarter_from_filename("jan-2024-asp-pricing-file.zip") == "2024Q1"
    assert quarter_from_filename("2025-october-asp-ndc-hcpcs-crosswalk.zip") == "2025Q4"
    assert quarter_from_filename("oct2025_payment_limit.zip") == "2025Q4"
    assert payer_group("Anthem Blue Cross") == "Anthem"
    assert payer_group("UMR") == "UnitedHealthcare"
    assert payer_group(None) == "Not stated"


# ---------- end to end ----------

def _cmp(built):
    return pl.read_parquet(built / "data/mart/comparison.parquet")


def _one(df, **eq):
    sub = df
    for k, v in eq.items():
        sub = sub.filter(pl.col(k) == v)
    assert len(sub) == 1, f"expected 1 row for {eq}, got {len(sub)}"
    return sub.row(0, named=True)


def test_asp_loaded(built):
    asp = pl.read_parquet(built / "data/ref/ref_asp.parquet")
    assert sorted(asp["quarter"].unique()) == ["2026Q3", "2026Q4"]
    q4 = _one(asp, hcpcs="J9271", quarter="2026Q4")
    assert q4["payment_limit"] == 60.0          # stored as is, no extra 6%
    assert q4["effective_start"] == date(2026, 10, 1)
    assert q4["effective_end"] == date(2026, 12, 31)
    assert asp["payment_limit"].null_count() == 0
    assert asp["source_sha256"].null_count() == 0
    assert "Note:" not in asp["hcpcs"].to_list()


def test_crosswalk_ndc_11(built):
    xw = pl.read_parquet(built / "data/ref/ref_crosswalk.parquet")
    assert set(xw["ndc11"]) == {"00006302602", "57894003001", "00003021001", "55513071001"}


def test_tall_dollar_rate(built):
    r = _one(_cmp(built), hcpcs="J9271", payer_name="Anthem Blue Cross",
             price_type="negotiated_dollar", source_member="tall__aaaa1111.csv")
    # 18000 for 100 mg -> 180 per mg; ASP Q4 60 -> 3.0x
    assert r["billing_units"] == 100
    assert r["price_per_billing_unit"] == pytest.approx(180)
    assert r["markup_multiple"] == pytest.approx(3.0)
    assert r["benchmark_quarter"] == "2026Q4"
    assert r["status"] == "ok"


def test_ten_mg_billing_unit(built):
    r = _one(_cmp(built), hcpcs="J1745", price_type="negotiated_dollar",
             description="REMICADE 100MG")
    # 2000 for 100 mg = 10 billing units of 10 mg -> 200 per unit; ASP 40 -> 5.0x
    assert r["billing_units"] == 10
    assert r["markup_multiple"] == pytest.approx(5.0)


def test_percent_only_and_estimate(built):
    df = _cmp(built)
    est = _one(df, payer_name="Aetna", price_type="estimated_amount")
    assert est["markup_multiple"] == pytest.approx(2.5)        # 15000/100/60
    uhc = _one(df, payer_name="UnitedHealthcare", source_member="tall__aaaa1111.csv")
    assert uhc["status"] == "percent_of_charges"
    assert uhc["markup_multiple"] is None
    assert uhc["negotiated_percentage"] == 60


def test_unresolved_units_are_not_priced(built):
    df = _cmp(built)
    op = _one(df, hcpcs="J9299", price_type="negotiated_dollar", description="OPDIVO")
    assert op["status"] == "unit_unresolved" and op["markup_multiple"] is None
    den = _one(df, hcpcs="J0897", price_type="negotiated_dollar", description="DENOSUMAB SYR")
    assert den["status"] == "unit_unresolved" and "ML" in den["unit_note"]


def test_ndc_only_row_matched_through_crosswalk(built):
    r = _one(_cmp(built), payer_name="Cigna", price_type="negotiated_dollar")
    assert r["hcpcs"] == "J9271" and r["matched_via"] == "ndc_crosswalk"
    assert r["markup_multiple"] == pytest.approx(50000 / 200 / 60)


def test_out_of_range_flagged(built):
    r = _one(_cmp(built), hcpcs="J2350", price_type="negotiated_dollar",
             description="OCREVUS 300MG")
    # 3 for 300 mg: 0.0001x as posted, 0.03x even per unit -> plain review_range
    assert r["markup_multiple"] == pytest.approx(0.0001)
    assert r["status"] == "review_range"


def test_unit_ambiguous_keeps_both_readings(built):
    r = _one(_cmp(built), description="KEYTRUDA 25 MG/ML VIAL", price_type="negotiated_dollar")
    # as posted: 66 / 100 mg / 60 = 0.011x; if 66 is per 1 mg: 1.1x
    assert r["status"] == "unit_ambiguous"
    assert r["markup_multiple"] == pytest.approx(0.011)
    assert r["alt_markup_per_unit"] == pytest.approx(1.1)


def test_wide_csv(built):
    df = _cmp(built).filter(pl.col("source_member") == "wide__bbbb2222.csv")
    a = _one(df, payer_name="Anthem", price_type="negotiated_dollar")
    m = _one(df, payer_name="Medical Mutual", price_type="negotiated_dollar")
    assert a["markup_multiple"] == pytest.approx(3.0)    # 9000/50/60
    assert m["markup_multiple"] == pytest.approx(2.0)    # 6000/50/60
    assert m["payer_group"] == "Medical Mutual"


def test_json_in_zip_uses_file_quarter(built):
    r = _one(_cmp(built), source_member="test_standardcharges.json",
             price_type="negotiated_dollar")
    assert r["benchmark_quarter"] == "2026Q3"             # file dated 2026-08-01
    assert r["markup_multiple"] == pytest.approx(11000 / 100 / 55)
    assert r["hospital_label"] == "Test JSON Hospital"


def test_gross_and_cash_not_repeated_per_payer(built):
    df = _cmp(built).filter((pl.col("source_member") == "tall__aaaa1111.csv")
                            & (pl.col("description") == "KEYTRUDA 100MG"))
    assert len(df.filter(pl.col("price_type") == "gross_charge")) == 1
    assert len(df.filter(pl.col("price_type") == "cash")) == 1


def test_non_drug_rows_and_part_files_skipped(built):
    rates = pl.read_parquet(built / "data/hpt/norm/hpt_drug_rates.parquet")
    assert "OFFICE VISIT" not in rates["description"].to_list()
    assert "MRI BRAIN" not in rates["description"].to_list()
    q = pl.read_parquet(built / "data/hpt/norm/hpt_file_quality.parquet")
    assert not any(s.endswith(".part") for s in q["source_file"])
    assert q["error"].null_count() == len(q)


# ---------- strength from the hospital description ----------

def test_strength_parser():
    from pipeline.common import strength_from_description as sd
    assert sd("KEYTRUDA 25 MG/ML INTRAVENOUS SOLUTION")["mg_per_ml"] == 25
    assert sd("OPDIVO 240 MG/24 ML INTRAVENOUS SOLUTION")["mg_per_ml"] == 10
    assert sd("PEMBROLIZUMAB 100 MG/4ML IV SOLN")["mg_per_ml"] == 25
    x = sd("XGEVA 120 MG/1.7 ML (70 MG/ML) SUBCUTANEOUS SOLUTION")["mg_per_ml"]
    assert 1.7 * x == pytest.approx(120)
    assert sd("REMICADE 100 MG INTRAVENOUS SOLUTION")["mg_each"] == 100
    assert sd("INJ DENOSUMAB 1 MG")["mg_each"] == 1
    assert sd("Inj pembrolizumab") == {"mg_per_ml": None, "mg_each": None, "text": None}
    assert sd("DRUG 100 MG OR 200 MG")["mg_each"] is None        # two strengths: ambiguous


def test_per_ml_row_uses_concentration(built):
    r = _one(_cmp(built), description="KEYTRUDA 25 MG/ML SOLN", price_type="negotiated_dollar")
    # 4 ML x 25 mg/ML = 100 mg; 24000 / 100 = 240 per mg; / 60 = 4.0
    assert r["unit_method"] == "description_concentration"
    assert r["billing_units"] == 100
    assert r["markup_multiple"] == pytest.approx(4.0)


def test_per_vial_row_uses_strength(built):
    r = _one(_cmp(built), description="REMICADE 100 MG VIAL", price_type="negotiated_dollar")
    # 1 EA x 100 mg = 10 billing units of 10 mg; 3000 / 10 = 300; / 40 = 7.5
    assert r["unit_method"] == "description_strength"
    assert r["markup_multiple"] == pytest.approx(7.5)


def test_no_unit_row_when_description_is_the_hcpcs_unit(built):
    r = _one(_cmp(built), description="INJ DENOSUMAB 1 MG", price_type="negotiated_dollar")
    assert r["unit_method"] == "description_matches_hcpcs_unit"
    assert r["markup_multiple"] == pytest.approx(2.0)          # 40 / 1 / 20


def test_posted_unit_marked(built):
    r = _one(_cmp(built), description="REMICADE 100MG", price_type="negotiated_dollar")
    assert r["unit_method"] == "posted_unit"


def test_json_with_bom_is_read(built):
    q = pl.read_parquet(built / "data/hpt/norm/hpt_file_quality.parquet")
    row = q.filter(pl.col("source_member") == "bom__eeee5555.json").row(0, named=True)
    assert row["error"] is None and row["drug_rows"] == 1 and row["cms_version"] == "3.0.0"



def test_exact_repeats_are_folded(built):
    r = _one(_cmp(built), description="REMICADE 100MG", price_type="negotiated_dollar")
    assert r["duplicate_count"] == 2
    g = _one(_cmp(built), description="REMICADE 100MG", price_type="gross_charge")
    assert g["duplicate_count"] == 1      # gross/cash were already kept once per item



# ---------- FDA / NADAC reference tables ----------

def test_package_amount_and_strength():
    from pipeline.load_drug import mg_per_package, package_amount
    assert package_amount("1 VIAL, SINGLE-DOSE in 1 CARTON (0006-3026-02)  > 4 mL in 1 VIAL, "
                          "SINGLE-DOSE") == (4.0, "ML")
    assert package_amount("1 VIAL, SINGLE-USE in 1 CARTON (57894-030-01)") == (1.0, "VIAL")
    assert package_amount("2 SYRINGE in 1 CARTON > 1.7 mL in 1 SYRINGE") == (3.4, "ML")
    assert mg_per_package("25", "mg/mL", 4.0, "ML") == 100
    assert mg_per_package("100", "mg/1", 1.0, "VIAL") == 100
    assert mg_per_package("25", "mg/mL", 1.0, "VIAL") is None       # units do not fit
    assert mg_per_package("25; 10", "mg/mL; mg/mL", 4.0, "ML") is None  # two ingredients


def test_ref_drug_tables(built):
    fda = pl.read_parquet(built / "data/ref/ref_drug_fda.parquet")
    r = _one(fda, ndc11="00006302602")
    assert r["mg_per_package"] == 100 and r["package_unit"] == "ML"
    assert _one(fda, ndc11="57894003001")["mg_per_package"] == 100
    nadac = pl.read_parquet(built / "data/ref/ref_nadac.parquet")
    assert len(nadac) == 2 and nadac["ndc11"].str.len_chars().unique().to_list() == [11]
    assert nadac["nadac_per_unit"].null_count() == 0


# ---------- NDC units, conflict, flat rate, discarded ----------

def test_ndc_only_row_uses_crosswalk_package(built):
    r = _one(_cmp(built), description="KEYTRUDA VIAL", price_type="negotiated_dollar")
    assert r["unit_method"] == "ndc_crosswalk" and r["billing_units"] == 100
    assert r["markup_multiple"] == pytest.approx(2.0)


def test_ndc_fda_concentration(built):
    r = _one(_cmp(built), description="PEMBRO SOLN", price_type="negotiated_dollar")
    assert r["unit_method"] == "ndc_fda_concentration" and r["billing_units"] == 100
    assert r["markup_multiple"] == pytest.approx(4.0)


def test_ndc_and_description_disagree(built):
    r = _one(_cmp(built), description="KEYTRUDA 50 MG", price_type="negotiated_dollar")
    assert r["status"] == "unit_conflict" and r["markup_multiple"] is None


def test_flat_rate_across_drugs(built):
    df = _cmp(built).filter((pl.col("payer_name") == "FlatCo")
                            & (pl.col("price_type") == "negotiated_dollar"))
    assert len(df) == 3 and set(df["status"]) == {"not_drug_price"}


def test_discarded_drug_line(built):
    r = _one(_cmp(built), description="DENOSUMAB 60 MG/ML|DISCARDED DRUG",
             price_type="negotiated_dollar")
    assert r["status"] == "discarded_drug"



def test_description_restating_code_unit_uses_ndc(built):
    r = _one(_cmp(built), description="INJECTION, DENOSUMAB, 1 MG", price_type="negotiated_dollar")
    assert r["status"] == "ok" and r["unit_method"] == "ndc_crosswalk"
    assert r["billing_units"] == 60
    assert r["markup_multiple"] == pytest.approx(1.5)


def test_study_drug_line(built):
    r = _one(_cmp(built), description="STUDY DRUG - NIVOLUMAB 100 MG/10 ML",
             price_type="negotiated_dollar")
    assert r["status"] == "study_drug"
