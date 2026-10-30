import { STATUS_TEXT } from "../api.js";
import { StatusPill } from "../components.jsx";

export default function Method() {
  return (
    <section className="prose">
      <h1>Method and limits</h1>

      <h2>What is compared</h2>
      <p>Each hospital publishes a machine-readable price file under federal price transparency
        rules. We keep the rows for the drugs in scope, identified by HCPCS code or by an NDC that
        the CMS NDC-HCPCS crosswalk maps to that code.</p>
      <p>The benchmark is the CMS Medicare Part B payment limit for the same HCPCS code. That
        limit is already 106% of the Average Sales Price (ASP + 6%), so no further 6% is added.
        The quarter used is the one that contains the hospital file's "last updated" date. If
        that quarter is not loaded, the latest quarter is used.</p>

      <h2>The calculation</h2>
      <ol>
        <li>Read the quantity the hospital priced (for example 100 mg). Sources, in order: the
          file's drug unit fields; the row's NDC through the CMS NDC-HCPCS crosswalk (billing
          units per package) or the FDA NDC Directory (strength × package size); the strength in
          the hospital's own description. When the NDC and the description disagree, the row is
          held for review.</li>
        <li>Divide by the HCPCS billing unit (for example 10 mg for infliximab) to get billing
          units. 100 mg ÷ 10 mg = 10 units.</li>
        <li>Price per billing unit = hospital rate ÷ billing units.</li>
        <li>Markup = price per billing unit ÷ ASP payment limit. 1.00× equals Medicare.</li>
      </ol>
      <p>Headline figures use negotiated dollar rates with status "Compared" only.</p>

      <h2>Row statuses</h2>
      <ul className="plain">
        {Object.keys(STATUS_TEXT).map((s) => <li key={s}><StatusPill status={s} /></li>)}
      </ul>
      <p>A row whose unit cannot be converted is shown but never priced. Markups below 0.5× or
        above 20× are held for a manual check, because they are usually unit errors.</p>
      <p>Three rules remove rows that are not drug prices: a payer and plan that post the same
        dollar amount for three or more different drugs in one file (a flat case rate or
        placeholder), drug waste lines (DISCARD in the text or a JW modifier), and clinical-trial
        study drug lines (STUDY DRUG in the text).</p>
      <p>When a row has an NDC and its description only repeats the HCPCS code text (for example
        "INJECTION, DENOSUMAB, 1 MG"), the NDC gives the product size.</p>
      <p>Many hospitals post the package size (for example a 100 mg vial) while the price is
        per one HCPCS billing unit. When a row only fits the benchmark under that second reading,
        it is marked "Unit ambiguous" and both markups are shown. It is not counted until a
        reviewer has checked sample rows for that hospital system and accepted the per-unit
        reading in <code>config/pipeline.yaml</code>.</p>

      <h2>Limits</h2>
      <ul>
        <li><b>Unit risk.</b> A wrong unit changes a result by 10× or more. Each drug needs a
          pharmacist or clinical reviewer to check the conversion before results are published.</li>
        <li><b>340B.</b> Some hospitals buy drugs at 340B discounts. That lowers the hospital's
          cost, not what the health plan pays.</li>
        <li><b>Site of care.</b> Moving a patient to a lower-cost site needs the prescriber's
          agreement and an in-network site that can give the infusion.</li>
        <li><b>Posted rates.</b> Files show contracted rates, not claims paid. Percent-of-charges
          and formula contracts are listed but not priced unless the file posts a dollar
          estimate.</li>
        <li><b>Coverage.</b> Only hospitals with a downloadable file are included. See the Data
          quality page for each file.</li>
      </ul>

      <h2>Sources</h2>
      <ul>
        <li>CMS ASP Pricing Files and NDC-HCPCS crosswalk:
          cms.gov/medicare/payment/part-b-drugs/asp-pricing-files</li>
        <li>Hospital price files: each hospital's cms-hpt.txt index.</li>
        <li>CMS hospital price transparency template: github.com/CMSgov/hospital-price-transparency</li>
      </ul>
      <p>Every row keeps its source file name and SHA-256 hash, so any number can be traced to
        the exact file it came from.</p>
    </section>
  );
}
