import { useEffect, useState } from "react";

/** Called when the server says the session has ended (set by AuthProvider). */
let onLoggedOut = () => {};
export function setLoggedOutHandler(fn) { onLoggedOut = fn; }

export async function getJSON(path, params) {
  const qs = params ? "?" + new URLSearchParams(clean(params)).toString() : "";
  const res = await fetch(`/api/${path}${qs}`, { credentials: "same-origin" });
  const body = await res.json().catch(() => ({}));
  if ((res.status === 401 || res.status === 403) && path !== "auth/me") onLoggedOut();
  if (!res.ok) throw new Error(body.error || body.detail || `${res.status} ${res.statusText}`);
  return body;
}

function csrfToken() {
  const m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : "";
}

export async function postJSON(path, payload = {}) {
  const res = await fetch(`/api/${path}`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
    body: JSON.stringify(payload),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || body.detail || `${res.status} ${res.statusText}`);
  return body;
}

export function csvUrl(params) {
  return `/api/rates.csv?${new URLSearchParams(clean(params)).toString()}`;
}

export function pdfUrl(params = {}) {
  const qs = new URLSearchParams(clean(params)).toString();
  return `/api/report.pdf${qs ? "?" + qs : ""}`;
}

function clean(p) {
  return Object.fromEntries(Object.entries(p).filter(([, v]) => v !== "" && v != null));
}

/** Fetch on mount and whenever `deps` change. */
export function useApi(path, params, deps = []) {
  const [state, set] = useState({ data: null, error: null, loading: true });
  useEffect(() => {
    let live = true;
    set((s) => ({ ...s, loading: true }));
    getJSON(path, params)
      .then((data) => live && set({ data, error: null, loading: false }))
      .catch((error) => live && set({ data: null, error, loading: false }));
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps]);
  return state;
}

export const fmt = {
  x: (v) => (v == null ? "—" : `${v.toFixed(2)}×`),
  usd: (v) => (v == null ? "—" : v.toLocaleString("en-US", { style: "currency", currency: "USD",
    maximumFractionDigits: v < 10 ? 3 : 2 })),
  n: (v) => (v == null ? "—" : v.toLocaleString("en-US")),
  pct: (v) => (v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(0)}%`),
};

export const STATUS_TEXT = {
  ok: "Compared",
  review_range: "Check by hand (outside 0.5×–20×)",
  unit_ambiguous: "Unit ambiguous (vial or per unit?)",
  unit_unresolved: "Unit not convertible",
  unit_conflict: "NDC and description disagree",
  not_drug_price: "Same $ for many drugs (not a drug price)",
  discarded_drug: "Discarded drug (waste line)",
  study_drug: "Clinical-trial study drug",
  billing_unit_mismatch: "ASP unit differs from config",
  no_benchmark: "No ASP benchmark",
  percent_of_charges: "% of charges only",
  algorithm_only: "Formula only",
};

export const PRICE_TYPE_TEXT = {
  negotiated_dollar: "Negotiated $",
  estimated_amount: "Estimated $",
  median_allowed: "Median allowed $",
  cash: "Cash price",
  gross_charge: "Gross charge",
  contract_terms: "Contract terms",
};
