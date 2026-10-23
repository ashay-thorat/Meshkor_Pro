import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip,
  XAxis, YAxis } from "recharts";
import { STATUS_TEXT } from "./api.js";

export function Loading({ state, children }) {
  if (state.loading && !state.data) return <div className="note">Loading…</div>;
  if (state.error) return (
    <div className="note error">
      <b>Could not load data.</b> {state.error.message}
      <div>Start the API (<code>python manage.py runserver</code>) and run the pipeline
        (<code>python -m pipeline.run_all</code>).</div>
    </div>
  );
  return children(state.data);
}

export function Stat({ label, value, hint }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  );
}

export function StatusPill({ status }) {
  return <span className={`pill s-${status}`}>{STATUS_TEXT[status] || status}</span>;
}

export function Provisional({ reviewed }) {
  if (reviewed) return null;
  return (
    <div className="banner">
      <b>Not yet reviewed.</b> Unit conversion for this drug has no pharmacist sign-off.
      Treat markups as provisional until <code>reviewed_by</code> is set in
      <code> config/drugs_in_scope.yaml</code>.
    </div>
  );
}

/** Sortable table. columns: [{key, label, render?, num?}] */
export function Table({ columns, rows, initialSort, empty = "No rows." }) {
  const [sort, setSort] = useState(initialSort || { key: null, dir: "desc" });
  const sorted = useMemo(() => {
    if (!sort.key) return rows;
    const s = [...rows].sort((a, b) => {
      const x = a[sort.key], y = b[sort.key];
      if (x == null) return 1;
      if (y == null) return -1;
      return (x > y ? 1 : x < y ? -1 : 0) * (sort.dir === "asc" ? 1 : -1);
    });
    return s;
  }, [rows, sort]);
  if (!rows.length) return <div className="note">{empty}</div>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} className={c.num ? "num" : ""}
                onClick={() => setSort({ key: c.key,
                  dir: sort.key === c.key && sort.dir === "desc" ? "asc" : "desc" })}>
                {c.label}{sort.key === c.key ? (sort.dir === "desc" ? " ↓" : " ↑") : ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r, i) => (
            <tr key={i}>
              {columns.map((c) => (
                <td key={c.key} className={c.num ? "num" : ""}>
                  {c.render ? c.render(r) : r[c.key] ?? "—"}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Horizontal bars of markup multiple with a 1× (= Medicare) reference line. */
export function MarkupBars({ rows, labelKey, valueKey = "median_markup", height }) {
  const data = rows.filter((r) => r[valueKey] != null)
    .map((r) => ({ name: r[labelKey], v: r[valueKey] }));
  if (!data.length) return <div className="note">No compared rates to chart.</div>;
  const h = height || Math.max(170, data.length * 34 + 60);
  const narrow = typeof window !== "undefined" && window.innerWidth < 640;
  const yw = narrow ? 120 : 240;
  const maxChars = narrow ? 16 : 36;
  return (
    <div className="chart">
      <ResponsiveContainer width="100%" height={h}>
        <BarChart data={data} layout="vertical" margin={{ left: 4, right: 24, top: 22, bottom: 8 }}>
          <CartesianGrid horizontal={false} stroke="var(--grid)" />
          <XAxis type="number" tickFormatter={(v) => `${+v.toFixed(1)}×`} stroke="var(--muted)"
            fontSize={12} allowDecimals domain={[0, (max) => Math.max(2, Math.ceil(max))]} />
          <YAxis type="category" dataKey="name" width={yw} stroke="var(--muted)" fontSize={12}
            tickFormatter={(s) => (s.length > maxChars ? s.slice(0, maxChars - 1) + "…" : s)} />
          <Tooltip formatter={(v) => [`${v.toFixed(2)}× ASP+6%`, "Median markup"]}
            contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)" }} />
          <ReferenceLine x={1} stroke="var(--ink)" strokeDasharray="4 3"
            label={{ value: "Medicare", position: "top", fill: "var(--muted)", fontSize: 11 }} />
          <Bar dataKey="v" radius={[0, 3, 3, 0]}>
            {data.map((d, i) => (
              <Cell key={i} fill={d.v >= 3 ? "var(--hot)" : d.v >= 1.5 ? "var(--warm)" : "var(--cool)"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
