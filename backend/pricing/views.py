"""API views. Headline numbers use negotiated dollar rates with status 'ok' only.

Rows flagged review_range, unit_unresolved, percent_of_charges, etc. are
counted and listed, but never mixed into medians.
"""
from __future__ import annotations

import csv
import io

from django.http import HttpResponse
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import data

HEADLINE = "price_type = 'negotiated_dollar' AND status = 'ok'"

RATE_COLUMNS = [
    "hospital_label", "system", "hcpcs", "drug_name", "description", "setting",
    "payer_group", "payer_name", "plan_name", "price_type", "price", "drug_unit",
    "drug_unit_type", "billing_units", "price_per_billing_unit", "benchmark_quarter",
    "asp_payment_limit", "markup_multiple", "pct_over_asp", "status", "unit_note",
    "negotiated_percentage", "methodology", "ndc11", "matched_via", "reviewed",
    "file_last_updated", "source_file", "source_member", "source_sha256", "hospital_key",
]
SORTABLE = {"markup_multiple", "price_per_billing_unit", "price", "hospital_label",
            "payer_group", "drug_name", "status"}


def _missing(e: data.DataMissing) -> Response:
    return Response({"error": str(e)}, status=503)


@api_view(["GET"])
def meta(request):
    try:
        info = data.run_info()
        statuses = data.query("SELECT status, count(*) AS n FROM {cmp} GROUP BY 1 ORDER BY 2 DESC",
                              cmp="comparison")
        counts = data.query(
            "SELECT count(DISTINCT hospital_key) AS hospitals, count(DISTINCT system) AS systems,"
            f" count(*) FILTER (WHERE {HEADLINE}) AS headline_rates FROM {{cmp}}",
            cmp="comparison")[0]
    except data.DataMissing as e:
        return _missing(e)
    return Response({**info, "statuses": statuses, **counts})


@api_view(["GET"])
def drugs(request):
    cfg = data.drug_config()
    try:
        latest = data.query(
            "SELECT hcpcs, quarter, payment_limit, dosage_text FROM {asp} "
            "WHERE hcpcs IN (SELECT unnest(?)) "
            "QUALIFY row_number() OVER (PARTITION BY hcpcs ORDER BY quarter DESC) = 1",
            [list(cfg)], asp="asp")
        stats = data.query(
            f"""SELECT hcpcs,
                   count(DISTINCT hospital_key) FILTER (WHERE {HEADLINE}) AS hospitals_priced,
                   count(*) FILTER (WHERE {HEADLINE}) AS rates,
                   median(markup_multiple) FILTER (WHERE {HEADLINE}) AS median_markup,
                   min(markup_multiple) FILTER (WHERE {HEADLINE}) AS min_markup,
                   max(markup_multiple) FILTER (WHERE {HEADLINE}) AS max_markup,
                   count(*) FILTER (WHERE status = 'review_range') AS review_rows,
                   count(*) FILTER (WHERE status NOT IN ('ok','review_range')) AS excluded_rows
                FROM {{cmp}} GROUP BY hcpcs""", cmp="comparison")
    except data.DataMissing as e:
        return _missing(e)
    asp = {r["hcpcs"]: r for r in latest}
    st = {r["hcpcs"]: r for r in stats}
    out = []
    for code, d in cfg.items():
        a, s = asp.get(code, {}), st.get(code, {})
        out.append({
            "hcpcs": code, "name": d["name"], "brand": d.get("brand"),
            "billing_unit": f'{d["billing_unit"]["qty"]:g} {d["billing_unit"]["unit"]}',
            "reviewed_by": d.get("reviewed_by"),
            "asp_quarter": a.get("quarter"), "asp_payment_limit": a.get("payment_limit"),
            "asp_dosage": a.get("dosage_text"),
            "hospitals_priced": s.get("hospitals_priced", 0), "rates": s.get("rates", 0),
            "median_markup": s.get("median_markup"), "min_markup": s.get("min_markup"),
            "max_markup": s.get("max_markup"), "review_rows": s.get("review_rows", 0),
            "excluded_rows": s.get("excluded_rows", 0),
        })
    return Response(out)


