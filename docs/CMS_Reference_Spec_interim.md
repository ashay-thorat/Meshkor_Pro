# CMS Reference Spec — INTERIM (project version 0.1)

Date: 2026-10-23. Status: **interim**. Written by the project team from the MeshKor
Developer Guide (v1, 2026-10-22) and from what the real files showed during the first
build. It stands in for `MeshKor_Step1_CMS_Reference_Spec.md` (v4) until that document
is received. When v4 arrives, compare section by section and replace this file.

Each table section gives: source, files, period, how to read, columns kept, keys,
rules, checks, and known pitfalls. Items marked **(verify)** are column names expected
from the public file layout but not yet confirmed on our downloaded copy.

---

## 0. Rules for every table

1. Keep every original download in `data/raw/<source>/<period>/`. Store its SHA-256.
2. Every output row carries `effective_start`, `effective_end`, `source_file`,
   `source_member` (file inside a ZIP), `source_sha256`.
3. One loader script per table. Same input gives same output.
4. No URL, code list or unit in code. They live in `config/`.
5. Find the header row by searching for a known column. Never assume row 1.
6. Keep only rows whose key matches its code pattern:
   - HCPCS: `^[A-Z0-9]\d{3}[A-Z0-9]$`
   - NDC: 11 digits after normalization (section 0.1)
   - NPI: 10 digits. CCN: 6 characters. NPI and CCN must never be equal.
7. Parse money and quantities as numbers. Fail the load if more than 1% of a required
   numeric column is null.
8. Do not store CPT long descriptions (AMA license). HCPCS Level II text is allowed.
9. Load all states. Filter to Ohio only in downstream steps.
10. Load 2024, 2025 and 2026 for every periodic source.

### 0.1 NDC normalization (5-4-2, 11 digits)

| Input form | Rule | Example |
|---|---|---|
| 5-4-2 dashed | remove dashes | `00006-3026-02` → `00006302602` |
| 4-4-2 dashed | pad first segment | `0006-3026-02` → `00006302602` |
| 5-3-2 dashed | pad second segment | `57894-030-01` → `57894003001` |
| 5-4-1 dashed | pad third segment | `57894-0030-1` → `57894003001` |
| 11 digits, no dashes | keep | |
| 10 digits, no dashes | **reject** (ambiguous, cannot pad safely) | |

### 0.2 Quarters

ASP and crosswalk files carry the quarter in the file name: `january` = Q1, `april` = Q2,
`july` = Q3, `october` = Q4. `effective_start` = first day of the quarter,
`effective_end` = last day. Seasonal vaccine files are excluded.

---

## 1. `ref_asp` — Medicare Part B payment limit (table 10)

**Status:** implemented (`pipeline/load_asp.py`), 2026 Q1–Q4 loaded. 2024–2025 pending download.

| Item | Value |
|---|---|
| Source page | https://www.cms.gov/medicare/payment/part-b-drugs/asp-pricing-files |
| Files | `<month>_<year>_medicare_part_b_payment_limit_file*.zip` (Excel or CSV inside) |
| Period | quarterly |
| Header | search for a row with a HCPCS column and `Payment Limit` (seen 3–5 junk rows above it) |

| Column kept | Type | From |
|---|---|---|
| `hcpcs` | str | `HCPCS Code` |
| `short_description` | str | `Short Description` |
| `dosage_text` | str | `HCPCS Code Dosage` (e.g. `10 MG`) |
| `billing_qty`, `billing_unit` | float, str | parsed from dosage (`10`, `MG`) |
| `payment_limit` | float | `Payment Limit` |
| `quarter` | str | `2026Q4` |
| lineage | | section 0 |

**Key:** (`hcpcs`, `quarter`).

**Rules:**
- `Payment Limit` is already **106% of ASP**. Store as is. Never add 6% again.
- When two files exist for one quarter (an "updated" re-issue), use the later one and log it.

**Checks:** no null `payment_limit`; codes match pattern; every drug in
`config/drugs_in_scope.yaml` has a row in every quarter in scope; ASP dosage equals the
config billing unit; five J-codes spot-checked by hand against the CMS file.

**Pitfalls seen:** footer notes in the code column; Excel and CSV versions in different
quarters; numbers stored as text.

---

## 2. `ref_crosswalk` — ASP NDC-HCPCS crosswalk (table 10b)

**Status:** implemented (`pipeline/load_asp.py`), 2026 Q1–Q4 loaded.

