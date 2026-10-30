"""Explain why rows are unit_unresolved and why some files have 0 drug rows.

Run from the infusion-audit folder:  python scripts/diagnose.py > diagnose.txt
Reads only pipeline outputs and raw file headers. Changes nothing.
"""
import csv
import io
import sys
import zipfile
from pathlib import Path

import json

import duckdb
import ijson

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.common import drugs_in_scope, paths  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
p = paths()
cmp_ = (p["mart"] / "comparison.parquet").as_posix()
rates = (p["hpt_norm"] / "hpt_drug_rates.parquet").as_posix()
qual = (p["hpt_norm"] / "hpt_file_quality.parquet").as_posix()
con = duckdb.connect()


def show(title, sql):
    print(f"\n=== {title} ===")
    print(con.sql(sql))


show("0. How billing units were found (compared + review rows)", f"""
    SELECT coalesce(unit_method, '(none)') unit_method, status, count(*) n FROM '{cmp_}'
    GROUP BY 1, 2 ORDER BY 1, 3 DESC""")

show("1. Why units are unresolved", f"""
    SELECT unit_note, count(*) n FROM '{cmp_}' WHERE status = 'unit_unresolved'
    GROUP BY 1 ORDER BY 2 DESC LIMIT 15""")

show("2. Drug unit type posted, by system", f"""
    SELECT system, coalesce(drug_unit_type, '(none)') unit_type, count(*) n
    FROM '{rates}' GROUP BY 1, 2 ORDER BY 1, 3 DESC""")

show("3. Sample rows with no unit (description shows strength?)", f"""
    SELECT system, hcpcs, description, count(*) n FROM '{rates}'
    WHERE drug_unit IS NULL GROUP BY 1, 2, 3 ORDER BY 4 DESC LIMIT 25""")

show("4. Sample rows priced per ML / EA", f"""
    SELECT system, hcpcs, description, drug_unit, drug_unit_type, count(*) n FROM '{rates}'
    WHERE upper(drug_unit_type) IN ('ML','EA') GROUP BY ALL ORDER BY n DESC LIMIT 25""")

show("5. Review-range rows: markup spread by drug", f"""
    SELECT hcpcs, count(*) n, round(min(markup_multiple), 3) min_x,
           round(median(markup_multiple), 3) med_x, round(max(markup_multiple), 1) max_x
    FROM '{cmp_}' WHERE status = 'review_range' GROUP BY 1 ORDER BY 1""")

show("6. Compared rows: markup by drug", f"""
    SELECT hcpcs, count(*) n, round(min(markup_multiple), 2) min_x,
           round(median(markup_multiple), 2) med_x, round(max(markup_multiple), 2) max_x
    FROM '{cmp_}' WHERE status = 'ok' AND price_type = 'negotiated_dollar'
    GROUP BY 1 ORDER BY 1""")

show("7. Files with 0 drug rows or an error", f"""
    SELECT system, source_member, format, items_scanned, error FROM '{qual}'
    WHERE drug_rows = 0 OR error IS NOT NULL ORDER BY 1""")

# 8. For 0-row files: do the J-codes appear anywhere in the raw text?
print("\n=== 8. Raw search of 0-row files for in-scope J-codes ===")
codes = [d["hcpcs"] for d in drugs_in_scope()]
zero = con.sql(f"SELECT DISTINCT source_file, source_member FROM '{qual}' "
               "WHERE drug_rows = 0").fetchall()
root = Path(__file__).resolve().parent.parent
for src, member in zero:
    f = Path(src) if Path(src).is_absolute() else root / src
    try:
        if zipfile.is_zipfile(f):
            fh = zipfile.ZipFile(f).open(member)
        else:
            fh = f.open("rb")
        text = io.TextIOWrapper(fh, encoding="utf-8", errors="replace")
        header, found, lines = None, {c: 0 for c in codes}, 0
        for i, line in enumerate(text):
            if header is None and "description" in line.lower():
                header = line.strip()[:400]
            for c in codes:
                if c in line:
                    found[c] += 1
            lines = i
        print(f"\n{member}: {lines:,} lines; J-code hits: {found}")
        print(f"  header: {header}")
    except Exception as e:  # noqa: BLE001
        print(f"\n{member}: could not read ({e})")


# 9. One drug item from a CMS v3.0 JSON file, to check field names.
print("\n=== 9. Sample drug item from a v3.0 JSON file ===")
row = con.execute(f"SELECT source_file, source_member FROM '{qual}' "
              "WHERE cms_version LIKE '3%' AND format = 'json' LIMIT 1").fetchone()
if row:
    f = root / row[0]
    fh = f.open("rb")
    if fh.peek(3)[:3] == b"\xef\xbb\xbf":
        fh.read(3)
    for item in ijson.items(fh, "standard_charge_information.item", use_float=True):
        codes = {c.get("code") for c in item.get("code_information", [])}
        if codes & set(codes_in := [d["hcpcs"] for d in drugs_in_scope()]):
            sc = item.get("standard_charges", [{}])
            if sc and sc[0].get("payers_information"):
                sc[0]["payers_information"] = sc[0]["payers_information"][:2]
            print(row[1])
            print(json.dumps(item, indent=1, default=str)[:3000])
            break
else:
    print("no v3.0 JSON file parsed")