@api_view(["GET"])
def drug_detail(request, hcpcs: str):
    cfg = data.drug_config()
    code = hcpcs.upper()
    if code not in cfg:
        return Response({"error": f"{code} is not in config/drugs_in_scope.yaml"}, status=404)
    try:
        asp = data.query("SELECT quarter, payment_limit, dosage_text, short_description, "
                         "source_file, source_sha256 FROM {asp} WHERE hcpcs = ? ORDER BY quarter",
                         [code], asp="asp")
        hospitals = data.query(
            f"""SELECT hospital_key, any_value(hospital_label) AS hospital_label,
                   any_value(system) AS system,
                   count(*) AS rates, count(DISTINCT payer_group) AS payer_groups,
                   median(markup_multiple) AS median_markup,
                   min(markup_multiple) AS min_markup, max(markup_multiple) AS max_markup,
                   median(price_per_billing_unit) AS median_price_per_unit,
                   any_value(asp_payment_limit) AS asp_payment_limit,
                   any_value(benchmark_quarter) AS benchmark_quarter
                FROM {{cmp}} WHERE hcpcs = ? AND {HEADLINE}
                GROUP BY hospital_key ORDER BY median_markup DESC""", [code], cmp="comparison")
        payers = data.query(
            f"""SELECT payer_group, count(*) AS rates, count(DISTINCT hospital_key) AS hospitals,
                   median(markup_multiple) AS median_markup,
                   min(markup_multiple) AS min_markup, max(markup_multiple) AS max_markup
                FROM {{cmp}} WHERE hcpcs = ? AND {HEADLINE}
                GROUP BY 1 ORDER BY median_markup DESC""", [code], cmp="comparison")
        statuses = data.query("SELECT status, count(*) AS n FROM {cmp} WHERE hcpcs = ? "
                              "GROUP BY 1 ORDER BY 2 DESC", [code], cmp="comparison")
    except data.DataMissing as e:
        return _missing(e)
    d = cfg[code]
    return Response({
        "hcpcs": code, "name": d["name"], "brand": d.get("brand"),
        "billing_unit": f'{d["billing_unit"]["qty"]:g} {d["billing_unit"]["unit"]}',
        "reviewed_by": d.get("reviewed_by"),
        "asp": asp, "hospitals": hospitals, "payers": payers, "statuses": statuses,
    })


@api_view(["GET"])
def hospitals(request):
    try:
        rows = data.query(
            f"""SELECT hospital_key, any_value(hospital_label) AS hospital_label,
                   any_value(system) AS system, any_value(locations) AS locations,
                   any_value(file_last_updated) AS file_last_updated,
                   count(DISTINCT hcpcs) FILTER (WHERE {HEADLINE}) AS drugs_priced,
                   count(*) FILTER (WHERE {HEADLINE}) AS rates,
                   median(markup_multiple) FILTER (WHERE {HEADLINE}) AS median_markup,
                   max(markup_multiple) FILTER (WHERE {HEADLINE}) AS max_markup,
                   count(*) FILTER (WHERE status = 'review_range') AS review_rows,
                   count(*) FILTER (WHERE status NOT IN ('ok','review_range')) AS excluded_rows
                FROM {{cmp}} GROUP BY hospital_key
                ORDER BY median_markup DESC NULLS LAST""", cmp="comparison")
    except data.DataMissing as e:
        return _missing(e)
    return Response(rows)