| Item | Value |
|---|---|
| Source page | same as `ref_asp` |
| Files | `<month>_<year>_asp_ndc_hcpcs_crosswalk*.zip` |
| Header | search for a HCPCS column and an `NDC…` column |

| Column kept | Type | From |
|---|---|---|
| `hcpcs` | str | `HCPCS Code` (older files: `_<year>_CODE`) |
| `ndc11` | str | `NDC2`, normalized (section 0.1) |
| `drug_name`, `labeler` | str | `Drug Name`, `LABELER NAME` |
| `dosage_text` | str | `HCPCS dosage` |
| `pkg_size`, `pkg_qty` | float | `PKG SIZE`, `PKG QTY` |
| `bill_units`, `bill_units_pkg` | float | `BILLUNITS`, `BILLUNITSPKG` |
| `quarter` + lineage | | |

**Key:** (`ndc11`, `hcpcs`, `quarter`).

**Use:** `bill_units_pkg` = HCPCS billing units in one package. This is the **official**
unit conversion for hospital rows that carry an NDC (section 8).

**Checks:** every NDC is 11 digits; every crosswalk NDC for drugs in scope joins to
`ref_drug` (report the ones that do not).

---

## 3. `ref_drug` — FDA NDC Directory + NADAC (table 21)

**Status:** implemented (`pipeline/load_drug.py`) → `ref_drug_fda.parquet`, `ref_nadac.parquet`.

### 3a. FDA NDC Directory

| Item | Value |
|---|---|
| Source page | https://www.fda.gov/drugs/drug-approvals-and-databases/national-drug-code-directory |
| File | `ndctext.zip` → `product.txt`, `package.txt` (tab-delimited) |
| Period | snapshot (record download date) |

| Column kept | From **(verify)** |
|---|---|
| `ndc11` | `package.txt` `NDCPACKAGECODE`, normalized |
| `product_ndc` | `PRODUCTNDC` |
| `package_description` | `PACKAGEDESCRIPTION` (e.g. `1 VIAL in 1 CARTON > 4 mL in 1 VIAL`) |
| `proprietary_name`, `nonproprietary_name` | `product.txt` `PROPRIETARYNAME`, `NONPROPRIETARYNAME` |
| `dosage_form`, `route` | `DOSAGEFORMNAME`, `ROUTENAME` |
| `strength_value`, `strength_unit` | `ACTIVE_NUMERATOR_STRENGTH`, `ACTIVE_INGRED_UNIT` (e.g. `25`, `mg/mL`) |
| `marketing_start`, `marketing_end` | `STARTMARKETINGDATE`, `ENDMARKETINGDATE` |

Join `package.txt` to `product.txt` on `PRODUCTID`.

### 3b. NADAC

| Item | Value |
|---|---|
| Source page | https://data.medicaid.gov (dataset "NADAC (National Average Drug Acquisition Cost) <year>") |
| File | `nadac-national-average-drug-acquisition-cost-<date>.csv` (weekly; one dataset per year) |

| Column kept | From **(verify)** |
|---|---|
| `ndc11` | `NDC` (already 11 digits; keep leading zeros) |
| `nadac_per_unit` | `NADAC Per Unit` |
| `pricing_unit` | `Pricing Unit` (`ML`, `EA`, `GM`) |
| `effective_date` | `Effective Date` |
| `as_of_date` | `As of Date` |

**Key:** (`ndc11`, `effective_date`).

**Rule:** NADAC is pharmacy acquisition cost, mostly retail drugs. It is a reference
only. It is never the benchmark. Many infusion drugs have no NADAC row; that is expected.

**Checks:** every NDC 11 digits; read the NDC column as text (leading zeros).

---

## 4. `ref_provider` — NPPES (table 1)

**Status:** not downloaded.

| Item | Value |
|---|---|
| Source page | https://download.cms.gov/nppes/NPI_Files.html |
| Files | monthly full replacement (V.2) and monthly deactivation file |
| Size | about 9 GB unzipped. Read with Polars `scan_csv`, select columns before collect. |

| Column kept | From **(verify)** |
|---|---|
| `npi` | `NPI` |
| `entity_type` | `Entity Type Code` (1 = individual, 2 = organization) |
| `org_name` | `Provider Organization Name (Legal Business Name)` |
| `last_name`, `first_name` | `Provider Last Name (Legal Name)`, `Provider First Name` |
| `state` | `Provider Business Practice Location Address State Name` |
| `zip5` | practice location postal code, first 5 |
| `primary_taxonomy` | `Healthcare Provider Taxonomy Code_n` where `Healthcare Provider Primary Taxonomy Switch_n` = `Y` |
| `deactivation_date` | `NPI Deactivation Date` (blank → null) |

