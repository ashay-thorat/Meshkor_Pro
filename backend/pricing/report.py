"""PDF market report (developer guide section 3.4).

Every page carries a banner: "DRAFT - NOT SIGNED OFF" until a reviewer signs off the
current pipeline run, then "Signed off by <name> on <date>".

Headline numbers use negotiated dollar rates with status "ok" only, the same rule as
the web app. Nothing in this report is estimated or filled in.
"""
from __future__ import annotations

import io
from datetime import datetime, timezone

from reportlab.graphics.charts.barcharts import HorizontalBarChart
from reportlab.graphics.shapes import Drawing, Line, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

from pipeline.common import load_yaml

from . import data

HEADLINE = "price_type = 'negotiated_dollar' AND status = 'ok'"

INK = colors.HexColor("#1d2327")
MUTED = colors.HexColor("#66707a")
LINE = colors.HexColor("#d9d5cc")
ACCENT = colors.HexColor("#0e5c63")
DRAFT = colors.HexColor("#8c2f1c")
OKC = colors.HexColor("#24603a")
ZEBRA = colors.HexColor("#f5f4f0")

STATUS_TEXT = {
    "ok": "Compared", "review_range": "Check by hand (outside range)",
    "unit_ambiguous": "Unit ambiguous", "unit_unresolved": "Unit not convertible",
    "unit_conflict": "NDC and description disagree",
    "not_drug_price": "Same $ for many drugs", "discarded_drug": "Discarded drug line",
    "study_drug": "Clinical-trial study drug", "billing_unit_mismatch": "ASP unit differs",
    "no_benchmark": "No ASP benchmark", "percent_of_charges": "% of charges only",
    "algorithm_only": "Formula only",
}

ss = getSampleStyleSheet()
S = {
    "title": ParagraphStyle("t", parent=ss["Title"], fontName="Helvetica-Bold", fontSize=20,
                            leading=24, textColor=INK, alignment=TA_LEFT, spaceAfter=4),
    "h1": ParagraphStyle("h1", parent=ss["Heading1"], fontName="Helvetica-Bold", fontSize=14,
                         leading=18, textColor=INK, spaceBefore=6, spaceAfter=6),
    "h2": ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=11,
                         leading=14, textColor=INK, spaceBefore=8, spaceAfter=4),
    "body": ParagraphStyle("b", parent=ss["BodyText"], fontName="Helvetica", fontSize=9,
                           leading=12.5, textColor=INK, spaceAfter=5),
    "small": ParagraphStyle("s", parent=ss["BodyText"], fontName="Helvetica", fontSize=7.5,
                            leading=9.5, textColor=MUTED),
    "cell": ParagraphStyle("c", fontName="Helvetica", fontSize=7.5, leading=9, textColor=INK),
    "cellb": ParagraphStyle("cb", fontName="Helvetica-Bold", fontSize=7.5, leading=9,
                            textColor=INK),
    "hash": ParagraphStyle("h", fontName="Courier", fontSize=5.8, leading=7, textColor=MUTED),
}


def x(v):
    return "-" if v is None else f"{v:.2f}×"


def usd(v):
    if v is None:
        return "-"
    return f"${v:,.3f}" if v < 10 else f"${v:,.2f}"


def n(v):
    return "-" if v is None else f"{v:,}"


def esc(text) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def P(text, style="cell", raw=False):
    """Table cell. raw=True keeps <br/> and <b> markup; callers escape the data parts."""
    return Paragraph(str(text) if raw else esc(text), S[style])


