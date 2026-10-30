import { useEffect, useState } from "react";
import { getJSON, pdfUrl, postJSON } from "./api.js";
import { useAuth } from "./auth.jsx";

/** Report status for the current pipeline run, PDF download, and reviewer sign-off. */
export default function SignoffPanel() {
  const { user } = useAuth();
  const [s, set] = useState(null);
  const [err, setErr] = useState(null);
  const [note, setNote] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => { getJSON("signoff").then(set).catch((e) => setErr(e.message)); }, []);

  const sign = async () => {
    setBusy(true);
    setErr(null);
    try { set(await postJSON("signoff", { note })); setConfirm(false); }
    catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  };

  if (!s) return err ? <div className="note error">{err}</div> : null;
  return (
    <section className={`signoff ${s.signed ? "is-signed" : "is-draft"}`}>
      <div className="signoff-row">
        <div>
          <div className="signoff-state">
            {s.signed ? `Signed off by ${s.signed_by} on ${s.signed_at.slice(0, 10)}`
              : "Draft – this pipeline run is not signed off"}
          </div>
          <div className="muted">
            Run {s.generated_at.replace("T", " ").slice(0, 16)} UTC · file sha256{" "}
            <span className="mono">{s.comparison_sha256.slice(0, 16)}…</span>
            {s.signed && s.note ? ` · “${s.note}”` : ""}
          </div>
        </div>
        <div className="signoff-actions">
          <a className="button" href={pdfUrl()}>Download PDF report</a>
          {user.can_review && !s.signed && !confirm &&
            <button onClick={() => setConfirm(true)}>Sign off this run…</button>}
        </div>
      </div>
      {confirm && (
        <div className="signoff-confirm">
          <p>Sign off confirms you have reviewed this run. The sign-off is tied to this exact
            data file; the next pipeline run becomes a draft again.</p>
          <input placeholder="Note (optional): what you checked" value={note}
            onChange={(e) => setNote(e.target.value)} />
          <button className="button" disabled={busy} onClick={sign}>Confirm sign-off</button>
          <button onClick={() => setConfirm(false)}>Cancel</button>
        </div>
      )}
      {err && <div className="note error">{err}</div>}
    </section>
  );
}
