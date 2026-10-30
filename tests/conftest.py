"""Builds a small TEST data folder and runs the pipeline on it.

ALL NUMBERS HERE ARE MADE-UP TEST VALUES. They are not CMS or hospital prices.
They exist only so each conversion can be checked by hand. They never go
into data/ and are never shown in the app.
"""
import csv
import io
import json
import zipfile
from pathlib import Path

import pytest
from openpyxl import Workbook

DISCLAIMER = ["TEST FILE - not CMS data"]


def _zip_bytes(member: str, data: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(member, data)
    return buf.getvalue()


def _csv_text(rows) -> str:
    s = io.StringIO()
    csv.writer(s).writerows(rows)
    return s.getvalue()


ASP_HEADER = ["HCPCS Code", "Short Description", "HCPCS Code Dosage", "Payment Limit",
              "Vaccine AWP%", "Vaccine Limit"]

ASP_Q4 = [  # TEST VALUES
    ["J9271", "Inj pembrolizumab", "1 MG", "60.000", "", ""],
    ["J9299", "Inj nivolumab", "1 MG", "30.000", "", ""],
    ["J2350", "Inj ocrelizumab", "1 MG", "100.000", "", ""],
    ["J1745", "Infliximab not biosimil 10mg", "10 MG", "40.000", "", ""],
    ["J0897", "Inj denosumab", "1 MG", "20.000", "", ""],
    ["99999", "not a drug", "", "1.00", "", ""],
]
ASP_Q3 = [  # TEST VALUES
    ["J9271", "Inj pembrolizumab", "1 MG", "55.000", "", ""],
    ["J9299", "Inj nivolumab", "1 MG", "29.000", "", ""],
    ["J2350", "Inj ocrelizumab", "1 MG", "99.000", "", ""],
    ["J1745", "Infliximab not biosimil 10mg", "10 MG", "39.000", "", ""],
    ["J0897", "Inj denosumab", "1 MG", "19.000", "", ""],
]

XW_HEADER = ["HCPCS Code", "Short Description", "LABELER NAME", "NDC2", "Drug Name",
             "HCPCS dosage", "PKG SIZE", "PKG QTY", "BILLUNITS", "BILLUNITSPKG"]
XW_Q4_DENOSUMAB = [
    ["J0897", "Inj denosumab", "TEST LABELER", "55513-0710-01", "TESTDRUG D", "1 MG",
     "1", "1", "60", "60"],
]
XW_Q4_NUMERIC_NDC = [  # Excel-style number: leading zeros lost
    ["J9299", "Inj nivolumab", "TEST LABELER", "3021001.0", "TESTDRUG C", "1 MG",
     "1", "1", "40", "40"],
]
XW_Q4 = [
    ["J9271", "Inj pembrolizumab", "TEST LABELER", "00006-3026-02", "TESTDRUG A", "1 MG",
     "4", "1", "100", "100"],
    ["J1745", "Infliximab", "TEST LABELER", "57894-030-01", "TESTDRUG B", "10 MG",
     "1", "1", "10", "10"],
]

META = [["hospital_name", "last_updated_on", "version"],
        ["Test General Hospital", "2026-10-01", "2.2.0"]]

TALL_HEADER = ["description", "code|1", "code|1|type", "code|2", "code|2|type",
               "code|3", "code|3|type", "setting",
               "drug_unit_of_measurement", "drug_type_of_measurement", "standard_charge|gross",
               "standard_charge|discounted_cash", "payer_name", "plan_name",
               "standard_charge|negotiated_dollar", "standard_charge|negotiated_percentage",
               "standard_charge|negotiated_algorithm", "estimated_amount",
               "standard_charge|methodology"]
TALL_ROWS = [
    ["KEYTRUDA 100MG", "123", "CDM", "J9271", "HCPCS", "outpatient", "100", "ME", "30000",
     "15000", "Anthem Blue Cross", "PPO", "18000", "", "", "", "fee schedule"],
    ["KEYTRUDA 100MG", "123", "CDM", "J9271", "HCPCS", "outpatient", "100", "ME", "30000",
     "15000", "Aetna", "HMO", "", "50", "", "15000", "percent of total billed charges"],
    ["KEYTRUDA 100MG", "123", "CDM", "J9271", "HCPCS", "outpatient", "100", "ME", "30000",
     "15000", "UnitedHealthcare", "Choice", "", "60", "", "", "percent of total billed charges"],
    ["REMICADE 100MG", "124", "CDM", "J1745", "HCPCS", "outpatient", "100", "ME", "5000",
     "2500", "Anthem Blue Cross", "PPO", "2000", "", "", "", "fee schedule"],
    # same drug, payer, plan and price under a second charge code -> one row, duplicate_count 2
    ["REMICADE 100MG", "124B", "CDM", "J1745", "HCPCS", "outpatient", "100", "ME", "5000",
     "2500", "Anthem Blue Cross", "PPO", "2000", "", "", "", "fee schedule"],
    ["OFFICE VISIT", "99213", "CPT", "", "", "outpatient", "", "", "200", "100",
     "Anthem Blue Cross", "PPO", "150", "", "", "", "fee schedule"],
    ["OPDIVO", "125", "CDM", "J9299", "HCPCS", "outpatient", "", "", "9000", "4000",
     "Anthem Blue Cross", "PPO", "5000", "", "", "", "fee schedule"],
    ["PEMBRO NDC LINE", "126", "CDM", "00006302602", "NDC", "outpatient", "200", "ME", "60000",
     "30000", "Cigna", "OAP", "50000", "", "", "", "fee schedule"],
    ["DENOSUMAB SYR", "127", "CDM", "J0897", "HCPCS", "outpatient", "1", "ML", "4000", "2000",
     "Anthem Blue Cross", "PPO", "1500", "", "", "", "fee schedule"],
    ["KEYTRUDA 25 MG/ML SOLN", "129", "CDM", "J9271", "HCPCS", "outpatient", "4", "ML", "40000",
     "20000", "Humana", "Gold", "24000", "", "", "", "fee schedule"],
    ["REMICADE 100 MG VIAL", "130", "CDM", "J1745", "HCPCS", "outpatient", "1", "EA", "6000",
     "3000", "Humana", "Gold", "3000", "", "", "", "fee schedule"],
    ["INJ DENOSUMAB 1 MG", "131", "CDM", "J0897", "HCPCS", "outpatient", "", "", "80", "40",
     "Humana", "Gold", "40", "", "", "", "fee schedule"],
    ["OCREVUS 300MG", "128", "CDM", "J2350", "HCPCS", "outpatient", "300", "ME", "60000",
     "30000", "Paramount", "Advantage", "3", "", "", "", "fee schedule"],
    ["KEYTRUDA 25 MG/ML VIAL", "132", "CDM", "J9271", "HCPCS", "outpatient", "4", "ML", "40000",
     "20000", "Medical Mutual", "SuperMed", "66", "", "", "", "fee schedule"],
]

# old rows have 2 codes: add an empty third code
TALL_ROWS = [r[:5] + ["", ""] + r[5:] for r in TALL_ROWS]
TALL_ROWS += [
    # NDC only, no unit -> CMS crosswalk 100 billing units/package -> 12000/100/60 = 2.0
    ["KEYTRUDA VIAL", "140", "CDM", "00006302602", "NDC", "", "", "outpatient", "", "",
     "30000", "15000", "Aetna", "PPO", "12000", "", "", "", "fee schedule"],
    # HCPCS + NDC not in crosswalk, priced per ML -> FDA 25 mg/ML x 4 ML = 100 mg -> 4.0
    ["PEMBRO SOLN", "141", "CDM", "J9271", "HCPCS", "00006302603", "NDC", "outpatient", "4",
     "ML", "30000", "15000", "Aetna", "PPO", "24000", "", "", "", "fee schedule"],
    # NDC says 100 units (crosswalk), description says 50 mg -> unit_conflict
    ["KEYTRUDA 50 MG", "142", "CDM", "J9271", "HCPCS", "00006302602", "NDC", "outpatient", "1",
     "EA", "30000", "15000", "Aetna", "HMO", "9000", "", "", "", "fee schedule"],
    # same $5000 for 3 different drugs, same payer + plan -> not_drug_price
    ["DRUG A", "150", "CDM", "J9271", "HCPCS", "", "", "outpatient", "100", "ME", "", "",
     "FlatCo", "Any", "5000", "", "", "", "case rate"],
    ["DRUG B", "151", "CDM", "J9299", "HCPCS", "", "", "outpatient", "100", "ME", "", "",
     "FlatCo", "Any", "5000", "", "", "", "case rate"],
    ["DRUG C", "152", "CDM", "J2350", "HCPCS", "", "", "outpatient", "300", "ME", "", "",
     "FlatCo", "Any", "5000", "", "", "", "case rate"],
    # description repeats the HCPCS text "1 MG"; NDC = 60 mg syringe -> 1800/60/20 = 1.5, no conflict
    ["INJECTION, DENOSUMAB, 1 MG", "170", "CDM", "J0897", "HCPCS", "55513071001", "NDC",
     "outpatient", "1", "EA", "", "", "Humana", "Gold", "1800", "", "", "", "fee schedule"],
    # clinical-trial line -> study_drug
    ["STUDY DRUG - NIVOLUMAB 100 MG/10 ML", "171", "CDM", "J9299", "HCPCS", "", "", "outpatient",
     "100", "ME", "", "", "Aetna", "HMO", "3000", "", "", "", "fee schedule"],
    # drug waste line -> discarded_drug
    ["DENOSUMAB 60 MG/ML|DISCARDED DRUG", "160", "CDM", "J0897", "HCPCS", "", "", "outpatient",
     "1", "ML", "", "", "Humana", "Gold", "1500", "", "", "", "fee schedule"],
]

FDA_PACKAGE = [
    ["PRODUCTID", "PRODUCTNDC", "NDCPACKAGECODE", "PACKAGEDESCRIPTION", "STARTMARKETINGDATE",
     "ENDMARKETINGDATE", "NDC_EXCLUDE_FLAG", "SAMPLE_PACKAGE"],
    ["P1", "0006-3026", "0006-3026-02",
     "1 VIAL, SINGLE-DOSE in 1 CARTON (0006-3026-02)  > 4 mL in 1 VIAL, SINGLE-DOSE",
     "20140904", "", "N", "N"],
    ["P1", "0006-3026", "0006-3026-03",
     "1 VIAL, SINGLE-DOSE in 1 CARTON (0006-3026-03)  > 4 mL in 1 VIAL, SINGLE-DOSE",
     "20140904", "", "N", "N"],
    ["P2", "57894-030", "57894-030-01", "1 VIAL, SINGLE-USE in 1 CARTON (57894-030-01)",
     "19980824", "", "N", "N"],
]
FDA_PRODUCT = [
    ["PRODUCTID", "PRODUCTNDC", "PRODUCTTYPENAME", "PROPRIETARYNAME", "PROPRIETARYNAMESUFFIX",
     "NONPROPRIETARYNAME", "DOSAGEFORMNAME", "ROUTENAME", "STARTMARKETINGDATE",
     "ENDMARKETINGDATE", "MARKETINGCATEGORYNAME", "APPLICATIONNUMBER", "LABELERNAME",
     "SUBSTANCENAME", "ACTIVE_NUMERATOR_STRENGTH", "ACTIVE_INGRED_UNIT"],
    ["P1", "0006-3026", "HUMAN PRESCRIPTION DRUG", "TESTDRUG A", "", "pembrolizumab",
     "INJECTION, SOLUTION", "INTRAVENOUS", "20140904", "", "BLA", "BLA0", "TEST LABELER",
     "PEMBROLIZUMAB", "25", "mg/mL"],
    ["P2", "57894-030", "HUMAN PRESCRIPTION DRUG", "TESTDRUG B", "", "infliximab",
     "INJECTION, POWDER", "INTRAVENOUS", "19980824", "", "BLA", "BLA1", "TEST LABELER",
     "INFLIXIMAB", "100", "mg/1"],
]
NADAC_ROWS = [
    ["NDC Description", "NDC", "NADAC Per Unit", "Effective Date", "Pricing Unit",
     "Pharmacy Type Indicator", "OTC", "Explanation Code", "Classification for Rate Setting",
     "Corresponding Generic Drug NADAC Per Unit", "Corresponding Generic Drug Effective Date",
     "As of Date"],
    ["TEST TAB 10MG", "00093505601", "0.12345", "01/07/2026", "EA", "C/I", "N", "1", "G", "",
     "", "01/14/2026"],
    ["TEST TAB 10MG", "00093505601", "0.12000", "02/04/2026", "EA", "C/I", "N", "1", "G", "",
     "", "02/11/2026"],
]

WIDE_HEADER = ["description", "code|1", "code|1|type", "setting", "drug_unit_of_measurement",
               "drug_type_of_measurement", "standard_charge|gross",
               "standard_charge|discounted_cash",
               "standard_charge|Anthem|PPO|negotiated_dollar",
               "standard_charge|Anthem|PPO|negotiated_percentage",
               "standard_charge|Medical Mutual|SuperMed|negotiated_dollar",
               "estimated_amount|Medical Mutual|SuperMed"]
WIDE_ROWS = [["PEMBROLIZUMAB 50MG", "J9271", "HCPCS", "outpatient", "50", "ME", "20000", "9000",
              "9000", "", "6000", ""]]

JSON_FILE = {
    "hospital_name": "Test JSON Hospital",
    "last_updated_on": "2026-08-01",     # Q3 -> benchmark uses Q3 ASP
    "version": "2.0.0",
    "hospital_location": ["Test JSON Hospital"],
    "standard_charge_information": [
        {"description": "PEMBROLIZUMAB 100 MG",
         "code_information": [{"code": "J9271", "type": "HCPCS"}],
         "drug_information": {"unit": 100, "type": "ME"},
         "standard_charges": [{
             "setting": "outpatient", "gross_charge": 25000, "discounted_cash": 12000,
             "payers_information": [{"payer_name": "UnitedHealthcare", "plan_name": "Choice",
                                     "standard_charge_dollar": 11000,
                                     "methodology": "fee schedule"}]}]},
        {"description": "MRI BRAIN",
         "code_information": [{"code": "70551", "type": "CPT"}],
         "standard_charges": [{"setting": "outpatient", "gross_charge": 3000}]},
    ],
}


@pytest.fixture(scope="session")
def data_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("ia_test_data")
    raw = root / "data" / "raw"
    (raw / "cms_asp" / "2026_Q4").mkdir(parents=True)
    (raw / "cms_asp" / "2026_Q3").mkdir(parents=True)
    (raw / "cms_crosswalk" / "2026_Q4").mkdir(parents=True)

    # Q4 as CSV with junk lines before the header (like real CMS files)
    q4 = _csv_text([DISCLAIMER, ["CPT codes copyright AMA"], [], ASP_HEADER, *ASP_Q4,
                    ["Note: footer text"]])
    (raw / "cms_asp/2026_Q4/october_2026_medicare_part_b_payment_limit_file_TEST.zip"
     ).write_bytes(_zip_bytes("Oct 2026 ASP Pricing File.csv", q4.encode()))

    # Q3 as Excel with 4 junk rows
    wb = Workbook()
    ws = wb.active
    for r in [DISCLAIMER, ["x"], ["y"], ["z"], ASP_HEADER, *ASP_Q3]:
        ws.append(r)
    b = io.BytesIO()
    wb.save(b)
    (raw / "cms_asp/2026_Q3/july_2026_medicare_part_b_payment_limit_file_TEST.zip"
     ).write_bytes(_zip_bytes("July 2026 ASP Pricing File.xlsx", b.getvalue()))

    xw = _csv_text([DISCLAIMER, XW_HEADER, *XW_Q4, *XW_Q4_NUMERIC_NDC, *XW_Q4_DENOSUMAB])
    (raw / "cms_crosswalk/2026_Q4/october_2026_asp_ndc_hcpcs_crosswalk_TEST.zip"
     ).write_bytes(_zip_bytes("crosswalk.csv", xw.encode()))
    # seasonal vaccine file must be ignored
    (raw / "cms_asp/2026_Q4/2026-2027-seasonal-vaccine-price-file-TEST.zip"
     ).write_bytes(_zip_bytes("v.csv", b"x"))

    # FDA NDC directory and NADAC (TEST rows)
    fdadir = raw / "fda_ndc" / "2026-10-21"
    fdadir.mkdir(parents=True)
    tab = lambda rows: "\n".join("\t".join(r) for r in rows).encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("package.txt", tab(FDA_PACKAGE))
        z.writestr("product.txt", tab(FDA_PRODUCT))
    (fdadir / "ndctext.zip").write_bytes(buf.getvalue())
    ndir = raw / "nadac" / "2026-10-21"
    ndir.mkdir(parents=True)
    (ndir / "nadac-test.csv").write_text(_csv_text(NADAC_ROWS))

    sysdir = raw / "hospital_mrf" / "test_system" / "2026-10-21"
    sysdir.mkdir(parents=True)
    (sysdir / "cms-hpt.txt").write_text("location-name: Test\nmrf-url: http://x\n")
    (sysdir / "tall__aaaa1111.csv").write_text(_csv_text([*META, TALL_HEADER, *TALL_ROWS]))
    (sysdir / "wide__bbbb2222.csv").write_text(_csv_text([*META, WIDE_HEADER, *WIDE_ROWS]))
    # v3-style JSON that starts with a UTF-8 byte order mark (as OhioHealth and Kettering do)
    bom = dict(JSON_FILE, hospital_name="Test BOM Hospital", version="3.0.0")
    (sysdir / "bom__eeee5555.json").write_bytes(b"\xef\xbb\xbf" + json.dumps(bom).encode())
    (sysdir / "json__cccc3333.zip").write_bytes(
        _zip_bytes("test_standardcharges.json", json.dumps(JSON_FILE).encode()))
    (sysdir / "half__dddd4444.csv.part").write_text("partial download - must be ignored")
    return root


@pytest.fixture(scope="session")
def built(data_root, monkeypatch_session):
    monkeypatch_session.setenv("IA_DATA_ROOT", str(data_root))
    from pipeline import build_compare, load_asp, load_drug, parse_hpt
    assert load_asp.main() == 0
    assert load_drug.main() == 0
    assert parse_hpt.main() == 0
    assert build_compare.main() == 0
    return data_root


@pytest.fixture(scope="session")
def monkeypatch_session():
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()
