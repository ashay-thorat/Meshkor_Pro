import { useEffect, useState } from "react";

export async function getJSON(path, params) {
  const qs = params ? "?" + new URLSearchParams(clean(params)).toString() : "";
  const res = await fetch(`/api/${path}${qs}`);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || `${res.status} ${res.statusText}`);
  return body;
}

export function csvUrl(params) {
  return `/api/rates.csv?${new URLSearchParams(clean(params)).toString()}`;
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
  unit_unresolved: "Unit not convertible",
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