@api_view(["GET"])
def hospital_detail(request, key: str):
    try:
        drugs_ = data.query(
            f"""SELECT hcpcs, any_value(drug_name) AS drug_name, count(*) AS rates,
                   median(markup_multiple) AS median_markup,
                   min(markup_multiple) AS min_markup, max(markup_multiple) AS max_markup,
                   any_value(asp_payment_limit) AS asp_payment_limit,
                   median(price_per_billing_unit) AS median_price_per_unit
                FROM {{cmp}} WHERE hospital_key = ? AND {HEADLINE}
                GROUP BY hcpcs ORDER BY median_markup DESC""", [key], cmp="comparison")
        info = data.query("SELECT any_value(hospital_label) AS hospital_label, "
                          "any_value(system) AS system, any_value(locations) AS locations, "
                          "any_value(file_last_updated) AS file_last_updated, "
                          "any_value(source_file) AS source_file, "
                          "any_value(source_sha256) AS source_sha256, "
                          "count(*) AS n_rows FROM {cmp} WHERE hospital_key = ?",
                          [key], cmp="comparison")
        statuses = data.query("SELECT status, count(*) AS n FROM {cmp} WHERE hospital_key = ? "
                              "GROUP BY 1 ORDER BY 2 DESC", [key], cmp="comparison")
    except data.DataMissing as e:
        return _missing(e)
    if not info or not info[0]["n_rows"]:
        return Response({"error": "hospital not found"}, status=404)
    return Response({**info[0], "hospital_key": key, "drugs": drugs_, "statuses": statuses})


def _rate_filters(request) -> tuple[str, list]:
    where, params = [], []
    for field in ("hcpcs", "hospital_key", "payer_group", "price_type", "status", "system"):
        v = request.GET.get(field)
        if v:
            vals = v.split(",")
            where.append(f"{field} IN (SELECT unnest(?))")
            params.append(vals)
    q = request.GET.get("q")
    if q:
        where.append("(hospital_label ILIKE ? OR payer_name ILIKE ? OR plan_name ILIKE ? "
                     "OR description ILIKE ?)")
        params += [f"%{q}%"] * 4
    return ("WHERE " + " AND ".join(where)) if where else "", params


@api_view(["GET"])
def rates(request):
    where, params = _rate_filters(request)
    sort = request.GET.get("sort", "markup_multiple")
    sort = sort if sort in SORTABLE else "markup_multiple"
    order = "ASC" if request.GET.get("order") == "asc" else "DESC"
    limit = min(int(request.GET.get("limit", 100)), 1000)
    offset = max(int(request.GET.get("offset", 0)), 0)
    cols = ", ".join(RATE_COLUMNS)
    try:
        total = data.query(f"SELECT count(*) AS n FROM {{cmp}} {where}", params,
                           cmp="comparison")[0]["n"]
        rows = data.query(f"SELECT {cols} FROM {{cmp}} {where} "
                          f"ORDER BY {sort} {order} NULLS LAST LIMIT {limit} OFFSET {offset}",
                          params, cmp="comparison")
    except data.DataMissing as e:
        return _missing(e)
    return Response({"total": total, "limit": limit, "offset": offset, "rows": rows})


@api_view(["GET"])
def rates_csv(request):
    where, params = _rate_filters(request)
    try:
        rows = data.query(f"SELECT {', '.join(RATE_COLUMNS)} FROM {{cmp}} {where} "
                          "ORDER BY hcpcs, markup_multiple DESC NULLS LAST", params,
                          cmp="comparison")
        info = data.run_info()
    except data.DataMissing as e:
        return _missing(e)
    buf = io.StringIO()
    buf.write(f"# Infusion Drug Markup Audit export. Pipeline run {info['generated_at']}. "
              "Markup = price per HCPCS billing unit / CMS ASP payment limit (ASP+6%).\n")
    w = csv.DictWriter(buf, fieldnames=RATE_COLUMNS)
    w.writeheader()
    w.writerows(rows)
    resp = HttpResponse(buf.getvalue(), content_type="text/csv")
    resp["Content-Disposition"] = 'attachment; filename="infusion_audit_rates.csv"'
    return resp


@api_view(["GET"])
def quality(request):
    try:
        rows = data.query("SELECT * FROM {quality} ORDER BY system, source_file", quality="quality")
    except data.DataMissing as e:
        return _missing(e)
    return Response(rows)
