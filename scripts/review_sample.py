"""Write a sample of rows for a reviewer to check by hand.

Run from the infusion-audit folder:
    python scripts/review_sample.py                       # status unit_ambiguous
    python scripts/review_sample.py review_range          # status review_range

Output: reports/review_<status>.csv  (up to 5 rows per system x drug x direction)
        plus a summary on screen.

review_range rows have a markup below 0.5x ("low") or above 20x ("high").
For each sample row the reviewer writes in reviewer_decision one of:
    unit_error_per_unit   price is per 1 billing unit, not per package
    unit_error_other      another unit problem (explain in a note)
    real_price            the price is right; the markup is real
    bad_row               not a usable rate (placeholder, $0.01, test row)
"""
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.common import PROJECT, load_yaml, paths  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
status = sys.argv[1] if len(sys.argv) > 1 else "unit_ambiguous"
cfg = load_yaml("pipeline.yaml")["review_range"]
low = float(cfg["low"])
cmp_ = (paths()["mart"] / "comparison.parquet").as_posix()
out = PROJECT / "reports" / f"review_{status}.csv"
out.parent.mkdir(exist_ok=True)
con = duckdb.connect()

base = f"""
    SELECT *, CASE WHEN markup_multiple < {low} THEN 'low' ELSE 'high' END AS direction
    FROM '{cmp_}' WHERE status = '{status}'"""

print(f"=== {status}: rows by system, direction and how the unit was found ===")
print(con.sql(f"""
    SELECT system, direction, coalesce(unit_method, '(none)') AS unit_method,
           count(*) AS n_rows,
           round(median(markup_multiple), 3) AS median_as_posted,
           round(median(alt_markup_per_unit), 2) AS median_if_per_unit
    FROM ({base}) GROUP BY ALL ORDER BY system, direction, n_rows DESC"""))

print(f"=== {status}: rows by drug ===")
print(con.sql(f"""
    SELECT hcpcs, any_value(drug_name) AS drug, direction, count(*) AS n_rows,
           round(median(price), 2) AS median_price,
           round(median(asp_payment_limit), 2) AS asp_per_unit
    FROM ({base}) GROUP BY hcpcs, direction ORDER BY hcpcs, direction"""))

con.execute(f"""
    COPY (
      SELECT system, hospital_label, hcpcs, drug_name, direction, description,
             payer_name, plan_name, price_type, price, drug_unit, drug_unit_type,
             unit_method, billing_units, asp_payment_limit,
             round(markup_multiple, 4) AS markup_as_posted,
             round(alt_markup_per_unit, 3) AS markup_if_per_unit,
             duplicate_count, unit_note, '' AS reviewer_decision, '' AS reviewer_note,
             source_file, source_sha256
      FROM ({base})
      QUALIFY row_number() OVER (PARTITION BY system, hcpcs, direction
                                 ORDER BY hash(source_sha256, description, payer_name)) <= 5
      ORDER BY system, hcpcs, direction
    ) TO '{out.as_posix()}' (HEADER, DELIMITER ',')""")
n = con.execute(f"SELECT count(*) FROM read_csv('{out.as_posix()}')").fetchone()[0]
print(f"Wrote {n} sample rows to {out}")
