"""DuckDB access to the pipeline's Parquet outputs.

Each call opens a short-lived in-memory DuckDB connection and reads Parquet
directly, so the API always shows the latest pipeline run.
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb

from pipeline.common import drugs_in_scope, paths

PRICED = ("ok", "review_range")       # statuses that carry a markup multiple


class DataMissing(Exception):
    pass


def files() -> dict[str, Path]:
    p = paths()
    return {
        "comparison": p["mart"] / "comparison.parquet",
        "run_info": p["mart"] / "run_info.json",
        "asp": p["ref"] / "ref_asp.parquet",
        "quality": p["hpt_norm"] / "hpt_file_quality.parquet",
    }


def _path(name: str) -> str:
    f = files()[name]
    if not f.exists():
        raise DataMissing(f"{f.name} not found. Run: python -m pipeline.run_all")
    return f.as_posix()


def query(sql: str, params: list | None = None, **tables: str) -> list[dict]:
    """Run SQL where {cmp}, {asp}, {quality} are replaced by read_parquet(...)."""
    con = duckdb.connect()
    try:
        sub = {k: f"read_parquet('{_path(v)}')" for k, v in tables.items()}
        cur = con.execute(sql.format(**sub), params or [])
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        con.close()


def run_info() -> dict:
    f = files()["run_info"]
    if not f.exists():
        raise DataMissing("run_info.json not found. Run: python -m pipeline.run_all")
    return json.loads(f.read_text(encoding="utf-8"))


def drug_config() -> dict[str, dict]:
    return {d["hcpcs"]: d for d in drugs_in_scope()}
