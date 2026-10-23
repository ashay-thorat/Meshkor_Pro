import { Link, useParams } from "react-router-dom";
import { fmt, useApi } from "../api.js";
import { Loading, StatusPill, Table } from "../components.jsx";
import RatesTable from "./RatesTable.jsx";

export default function HospitalDetail() {
  const { key } = useParams();
  const h = useApi(`hospitals/${key}`, null, [key]);
  return (
    <Loading state={h}>
      {(d) => (
        <>
          <section>
            <div className="crumb"><Link to="/hospitals">Hospitals</Link> / {d.hospital_label}</div>
            <h1>{d.hospital_label}</h1>
            <p className="lede">{d.system} · file dated {d.file_last_updated || "not stated"}</p>
            {d.locations && <p className="muted">Locations on this file: {d.locations}</p>}
            <p className="muted mono">{d.source_file}<br />sha256 {d.source_sha256}</p>
            <div className="status-row">
              {d.statuses.map((s) => (
                <span key={s.status}><StatusPill status={s.status} /> {fmt.n(s.n)}</span>
              ))}
            </div>
          </section>
          <section>
            <h2>Drugs</h2>
            <Table rows={d.drugs} initialSort={{ key: "median_markup", dir: "desc" }}
              empty="No compared negotiated rates in this file." columns={[
                { key: "hcpcs", label: "HCPCS",
                  render: (r) => <Link to={`/drugs/${r.hcpcs}`}>{r.hcpcs}</Link> },
                { key: "drug_name", label: "Drug" },
                { key: "rates", label: "Rates", num: true },
                { key: "median_price_per_unit", label: "Median $ / unit", num: true,
                  render: (r) => fmt.usd(r.median_price_per_unit) },
                { key: "asp_payment_limit", label: "ASP+6%", num: true,
                  render: (r) => fmt.usd(r.asp_payment_limit) },
                { key: "median_markup", label: "Median", num: true,
                  render: (r) => <b>{fmt.x(r.median_markup)}</b> },
                { key: "max_markup", label: "Range", num: true,
                  render: (r) => `${fmt.x(r.min_markup)} – ${fmt.x(r.max_markup)}` },
              ]} />
          </section>
          <section>
            <h2>Every rate in this file</h2>
            <RatesTable fixed={{ hospital_key: key }} />
          </section>
        </>
      )}
    </Loading>
  );
}
