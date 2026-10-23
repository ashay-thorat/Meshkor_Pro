import RatesTable from "./RatesTable.jsx";

export default function Rates() {
  return (
    <section>
      <h1>All rates</h1>
      <p className="lede">Every hospital rate for the drugs in scope, including rows that were
        not compared and why. Hover a row to see its source file and hash.</p>
      <RatesTable />
    </section>
  );
}
