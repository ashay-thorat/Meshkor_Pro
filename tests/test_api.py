"""API tests: Django test client against the pipeline output built from TEST data."""
import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"


@pytest.fixture(scope="module")
def client(built):
    sys.path.insert(0, str(BACKEND))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "auditapi.settings")
    import django
    django.setup()
    from django.test import Client
    return Client()


def test_meta(client):
    r = client.get("/api/meta").json()
    assert r["asp_quarters"] == ["2026Q3", "2026Q4"]
    assert r["hospitals"] == 3
    assert {s["status"] for s in r["statuses"]} >= {"ok", "unit_unresolved"}


def test_drugs_headline_uses_ok_rows_only(client):
    rows = {d["hcpcs"]: d for d in client.get("/api/drugs").json()}
    assert set(rows) == {"J9271", "J9299", "J2350", "J1745", "J0897"}
    k = rows["J9271"]
    assert k["asp_payment_limit"] == 60.0 and k["asp_quarter"] == "2026Q4"
    # negotiated_dollar ok rows for J9271: 3.0 (tall), 4.1667 (NDC), 3.0, 2.0 (wide), 2.0 (json)
    assert k["rates"] == 5
    assert k["median_markup"] == pytest.approx(3.0)
    assert rows["J2350"]["rates"] == 0 and rows["J2350"]["review_rows"] == 1
    assert rows["J9299"]["median_markup"] is None


def test_drug_detail(client):
    d = client.get("/api/drugs/J9271").json()
    assert [a["quarter"] for a in d["asp"]] == ["2026Q3", "2026Q4"]
    assert len(d["hospitals"]) == 3
    assert client.get("/api/drugs/J0000").status_code == 404


def test_rates_filter_and_sort(client):
    r = client.get("/api/rates", {"hcpcs": "J9271", "price_type": "negotiated_dollar",
                                  "status": "ok", "sort": "markup_multiple"}).json()
    assert r["total"] == 5
    m = [x["markup_multiple"] for x in r["rows"]]
    assert m == sorted(m, reverse=True)
    # unsafe sort value falls back to markup_multiple
    assert client.get("/api/rates", {"sort": "1; DROP TABLE x"}).status_code == 200


def test_csv_export(client):
    r = client.get("/api/rates.csv", {"hcpcs": "J1745"})
    assert r.status_code == 200
    body = r.content.decode()
    assert body.startswith("# Infusion Drug Markup Audit export")
    assert "source_sha256" in body


def test_hospital_detail_and_quality(client):
    hs = client.get("/api/hospitals").json()
    key = hs[0]["hospital_key"]
    d = client.get(f"/api/hospitals/{key}").json()
    assert d["hospital_key"] == key and d["drugs"]
    assert len(client.get("/api/quality").json()) == 3