**Key:** `npi`.

**Use:** Ohio Type 2 NPIs with a hospital taxonomy (`config/hospital_taxonomies.yaml`:
282N…, 282E…, 283Q…, 284300000X and others) form the hospital list.

---

## 5. `ref_ccn_npi` — Hospital Enrollments (table 8)

**Status:** not downloaded.

| Item | Value |
|---|---|
| Source page | https://data.cms.gov/provider-characteristics/hospitals-and-other-facilities/hospital-enrollments |
| File | CSV (quarterly or monthly release) |

| Column kept | From **(verify)** |
|---|---|
| `ccn` | `CCN` |
| `npi` | `NPI` |
| `org_name` | `ORGANIZATION NAME` |
| `state` | enrollment state column |

**Key:** (`ccn`, `npi`). Store all pairs. One CCN can have several NPIs.

**Checks:** `ccn` ≠ `npi` on every row; report Ohio acute-care hospitals with no match
(target under 5%).

---

## 6. `ref_partb_spending` — Medicare Part B Spending by Drug

**Status:** not downloaded. Used only to choose the top 20 drugs.

| Item | Value |
|---|---|
| Source page | https://data.cms.gov/summary-statistics-on-use-and-payments/medicare-medicaid-spending-by-drug/medicare-part-b-spending-by-drug |

Keep HCPCS, brand and generic name, total spending per year, claim count. Select the
top 20 J-codes by latest-year spending; store them in `config/drugs_in_scope.yaml`.

---

## 7. Hospital list (Care Compare)

**Status:** downloaded (`Hospital_General_Information.csv`); not loaded.

Use for hospital name, CCN (`Facility ID`), city, county, hospital type and website.
Store websites in `config/hospital_sites.csv`.

---

## 8. Unit conversion order (applies to hospital rows, Phase 3)

The goal is the number of HCPCS billing units in the quantity the hospital priced.

| Step | Source | Status |
|---|---|---|
| 1 | Hospital `drug_unit` + `drug_type_of_measurement` in mass units (ME, GR, UN) | implemented |
| 2 | Hospital row NDC → `ref_crosswalk.bill_units_pkg` | implemented |
| 3 | NDC → `ref_drug` strength × package volume | implemented |
| 4 | Strength in the hospital's own description (mg/mL × mL, mg per vial) | implemented, fallback only |
| 5 | Reviewer-accepted reading per system (`config/pipeline.yaml`) | implemented |
| — | None of the above | `unit_unresolved`, never guessed |

When the NDC step and the description step both give an answer and they differ by more than 1%, the row gets status `unit_conflict` (implemented).

**Statuses:** `ok`, `review_range` (outside 0.5×–20×), `unit_ambiguous`,
`unit_unresolved`, `unit_conflict`, `not_drug_price`, `discarded_drug`,
`billing_unit_mismatch`, `no_benchmark`, `percent_of_charges`, `algorithm_only`. Only `ok` negotiated-dollar rows enter medians.

---

## 9. Errors to avoid (guide list + first build)

1. Header or disclaimer rows read as data.
2. Wrong column read as the rate.
3. Hand-typed sample rows in place of real data (test data stays in `tests/` only).
4. One period loaded instead of three years.
5. Lineage pointing at the wrong source file.
6. CCN filled with the NPI.
7. 6% added twice to the ASP payment limit.
8. 10-digit NDC compared with 11-digit NDC.
9. Price per package compared with ASP per billing unit.
10. JSON files that start with a UTF-8 byte order mark (OhioHealth, Kettering) — skip the BOM.
11. The same contract listed under several charge codes — fold exact repeats (`duplicate_count`).
12. Identical dollar amounts across different drugs for one payer — not a drug price.
13. "Discarded drug" (JW) lines — waste, not an administered dose.

---

## 10. Open questions for v4

- Exact column names for NPPES, Hospital Enrollments, NADAC and FDA files (marked verify).
- Required table numbering and any tables 2–7, 9, 11–20 not covered here.
- Whether `ref_crosswalk` is its own table or part of `ref_asp`.
- Folder layout: `meshkor-data/` and `hpt/raw/<ccn>/` vs the current project layout.
