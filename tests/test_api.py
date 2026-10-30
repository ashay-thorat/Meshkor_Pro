"""API tests: Django test client against the pipeline output built from TEST data."""
import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"


@pytest.fixture(scope="module")
def django_env(built, tmp_path_factory):
    """Django with a fresh SQLite file, migrated, and one user per role (TEST users)."""
    os.environ["IA_DB_PATH"] = str(tmp_path_factory.mktemp("db") / "test.sqlite3")
    sys.path.insert(0, str(BACKEND))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "auditapi.settings")
    import django
    django.setup()
    from django.contrib.auth.models import Group, User
    from django.core.management import call_command
    call_command("migrate", verbosity=0)
    call_command("setup_roles", verbosity=0)
    users = {}
    for name, role in (("t_admin", "admin"), ("t_reviewer", "reviewer"),
                       ("t_viewer", "viewer"), ("t_norole", None)):
        u, _ = User.objects.get_or_create(username=name)
        u.set_password("Test-Pass-12345")
        u.is_superuser = u.is_staff = role == "admin"
        u.save()
        if role in ("reviewer", "viewer"):
            u.groups.add(Group.objects.get(name=role))
        users[role or "none"] = u
    return users


@pytest.fixture(scope="module")
def client(django_env):
    from django.test import Client
    c = Client()
    c.force_login(django_env["viewer"])
    return c


def test_meta(client):
    r = client.get("/api/meta").json()
    assert r["asp_quarters"] == ["2026Q3", "2026Q4"]
    assert r["hospitals"] == 4
    assert {s["status"] for s in r["statuses"]} >= {"ok", "unit_unresolved"}


def test_drugs_headline_uses_ok_rows_only(client):
    rows = {d["hcpcs"]: d for d in client.get("/api/drugs").json()}
    assert set(rows) == {"J9271", "J9299", "J2350", "J1745", "J0897"}
    k = rows["J9271"]
    assert k["asp_payment_limit"] == 60.0 and k["asp_quarter"] == "2026Q4"
    # negotiated_dollar ok rows for J9271: 3.0, 4.1667 (NDC), 4.0 (per ML), 2.0 (NDC crosswalk),
    # 4.0 (FDA) (tall), 3.0, 2.0 (wide), 2.0 (json), 2.0 (BOM json) -> median 3.0
    assert k["rates"] == 9
    assert k["median_markup"] == pytest.approx(3.0)
    assert rows["J2350"]["rates"] == 0 and rows["J2350"]["review_rows"] == 1
    assert rows["J9299"]["median_markup"] is None
    assert rows["J0897"]["rates"] == 2


def test_drug_detail(client):
    d = client.get("/api/drugs/J9271").json()
    assert [a["quarter"] for a in d["asp"]] == ["2026Q3", "2026Q4"]
    assert len(d["hospitals"]) == 4
    assert client.get("/api/drugs/J0000").status_code == 404


def test_rates_filter_and_sort(client):
    r = client.get("/api/rates", {"hcpcs": "J9271", "price_type": "negotiated_dollar",
                                  "status": "ok", "sort": "markup_multiple"}).json()
    assert r["total"] == 9
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
    assert len(client.get("/api/quality").json()) == 4



# ---------- login and roles ----------

def test_api_needs_login(django_env):
    from django.test import Client
    c = Client()
    assert c.get("/api/drugs").status_code == 403
    assert c.get("/api/rates.csv").status_code == 403
    assert c.get("/api/report.pdf").status_code == 403
    assert c.get("/api/auth/me").status_code == 401


def test_login_flow_and_csrf(django_env):
    from django.test import Client
    c = Client(enforce_csrf_checks=True)
    c.get("/api/auth/csrf")
    token = c.cookies["csrftoken"].value
    bad = c.post("/api/auth/login", {"username": "t_viewer", "password": "wrong"},
                 content_type="application/json", HTTP_X_CSRFTOKEN=token)
    assert bad.status_code == 400
    ok = c.post("/api/auth/login", {"username": "t_viewer", "password": "Test-Pass-12345"},
                content_type="application/json", HTTP_X_CSRFTOKEN=token)
    assert ok.status_code == 200 and ok.json()["role"] == "viewer"
    assert ok.json()["can_review"] is False
    assert c.get("/api/drugs").status_code == 200
    # no CSRF token -> rejected
    assert c.post("/api/auth/logout").status_code == 403


def test_user_without_role_cannot_log_in(django_env):
    from django.test import Client
    r = Client().post("/api/auth/login", {"username": "t_norole", "password": "Test-Pass-12345"},
                      content_type="application/json")
    assert r.status_code == 400 and "no role" in r.json()["error"]


def test_login_rate_limit(django_env):
    from django.test import Client
    c = Client()
    codes = [c.post("/api/auth/login", {"username": "t_admin", "password": "nope"},
                    content_type="application/json").status_code for _ in range(6)]
    assert codes[:5] == [400] * 5 and codes[5] == 429
    from django.core.cache import cache
    cache.clear()


def test_signoff_roles_and_pdf(django_env):
    from django.test import Client
    viewer, reviewer = Client(), Client()
    viewer.force_login(django_env["viewer"])
    reviewer.force_login(django_env["reviewer"])
    s = viewer.get("/api/signoff").json()
    assert s["signed"] is False and len(s["comparison_sha256"]) == 64
    assert viewer.post("/api/signoff", {"note": "x"}, content_type="application/json").status_code == 403

    draft = viewer.get("/api/report.pdf")
    assert draft.status_code == 200 and draft["Content-Type"] == "application/pdf"
    assert draft.content[:5] == b"%PDF-" and "DRAFT" in draft["Content-Disposition"]

    r = reviewer.post("/api/signoff", {"note": "checked sample"}, content_type="application/json")
    assert r.status_code == 200 and r.json()["signed"] is True
    assert r.json()["signed_by"] == "t_reviewer"
    signed = viewer.get("/api/report.pdf", {"hcpcs": "J9271"})
    assert "signed" in signed["Content-Disposition"]


def test_pdf_text(django_env):
    from django.test import Client
    from pypdf import PdfReader
    import io
    c = Client()
    c.force_login(django_env["admin"])
    pdf = PdfReader(io.BytesIO(c.get("/api/report.pdf").content))
    text = " ".join(p.extract_text() for p in pdf.pages)
    assert "Drugs ranked by median markup" in text
    assert "J9271" in text and "Pembrolizumab" in text
    assert "Sources" in text and "SHA-256" in text
    assert "Method" in text and "Limits" in text