def table(rows, widths, num_cols=(), header_rows=1):
    t = Table(rows, colWidths=widths, repeatRows=header_rows)
    style = [
        ("FONT", (0, 0), (-1, header_rows - 1), "Helvetica-Bold", 7.5),
        ("TEXTCOLOR", (0, 0), (-1, header_rows - 1), MUTED),
        ("LINEBELOW", (0, header_rows - 1), (-1, header_rows - 1), 0.6, LINE),
        ("FONT", (0, header_rows), (-1, -1), "Helvetica", 7.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]
    for c in num_cols:
        style.append(("ALIGN", (c, 0), (c, -1), "RIGHT"))
    for i in range(header_rows, len(rows)):
        if (i - header_rows) % 2 == 1:
            style.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
    t.setStyle(TableStyle(style))
    return t


def markup_chart(items, width=6.9 * inch):
    """items: [(label, value)] -> horizontal bars with a 1x Medicare line."""
    items = [(lab, v) for lab, v in items if v is not None]
    if not items:
        return Spacer(1, 1)
    h = 26 + 18 * len(items)
    d = Drawing(width, h + 16)
    c = HorizontalBarChart()
    c.x, c.y, c.width, c.height = 150, 8, width - 175, h
    c.data = [[v for _, v in reversed(items)]]
    c.categoryAxis.categoryNames = [lab[:34] for lab, _ in reversed(items)]
    c.categoryAxis.labels.fontName = "Helvetica"
    c.categoryAxis.labels.fontSize = 7
    c.categoryAxis.labels.boxAnchor = "e"
    c.categoryAxis.strokeColor = LINE
    top = max(2, int(max(v for _, v in items)) + 1)
    c.valueAxis.valueMin, c.valueAxis.valueMax = 0, top
    c.valueAxis.valueStep = 1 if top <= 8 else 2
    c.valueAxis.labels.fontName = "Helvetica"
    c.valueAxis.labels.fontSize = 7
    c.valueAxis.labelTextFormat = lambda v: f"{v:g}×"
    c.valueAxis.strokeColor = LINE
    c.valueAxis.visibleGrid = True
    c.valueAxis.gridStrokeColor = colors.HexColor("#ece9e2")
    c.bars[0].fillColor = ACCENT
    c.bars[0].strokeColor = None
    c.barWidth = 10
    d.add(c)
    x1 = c.x + c.width * (1 / top)
    d.add(Line(x1, c.y, x1, c.y + c.height + 4, strokeColor=INK, strokeDashArray=[3, 2],
               strokeWidth=0.6))
    d.add(String(x1 + 2, c.y + c.height + 4, "Medicare (ASP+6%)", fontName="Helvetica",
                 fontSize=6.5, fillColor=MUTED))
    return KeepTogether([d, Spacer(1, 10)])


# ---------- data ----------

def gather(hcpcs: list[str] | None):
    cfg = data.drug_config()
    codes = [c for c in cfg if not hcpcs or c in hcpcs]
    info = data.run_info()
    q = lambda sql, params=None, **t: data.query(sql, params, **t)  # noqa: E731

    drugs = q(f"""
        SELECT hcpcs, count(DISTINCT hospital_key) AS hospitals, count(*) AS rates,
               median(markup_multiple) AS med, quantile_cont(markup_multiple, 0.25) AS p25,
               quantile_cont(markup_multiple, 0.75) AS p75,
               median(price_per_billing_unit - asp_payment_limit) AS excess
        FROM {{cmp}} WHERE {HEADLINE} AND hcpcs IN (SELECT unnest(?)) GROUP BY hcpcs""",
              [codes], cmp="comparison")
    dstat = {r["hcpcs"]: r for r in drugs}
    asp = {r["hcpcs"]: r for r in q(
        "SELECT hcpcs, quarter, payment_limit, dosage_text FROM {asp} WHERE hcpcs IN "
        "(SELECT unnest(?)) QUALIFY row_number() OVER (PARTITION BY hcpcs ORDER BY quarter DESC)=1",
        [codes], asp="asp")}

    per_drug = {}
    for c in codes:
        per_drug[c] = {
            "hospitals": q(f"""
                SELECT any_value(hospital_label) AS label, any_value(system) AS system,
                       count(*) AS rates, median(price_per_billing_unit) AS ppu,
                       any_value(asp_payment_limit) AS asp, median(markup_multiple) AS med,
                       min(markup_multiple) AS lo, max(markup_multiple) AS hi
                FROM {{cmp}} WHERE {HEADLINE} AND hcpcs = ?
                GROUP BY hospital_key ORDER BY med DESC""", [c], cmp="comparison"),
            "payers": q(f"""
                SELECT payer_group, count(*) AS rates, count(DISTINCT hospital_key) AS hospitals,
                       median(markup_multiple) AS med, min(markup_multiple) AS lo,
                       max(markup_multiple) AS hi
                FROM {{cmp}} WHERE {HEADLINE} AND hcpcs = ?
                GROUP BY 1 ORDER BY med DESC""", [c], cmp="comparison"),
        }
    statuses = q("SELECT status, count(*) AS n FROM {cmp} WHERE hcpcs IN (SELECT unnest(?)) "
                 "GROUP BY 1 ORDER BY 2 DESC", [codes], cmp="comparison")
    totals = q(f"SELECT count(DISTINCT hospital_key) AS files, count(DISTINCT system) AS systems, "
               f"count(*) FILTER (WHERE {HEADLINE}) AS rates FROM {{cmp}} "
               f"WHERE hcpcs IN (SELECT unnest(?))", [codes], cmp="comparison")[0]
    asp_files = q("SELECT quarter, any_value(source_member) AS member, any_value(source_file) AS file, "
                  "any_value(source_sha256) AS sha FROM {asp} GROUP BY quarter ORDER BY quarter",
                  asp="asp")
    hosp_files = q("SELECT system, any_value(hospital_label) AS label, source_file AS file, "
                   "any_value(file_last_updated) AS updated, any_value(source_sha256) AS sha "
                   "FROM {cmp} GROUP BY system, source_file ORDER BY system, label",
                   cmp="comparison")
    return {"cfg": cfg, "codes": codes, "info": info, "dstat": dstat, "asp": asp,
            "per_drug": per_drug, "statuses": statuses, "totals": totals,
            "asp_files": asp_files, "hosp_files": hosp_files,
            "pipeline_cfg": load_yaml("pipeline.yaml")}


# ---------- build ----------

def build_pdf(signoff: dict, hcpcs: list[str] | None = None, user: str = "") -> bytes:
    g = gather(hcpcs)
    buf = io.BytesIO()
    made = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    signed = signoff.get("signed")
    banner = (f"Signed off by {signoff['signed_by']} on {signoff['signed_at'][:10]}" if signed
              else "DRAFT - NOT SIGNED OFF. Do not share outside the project team.")

    def on_page(canv, doc):
        w, h = letter
        canv.saveState()
        canv.setFillColor(OKC if signed else DRAFT)
        canv.rect(0, h - 22, w, 22, stroke=0, fill=1)
        canv.setFillColor(colors.white)
        canv.setFont("Helvetica-Bold", 8.5)
        canv.drawString(0.6 * inch, h - 14.5, banner)
        canv.setFillColor(MUTED)
        canv.setFont("Helvetica", 7)
        canv.drawString(0.6 * inch, 0.4 * inch,
                        f"Ohio Infusion Drug Markup Report  |  pipeline run {g['info']['generated_at']}"
                        f"  |  comparison sha256 {signoff['comparison_sha256'][:16]}...")
        canv.drawRightString(w - 0.6 * inch, 0.4 * inch, f"Page {doc.page}")
        canv.restoreState()

    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=0.6 * inch, rightMargin=0.6 * inch,
                            topMargin=0.65 * inch, bottomMargin=0.65 * inch,
                            title="Ohio Infusion Drug Markup Report",
                            author="Infusion Drug Markup Audit")
    st = []
    W = letter[0] - 1.2 * inch

    # ---- cover / summary
    st += [Paragraph("Ohio Infusion Drug Markup Report", S["title"]),
           Paragraph(f"Hospital negotiated prices compared with the Medicare Part B payment limit "
                     f"(ASP + 6%), per HCPCS billing unit. Generated {made}"
                     + (f" by {user}" if user else "") + ".", S["small"]),
           Spacer(1, 10)]
    t = g["totals"]
    quarters = g["info"]["asp_quarters"]
    st.append(table([
        ["Hospital price files", "Hospital systems", "Compared rates", "ASP quarters", "Drugs"],
        [n(t["files"]), n(t["systems"]), n(t["rates"]),
         f"{quarters[0]} - {quarters[-1]}" if quarters else "-", str(len(g["codes"]))],
    ], [W / 5] * 5))
    st.append(Spacer(1, 8))
    unreviewed = [c for c in g["codes"] if not g["cfg"][c].get("reviewed_by")]
    if unreviewed:
        st.append(Paragraph(
            f"<b>Unit review pending</b> for {len(unreviewed)} of {len(g['codes'])} drugs "
            f"({', '.join(unreviewed)}). A pharmacist or clinical reviewer must check each drug's "
            f"unit conversion before results are used outside the team. The drug list is a "
            f"provisional starter list; the top 20 by Medicare Part B spend will replace it.",
            S["body"]))
    st.append(Paragraph(
        "<b>How to read a markup.</b> 1.00× means the hospital's negotiated rate equals what "
        "Medicare pays for the same drug and amount. 2.00× means twice that. Only negotiated "
        "dollar rates whose units could be converted with confidence are counted.", S["body"]))

    # ---- 1. ranking
    st += [Paragraph("1. Drugs ranked by median markup", S["h1"])]
    rank = sorted(g["codes"], key=lambda c: -(g["dstat"].get(c, {}).get("med") or -1))
    st.append(markup_chart([(f"{c} {g['cfg'][c]['name']}", g["dstat"].get(c, {}).get("med"))
                            for c in rank]))
    rows = [["HCPCS", "Drug", "Billing unit", "ASP+6% / unit", "Hospitals", "Rates",
             "Median", "Middle 50%", "Median $ above\nMedicare / unit", "Unit review"]]
    for c in rank:
        d, a, cfgd = g["dstat"].get(c, {}), g["asp"].get(c, {}), g["cfg"][c]
        rows.append([
            c, P(f"{cfgd['name']} ({cfgd.get('brand') or ''})"),
            f"{cfgd['billing_unit']['qty']:g} {cfgd['billing_unit']['unit']}",
            P(f"{usd(a.get('payment_limit'))}<br/>{esc(a.get('quarter', ''))}", raw=True),
            n(d.get("hospitals")), n(d.get("rates")), x(d.get("med")),
            f"{x(d.get('p25'))} - {x(d.get('p75'))}" if d.get("p25") is not None else "-",
            usd(d.get("excess")),
            cfgd.get("reviewed_by") or "pending",
        ])
    st.append(table(rows, [w * inch for w in (0.5, 1.35, 0.6, 0.75, 0.55, 0.45, 0.5, 0.95, 0.85, 0.6)],
                    num_cols=(4, 5, 6, 8)))
    st.append(Paragraph(
        "Ranking by dollars at stake needs utilization (how often each drug is given at each "
        "hospital). The CMS Part B spending file is not loaded yet, so this report ranks by "
        "markup only and shows the median dollars above Medicare per billing unit.", S["small"]))

    # ---- 2. per drug
    for c in rank:
        cfgd, pd = g["cfg"][c], g["per_drug"][c]
        st.append(PageBreak())
        st.append(Paragraph(f"2. {c} {cfgd['name']} ({cfgd.get('brand') or ''})", S["h1"]))
        a = g["asp"].get(c, {})
        st.append(Paragraph(
            f"Billing unit {cfgd['billing_unit']['qty']:g} {cfgd['billing_unit']['unit']}. "
            f"Latest Medicare payment limit {usd(a.get('payment_limit'))} per unit "
            f"({a.get('quarter', '-')}). Unit review: <b>{cfgd.get('reviewed_by') or 'pending'}</b>.",
            S["body"]))
        st.append(Paragraph("Hospitals, ranked by median markup", S["h2"]))
        if pd["hospitals"]:
            st.append(markup_chart([(h["label"], h["med"]) for h in pd["hospitals"][:15]]))
            rows = [["Hospital", "System", "Rates", "Median $ / unit", "ASP+6%", "Median",
                     "Range"]]
            for h in pd["hospitals"]:
                rows.append([P(h["label"]), P(h["system"]), n(h["rates"]), usd(h["ppu"]),
                             usd(h["asp"]), x(h["med"]), f"{x(h['lo'])} - {x(h['hi'])}"])
            st.append(table(rows, [w * inch for w in (2.6, 1.05, 0.45, 0.85, 0.65, 0.55, 1.0)],
                            num_cols=(2, 3, 4, 5)))
        else:
            st.append(Paragraph("No compared negotiated rates for this drug.", S["body"]))
        st.append(Paragraph("Payer groups", S["h2"]))
        if pd["payers"]:
            rows = [["Payer group", "Hospitals", "Rates", "Median", "Range"]]
            for p in pd["payers"]:
                rows.append([p["payer_group"], n(p["hospitals"]), n(p["rates"]), x(p["med"]),
                             f"{x(p['lo'])} - {x(p['hi'])}"])
            st.append(KeepTogether(table(rows, [w * inch for w in (2.2, 0.8, 0.7, 0.8, 1.4)],
                                         num_cols=(1, 2, 3))))

    # ---- 3. coverage
    st.append(PageBreak())
    st.append(Paragraph("3. What was and was not compared", S["h1"]))
    st.append(Paragraph(
        "Every hospital row for these drugs gets one status. Only \"Compared\" negotiated "
        "dollar rates enter the figures above. All other rows are kept and shown in the web app "
        "and the CSV appendix with the reason.", S["body"]))
    rows = [["Status", "Rows"]] + [[STATUS_TEXT.get(s["status"], s["status"]), n(s["n"])]
                                   for s in g["statuses"]]
    st.append(table(rows, [3.2 * inch, 1 * inch], num_cols=(1,)))
    acc = g["pipeline_cfg"].get("accept_per_billing_unit_reading") or []
    if acc:
        st.append(Spacer(1, 6))
        st.append(Paragraph(
            "Reviewer decisions in force: for " + ", ".join(acc) + ", rows whose posted price "
            "fits Medicare only when read per billing unit are read that way (see decisions log).",
            S["small"]))

    # ---- 4. method
    st.append(Paragraph("4. Method", S["h1"]))
    for para in [
        "<b>Hospital prices.</b> Each hospital publishes a machine-readable file of standard "
        "charges under federal price transparency rules. Rows for the drugs in scope are kept, "
        "matched by HCPCS code or by an NDC that the CMS NDC-HCPCS crosswalk maps to the code.",
        "<b>Benchmark.</b> The CMS Medicare Part B payment limit for the same HCPCS code, for the "
        "quarter that contains the hospital file's last-updated date. The limit is already 106% "
        "of the Average Sales Price; no further 6% is added.",
        "<b>Units.</b> The quantity the hospital priced is taken, in order, from: the file's drug "
        "unit fields; the row's NDC through the CMS crosswalk (billing units per package) or the "
        "FDA NDC Directory (strength x package size); the strength in the hospital's own "
        "description; a reviewer decision recorded for that hospital system. If none applies, the "
        "row is not priced.",
        "<b>Markup.</b> Hospital rate / billing units = price per billing unit. Price per billing "
        "unit / Medicare payment limit = markup multiple.",
        "<b>Checks.</b> Markups below 0.5× or above 20× are held for a manual check. "
        "Rows are excluded when the same dollar amount is posted for three or more different drugs "
        "under one payer and plan, when the line is drug waste (DISCARD or JW), or when it is a "
        "clinical-trial study drug. Exact repeat rows are counted once.",
    ]:
        st.append(Paragraph(para, S["body"]))

    st.append(Paragraph("5. Limits", S["h1"]))
    for para in [
        "<b>Unit risk.</b> A wrong unit changes a result by 10× or more. Each drug needs a "
        "pharmacist or clinical reviewer to check the conversion before use.",
        "<b>340B.</b> Some hospitals buy drugs at 340B discounts. That lowers the hospital's cost, "
        "not what the health plan pays.",
        "<b>Site of care.</b> Moving a patient to a lower-cost site needs the prescriber's "
        "agreement and an in-network site that can give the infusion.",
        "<b>Posted rates.</b> Files show contracted rates, not claims paid. Percent-of-charges and "
        "formula contracts are listed but not priced unless the file posts a dollar amount.",
        "<b>Coverage.</b> Only hospitals with a downloaded and readable price file are included. "
        "Hospitals are identified by price file; CCN and NPI linkage is not yet loaded.",
    ]:
        st.append(Paragraph(para, S["body"]))

    # ---- 6. sources
    st.append(PageBreak())
    st.append(Paragraph("6. Sources", S["h1"]))
    st.append(Paragraph("CMS ASP Pricing Files (cms.gov/medicare/payment/part-b-drugs/"
                        "asp-pricing-files)", S["h2"]))
    rows = [["Quarter", "File", "SHA-256"]] + [
        [a["quarter"], P(a["member"]), P(a["sha"], "hash")] for a in g["asp_files"]]
    st.append(table(rows, [0.6 * inch, 3.0 * inch, 3.7 * inch]))
    st.append(Paragraph("Hospital price files (each hospital's cms-hpt.txt index)", S["h2"]))
    rows = [["System", "Hospital / file", "File date", "SHA-256"]] + [
        [P(h["system"]), P(f"{esc(h['label'])}<br/>{esc(h['file'].rsplit('/', 1)[-1])}", raw=True),
         str(h["updated"] or "-"), P(h["sha"], "hash")] for h in g["hosp_files"]]
    st.append(table(rows, [0.95 * inch, 2.75 * inch, 0.65 * inch, 2.95 * inch]))
    st.append(Spacer(1, 6))
    st.append(Paragraph(
        "Also used: CMS NDC-HCPCS crosswalk (same page as ASP), FDA NDC Directory (fda.gov), "
        "NADAC (data.medicaid.gov, reference only). Full row-level data with source file and "
        "hash per row: CSV appendix from the web app (All rates, Export CSV).", S["small"]))

    doc.build(st, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()
