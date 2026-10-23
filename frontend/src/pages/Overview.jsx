import { Link } from "react-router-dom";
import { fmt, useApi } from "../api.js";
import { Loading, MarkupBars, Stat, StatusPill, Table } from "../components.jsx";

export default function Overview() {
  const meta = useApi("meta");
  const drugs = useApi("drugs");
  return (
    <>
      <Loading state={meta}>
        {(m) => (
          <section>
            <div className="stats">
              <Stat label="Hospital price files" value={fmt.n(m.hospitals)}
                hint={`${m.systems} system${m.systems === 1 ? "" : "s"}`} />
              <Stat label="Compared rates" value={fmt.n(m.headline_rates)}
                hint="negotiated $, units converted" />
              <Stat label="ASP quarters" value={m.asp_quarters.length}
                hint={`${m.asp_quarters[0]} – ${m.asp_quarters.at(-1)}`} />
              <Stat label="Pipeline run" value={m.generated_at.slice(0, 10)}
                hint={m.generated_at.slice(11, 16) + " UTC"} />
            </div>
            <div className="status-row">
              {m.statuses.map((s) => (
                <span key={s.status}><StatusPill status={s.status} /> {fmt.n(s.n)}</span>
              ))}
            </div>
          </section>
        )}
      </Loading>

      <Loading state={drugs}>
        {(rows) => (
          <>
            <section>
              <h2>Median markup by drug</h2>
              <p className="lede">Median of hospital negotiated rates, per HCPCS billing unit,
                divided by the CMS ASP payment limit (ASP + 6%). 1× = what Medicare pays.</p>
              <MarkupBars rows={rows.map((r) => ({ ...r, label: `${r.hcpcs} ${r.name}` }))}
                labelKey="label" />
            </section>
            <section>
              <h2>Drugs in scope</h2>
              <div className="banner">Starter list of 5 drugs. The top 20 by Medicare Part B
                spend replaces it when the CMS Part B Spending file is loaded.</div>
              <Table rows={rows} initialSort={{ key: "median_markup", dir: "desc" }} columns={[
                { key: "hcpcs", label: "HCPCS",
                  render: (r) => <Link to={`/drugs/${r.hcpcs}`}>{r.hcpcs}</Link> },
                { key: "name", label: "Drug",
                  render: (r) => <>{r.name}<div className="muted">{r.brand}</div></> },
                { key: "billing_unit", label: "Billing unit" },
                { key: "asp_payment_limit", label: "ASP+6% / unit", num: true,
                  render: (r) => <>{fmt.usd(r.asp_payment_limit)}
                    <div className="muted">{r.asp_quarter}</div></> },
                { key: "hospitals_priced", label: "Hospitals", num: true },
                { key: "rates", label: "Rates", num: true },
                { key: "median_markup", label: "Median", num: true,
                  render: (r) => <b>{fmt.x(r.median_markup)}</b> },
                { key: "max_markup", label: "Range", num: true,
                  render: (r) => r.min_markup == null ? "—"
                    : `${fmt.x(r.min_markup)} – ${fmt.x(r.max_markup)}` },
                { key: "excluded_rows", label: "Not compared", num: true,
                  render: (r) => fmt.n(r.excluded_rows + r.review_rows) },
                { key: "reviewed_by", label: "Unit review",
                  render: (r) => r.reviewed_by || <span className="pill s-review_range">pending</span> },
              ]} />
            </section>
          </>
        )}
      </Loading>
    </>
  );
}
