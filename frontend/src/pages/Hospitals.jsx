import { Link } from "react-router-dom";
import { fmt, useApi } from "../api.js";
import { Loading, MarkupBars, Table } from "../components.jsx";

export default function Hospitals() {
  const h = useApi("hospitals");
  return (
    <Loading state={h}>
      {(rows) => (
        <>
          <section>
            <h1>Hospitals</h1>
            <p className="lede">One row per hospital price file. Median markup across all
              compared negotiated rates for the drugs in scope.</p>
            <MarkupBars rows={rows} labelKey="hospital_label" />
          </section>
          <section>
            <Table rows={rows} initialSort={{ key: "median_markup", dir: "desc" }} columns={[
              { key: "hospital_label", label: "Hospital",
                render: (r) => <><Link to={`/hospitals/${r.hospital_key}`}>{r.hospital_label}</Link>
                  {r.locations && <div className="muted">{r.locations}</div>}</> },
              { key: "system", label: "System" },
              { key: "file_last_updated", label: "File date" },
              { key: "drugs_priced", label: "Drugs", num: true },
              { key: "rates", label: "Rates", num: true },
              { key: "median_markup", label: "Median", num: true,
                render: (r) => <b>{fmt.x(r.median_markup)}</b> },
              { key: "max_markup", label: "Max", num: true, render: (r) => fmt.x(r.max_markup) },
              { key: "excluded_rows", label: "Not compared", num: true,
                render: (r) => fmt.n(r.excluded_rows + r.review_rows) },
            ]} />
          </section>
        </>
      )}
    </Loading>
  );
}
