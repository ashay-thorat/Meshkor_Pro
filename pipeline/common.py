"""Shared helpers: paths, config, hashing, code and unit normalization."""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

PROJECT = Path(__file__).resolve().parent.parent

HCPCS_RE = re.compile(r"^[A-Z0-9]\d{3}[A-Z0-9]$")
MONTH_TO_Q = {"january": 1, "april": 2, "july": 3, "october": 4,
              "jan": 1, "apr": 2, "jul": 3, "oct": 4}
_MONTHS = r"(january|april|july|october|jan|apr|jul|oct)"


def load_yaml(name: str) -> dict:
    with (PROJECT / "config" / name).open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def paths() -> dict[str, Path]:
    """Data folders. IA_DATA_ROOT overrides the base folder (used by tests)."""
    cfg = load_yaml("pipeline.yaml")["paths"]
    base = Path(os.environ.get("IA_DATA_ROOT", PROJECT))
    return {k: base / v for k, v in cfg.items()}


def drugs_in_scope() -> list[dict]:
    return load_yaml("drugs_in_scope.yaml")["drugs"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def rel(path: Path) -> str:
    """Path relative to the project, with forward slashes (stable across OS)."""
    try:
        return path.resolve().relative_to(PROJECT).as_posix()
    except ValueError:
        return path.as_posix()


# ---------- quarters ----------

def quarter_from_filename(name: str) -> str | None:
    """'october_2026_..._payment_limit...' -> '2026Q4'."""
    low = name.lower()
    # month then year: october_2026, oct-2026, oct2026
    m = re.search(_MONTHS + r"[_\- ]?(20\d\d)", low)
    if m:
        return f"{m.group(2)}Q{MONTH_TO_Q[m.group(1)]}"
    # year then month: 2024-january, 2024_oct
    m = re.search(r"(20\d\d)[_\- ]?" + _MONTHS + r"(?![a-z])", low)
    if m:
        return f"{m.group(1)}Q{MONTH_TO_Q[m.group(2)]}"
    return None


def quarter_bounds(q: str) -> tuple[date, date]:
    year, n = int(q[:4]), int(q[-1])
    start = date(year, 3 * (n - 1) + 1, 1)
    end = date(year + 1, 1, 1) if n == 4 else date(year, 3 * n + 1, 1)
    from datetime import timedelta
    return start, end - timedelta(days=1)


def quarter_of(d: date) -> str:
    return f"{d.year}Q{(d.month - 1) // 3 + 1}"


# ---------- codes ----------

def norm_hcpcs(code: object) -> str | None:
    if code is None:
        return None
    c = str(code).strip().upper()
    return c if HCPCS_RE.match(c) else None


def norm_ndc(raw: object) -> str | None:
    """Return an 11-digit NDC (5-4-2) or None when the form is ambiguous.

    Dashed 10-digit forms are padded by segment (4-4-2, 5-3-2, 5-4-1).
    An undashed 10-digit NDC cannot be padded safely, so it returns None.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    s = s.replace(" ", "")
    if "-" in s:
        parts = s.split("-")
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            return None
        a, b, c = parts
        if (len(a), len(b), len(c)) == (5, 4, 2):
            return a + b + c
        if (len(a), len(b), len(c)) == (4, 4, 2):
            return "0" + a + b + c
        if (len(a), len(b), len(c)) == (5, 3, 2):
            return a + "0" + b + c
        if (len(a), len(b), len(c)) == (5, 4, 1):
            return a + b + "0" + c
        return None
    digits = re.sub(r"\D", "", s)
    return digits if len(digits) == 11 else None


# ---------- units ----------

# CMS hospital template drug_type_of_measurement values, mapped to a base unit.
#   GR = gram, ME = milligram, ML = millilitre, UN = unit, F2 = international unit, EA = each
_MASS_TO_MG = {"ME": 1.0, "MG": 1.0, "GR": 1000.0, "GM": 1000.0, "G": 1000.0, "MCG": 0.001, "UG": 0.001}
_UNIT_WORDS = {"UN", "UNIT", "UNITS", "F2", "IU", "INTERNATIONAL UNITS"}


@dataclass(frozen=True)
class Dose:
    qty: float
    unit: str  # canonical: MG, UNIT, ML, EA, or the raw upper-case text


def parse_hcpcs_dosage(text: object) -> Dose | None:
    """'10 MG' -> Dose(10, 'MG'); '1 MG' ; '100 UNITS' -> Dose(100, 'UNIT')."""
    if text is None:
        return None
    s = str(text).strip().upper()
    m = re.match(r"^([\d.,]+)\s*([A-Z ]+?)\.?$", s)
    if not m:
        return None
    qty = float(m.group(1).replace(",", ""))
    unit = m.group(2).strip()
    if unit in _MASS_TO_MG:
        return Dose(qty * _MASS_TO_MG[unit], "MG")
    if unit in _UNIT_WORDS:
        return Dose(qty, "UNIT")
    return Dose(qty, unit)


def hospital_dose(qty: object, type_code: object) -> Dose | None:
    """Hospital drug_unit_of_measurement + drug_type_of_measurement -> Dose."""
    if qty in (None, "") or type_code in (None, ""):
        return None
    try:
        q = float(str(qty).replace(",", ""))
    except ValueError:
        return None
    if q <= 0:
        return None
    t = str(type_code).strip().upper()
    if t in _MASS_TO_MG:
        return Dose(q * _MASS_TO_MG[t], "MG")
    if t in _UNIT_WORDS:
        return Dose(q, "UNIT")
    if t == "ML":
        return Dose(q, "ML")
    if t == "EA":
        return Dose(q, "EA")
    return Dose(q, t)


def billing_units(hosp: Dose | None, billing: Dose) -> tuple[float | None, str]:
    """How many HCPCS billing units the hospital's priced quantity holds.

    Returns (units, reason). units is None when the conversion is not safe.
    """
    if hosp is None:
        return None, "no drug unit on hospital row"
    if hosp.unit == billing.unit and billing.qty > 0:
        return hosp.qty / billing.qty, f"{hosp.qty:g} {hosp.unit} / {billing.qty:g} {billing.unit}"
    if hosp.unit in {"ML", "EA"}:
        return None, f"hospital priced per {hosp.unit}; needs product concentration"
    return None, f"unit mismatch: hospital {hosp.unit} vs billing {billing.unit}"


# ---------- strength read from the hospital's own description ----------

_NUM = r"(\d+(?:\.\d+)?)"
_CONC = re.compile(_NUM + r"\s*MG\s*/\s*" + r"(\d+(?:\.\d+)?)?\s*ML\b", re.I)   # 100 MG/4 ML, 25 MG/ML
_MG = re.compile(_NUM + r"\s*MG\b", re.I)


def strength_from_description(desc: object) -> dict:
    """Read drug strength from text such as 'KEYTRUDA 25 MG/ML' or 'REMICADE 100 MG'.

    Returns {'mg_per_ml': float|None, 'mg_each': float|None, 'text': matched text}.
    The first concentration found is used. When the text holds two different
    plain MG strengths, mg_each stays None (ambiguous).
    """
    out = {"mg_per_ml": None, "mg_each": None, "text": None}
    if not desc:
        return out
    s = str(desc)
    m = _CONC.search(s)
    if m:
        mg, ml = float(m.group(1)), float(m.group(2) or 1)
        if ml > 0:
            out.update(mg_per_ml=mg / ml, text=m.group(0))
        return out
    mgs = {float(x) for x in _MG.findall(s)}
    if len(mgs) == 1:
        v = mgs.pop()
        out.update(mg_each=v, text=f"{v:g} MG")
    return out


def units_from_description(desc: object, drug_unit: object, drug_type: object,
                           billing: Dose) -> tuple[float | None, str | None, str]:
    """Billing units for rows priced per ML, per EA, or with no unit, using the description.

    Returns (units, method, note). Only MG billing units are handled.
    """
    if billing.unit != "MG":
        return None, None, "billing unit is not MG"
    st = strength_from_description(desc)
    t = (str(drug_type).strip().upper() if drug_type else "")
    qty = to_float(drug_unit)
    if t == "ML" and qty and st["mg_per_ml"]:
        mg = qty * st["mg_per_ml"]
        return (mg / billing.qty, "description_concentration",
                f"{qty:g} ML x {st['mg_per_ml']:g} mg/ML ('{st['text']}') = {mg:g} mg")
    if t == "EA" and qty and st["mg_each"]:
        mg = qty * st["mg_each"]
        return (mg / billing.qty, "description_strength",
                f"{qty:g} EA x {st['mg_each']:g} mg ('{st['text']}') = {mg:g} mg")
    if not t and st["mg_each"] is not None and st["mg_each"] == billing.qty:
        return (1.0, "description_matches_hcpcs_unit",
                f"no unit posted; description says '{st['text']}' = 1 billing unit")
    return None, None, "strength not found in description"


# ---------- payers ----------

_PAYER_GROUPS = [
    ("Anthem", r"anthem|elevance|blue ?cross|bcbs|wellpoint"),
    ("UnitedHealthcare", r"united|uhc|optum|umr"),
    ("Aetna", r"aetna"),
    ("Cigna", r"cigna|evernorth"),
    ("Medical Mutual", r"medical mutual|mmo"),
    ("Humana", r"humana"),
    ("CareSource", r"caresource"),
    ("Molina", r"molina"),
    ("Medicare Advantage", r"medicare"),
    ("Medicaid MCO", r"medicaid|buckeye|amerihealth|paramount"),
]


def payer_group(name: object) -> str:
    if not name:
        return "Not stated"
    low = str(name).lower()
    for group, pat in _PAYER_GROUPS:
        if re.search(pat, low):
            return group
    return "Other"


def to_float(x: object) -> float | None:
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip().replace("$", "").replace(",", "")
    if s in ("", "N/A", "NA", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None
