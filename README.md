# Infusion Drug Markup Audit — Phase 1 (Ohio market report)

Compares Ohio hospital negotiated prices for infusion drugs with the Medicare
benchmark (CMS ASP payment limit = ASP + 6%), per HCPCS billing unit.

```
pipeline/   Python: CMS + hospital files  ->  Parquet
backend/    Django + Django REST Framework API (reads Parquet with DuckDB)
frontend/   React + Vite dashboard
config/     drug list, review range, sources  (no codes or URLs in code)
scripts/    download_mrfs.py, build_manifest.py
tests/      pytest on made-up TEST files (never shown in the app)
data/       your downloads and outputs (not in Git)
```

## 1. Set up (Windows, once)

Copy this folder next to your existing data, so `data\raw\...` sits inside it:

```
E:\infusion-audit\
    data\raw\cms_asp\...  data\raw\hospital_mrf\...   (what you already have)
    pipeline\  backend\  frontend\  config\ ...      (this project)
```

```powershell
cd E:\infusion-audit
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
cd frontend
npm install
cd ..
```

Node.js 18 or later is needed for the frontend.

## 2. Build the data

```powershell
python -m pipeline.run_all
```

| Step | Reads | Writes |
|---|---|---|
| `load_asp` | `data/raw/cms_asp/**/*.zip`, `data/raw/cms_crosswalk/**/*.zip` | `data/ref/ref_asp.parquet`, `ref_crosswalk.parquet` |
| `parse_hpt` | `data/raw/hospital_mrf/<system>/<date>/*` | `data/hpt/norm/hpt_drug_rates.parquet`, `hpt_file_quality.parquet` |
| `build_compare` | the two above + `config/` | `data/mart/comparison.parquet`, `run_info.json` |

The ASP files can stay where they are now. The loader finds the quarter from the
file name (`october_2026_...` = 2026Q4) and skips seasonal vaccine files.
Hospital `.part` files (unfinished downloads) are skipped.

## 3. Run the app

Two terminals, both in `E:\infusion-audit` with the venv active:

```powershell
# terminal 1 - API on http://127.0.0.1:8000/api/
cd backend
python manage.py runserver

# terminal 2 - UI on http://localhost:5173
cd frontend
npm run dev
```

Pages: Drugs (overview), drug detail, Hospitals, hospital detail, All rates
(filters + CSV export), Data quality (per file), Method (calculation and limits).

API: `/api/meta`, `/api/drugs`, `/api/drugs/<hcpcs>`, `/api/hospitals`,
`/api/hospitals/<key>`, `/api/rates?hcpcs=&payer_group=&status=&price_type=&q=&sort=&order=`,
`/api/rates.csv`, `/api/quality`.

## 4. Tests

```powershell
python -m pytest
```

31 tests. They build a small folder of made-up files (CSV tall, CSV wide, JSON
in a ZIP, ASP as CSV and as Excel with junk header rows) and check every
conversion against hand-computed values.

## How a markup is computed

1. Hospital quantity from `drug_unit_of_measurement` + `drug_type_of_measurement`
   (ME = mg, GR = g, UN/F2 = units, ML, EA).
2. Billing units = hospital quantity ÷ HCPCS billing unit (from `config/drugs_in_scope.yaml`,
   checked against the ASP file's dosage column every run).
3. Price per billing unit = rate ÷ billing units.
4. Markup = price per billing unit ÷ ASP payment limit for the quarter of the hospital
   file's `last_updated_on` date (latest quarter if that one is not loaded).

Row status: `ok`, `review_range` (outside 0.5×–20×), `unit_unresolved`,
`billing_unit_mismatch`, `no_benchmark`, `percent_of_charges`, `algorithm_only`.
Only `ok` negotiated-dollar rows go into medians. No unit is guessed: rows priced
per ML or EA, or with no unit, are listed but not priced.

## Current limits (Phase 1 slice)

- Drug list is a provisional starter of 5. Replace with the top 20 by Part B spend.
- No drug has a `reviewed_by` yet. The UI marks every drug "not yet reviewed".
- Hospitals are keyed by price file, not CCN. NPPES + Hospital Enrollments add CCN/NPI later.
- UH Cleveland files are not downloaded yet. Run `python scripts/download_mrfs.py` later.
- ASP history is 2026 only. Add 2024–2025 ZIPs to `data/raw/cms_asp/` and rerun.
- PDF report export is not built yet (CSV export works).
- Percent-of-charges contracts are shown, not priced.
