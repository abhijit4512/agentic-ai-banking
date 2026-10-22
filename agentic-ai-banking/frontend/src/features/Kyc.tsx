import { useEffect, useMemo, useState } from "react";
import { api, tok, useApi } from "../api";
import { Badge, Load, Page } from "../components/ui";

const TYPES = [
  ["aadhaar", "Aadhaar card"], ["pan", "PAN card"], ["passport", "Passport"],
  ["driving_licence", "Driving licence"], ["voter_id", "Voter ID"],
  ["bank_statement", "Bank statement"], ["utility_bill", "Utility bill"], ["other", "Other identity/address document"],
];
const REQUIRED_FIELDS: Record<string, string[]> = {
  aadhaar: ["name", "date_of_birth", "gender", "identity_number", "address"],
  pan: ["name", "father_name", "date_of_birth", "identity_number"],
  passport: ["name", "identity_number", "nationality", "date_of_birth", "expiry_date"],
  driving_licence: ["name", "identity_number", "date_of_birth", "issue_date", "expiry_date", "address"],
  voter_id: ["name", "identity_number", "address"],
  bank_statement: ["name", "bank_name", "account_number", "statement_period"],
  utility_bill: ["name", "address", "issuer", "bill_date"],
  other: ["name"],
};
const STATUS = ["Uploaded", "Processing", "Pending Review", "Verified", "Rejected", "Resubmission Required", "Verification Failed"];
const nice = (value: string) => value.replace(/_/g, " ");

async function protectedPreview(id: number, page: number) {
  const response = await fetch(`/api/v1/kyc/documents/${id}/preview?page=${page}`, { headers: { Authorization: `Bearer ${tok()}` } });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : response.statusText);
  }
  return URL.createObjectURL(await response.blob());
}

function Preview({ doc, close }: { doc: any; close: () => void }) {
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  const [page, setPage] = useState(1);
  useEffect(() => {
    let active = true;
    let objectUrl = "";
    setUrl(""); setError("");
    protectedPreview(doc.id, page).then(value => { objectUrl = value; if (active) setUrl(value); else URL.revokeObjectURL(value); })
      .catch(e => setError(e.message));
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [doc.id, page]);
  return <div className="kyc-modal" role="dialog" aria-modal="true" aria-label="Private document preview" onClick={close}>
    <div className="kyc-preview" onClick={e => e.stopPropagation()}>
      <div className="toolbar"><b>{doc.name}</b><span className="grow">{doc.mime_type === "application/pdf" && `Page ${page} / ${doc.pages || 1}`}</span>
        {doc.mime_type === "application/pdf" && <><button className="sec" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button><button className="sec" disabled={page >= (doc.pages || 1)} onClick={() => setPage(page + 1)}>Next</button></>}
        <button className="sec" onClick={close}>Close</button></div>
      {error ? <div className="err">{error}</div> : !url ? <div className="load">Loading protected preview…</div> :
        <img src={url} alt={`Protected preview of ${doc.name}, page ${page}`} />}
    </div>
  </div>;
}

function DocumentList({ documents, onPreview, onReplace, onRetry, onSelectDoc }: any) {
  if (!documents?.length) return <div className="empty">No KYC documents submitted yet.</div>;
  return <div className="kyc-doclist">{documents.map((doc: any) => <div className="kyc-doc" key={doc.id}>
    <div className="kyc-docmain"><b>{doc.document_label}</b><span>{doc.name} · {(doc.size / 1024 / 1024).toFixed(2)} MB · {doc.mime_type}</span>
      <small>Submitted {new Date(doc.created_at).toLocaleString()}</small></div>
    <Badge v={doc.status} />
    <div className="row">
      <button className="sec" onClick={() => onPreview(doc)}>Preview securely</button>
      {onSelectDoc && <button className="sec" onClick={() => onSelectDoc(doc.id)}>Review fields</button>}
      {onReplace && (doc.status === "Rejected" || doc.status === "Resubmission Required" || doc.status === "Verification Failed") &&
        <button className="sec" onClick={() => onReplace(doc)}>Replace</button>}
      {onRetry && (doc.status === "Pending Review" || doc.status === "Verification Failed") &&
        <button className="sec" onClick={() => onRetry(doc)}>Retry OCR</button>}
    </div>
    {doc.customer_message && <p className="kyc-message">{doc.customer_message}</p>}
    {doc.validation?.processing_errors?.map((failure: string) => <small className="kyc-warning" key={failure}>{failure}</small>)}
    {doc.validation?.missing_fields?.length > 0 && <small>Fields not found: {doc.validation.missing_fields.map(nice).join(", ")}</small>}
    {doc.validation?.warnings?.map((warning: string) => <small className="kyc-warning" key={warning}>{warning}</small>)}
    {doc.fields && <div className="kyc-fields">{Object.entries(doc.fields).map(([key, value]: [string, any]) =>
      <div key={key}><small>{nice(key)}</small><b>{value.value || "Not detected"}</b></div>)}</div>}
  </div>)}</div>;
}

function CustomerKyc({ me }: any) {
  const s = useApi("/kyc/me");
  const [type, setType] = useState("aadhaar");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<any>(null);
  const [replaceId, setReplaceId] = useState<number | null>(null);
  const [dragging, setDragging] = useState(false);
  const [profile, setProfile] = useState<any>(null);
  const [profileMessage, setProfileMessage] = useState("");
  useEffect(() => { if (s.data && !profile) setProfile({ ...s.data.profile }); }, [s.data, profile]);

  const upload = async (file?: File) => {
    if (!file) return;
    setMessage("Uploading and processing…"); setError("");
    const form = new FormData();
    form.append("file", file);
    form.append("document_type", type);
    if (replaceId) form.append("supersedes_id", String(replaceId));
    try {
      const result = await api("/kyc/documents", { body: form });
      setMessage(`${result.name} uploaded. Status: ${result.status}.`);
      setReplaceId(null);
      s.reload();
    } catch (e: any) { setError(e.message); }
  };
  const retry = async (doc: any) => {
    setError(""); setMessage("");
    try {
      const result = await api(`/kyc/documents/${doc.id}/retry-ocr`, { method: "POST" });
      setMessage(`OCR retry finished. Status: ${result.status}.`);
      s.reload();
    } catch (e: any) { setError(e.message); }
  };
  const saveProfile = async () => {
    try {
      const result = await api("/kyc/profile", { method: "PATCH", body: profile });
      setProfile(result); setProfileMessage("Profile saved."); s.reload();
    } catch (e: any) { setProfileMessage(`Could not save profile: ${e.message}`); }
  };
  const docs = s.data?.documents || [];
  return <Page title="My KYC" sub="Submit identity and address documents, track review progress, and respond to resubmission requests.">
    <Load s={s} />
    {s.data && <>
      <div className="grid g2">
        <section className="card"><h2>Profile</h2>
          <div className="kyc-profile">
            <label>Full name<input value={profile?.name || ""} onChange={e => setProfile({ ...profile, name: e.target.value })} /></label>
            <label>Country<input value={profile?.country || ""} onChange={e => setProfile({ ...profile, country: e.target.value })} /></label>
            <label>Occupation<input value={profile?.occupation || ""} onChange={e => setProfile({ ...profile, occupation: e.target.value })} /></label>
            <label>Source of funds<input value={profile?.source_of_funds || ""} onChange={e => setProfile({ ...profile, source_of_funds: e.target.value })} /></label>
          </div>
          <div className="row"><button onClick={saveProfile}>Save profile</button><span>{profileMessage}</span></div>
        </section>
        <section className="card"><div className="kyc-progresshead"><div><h2>KYC completion</h2><b>{s.data.progress.completion_percent}%</b></div><Badge v={s.data.profile.kyc_status} /></div>
          <div className="bar"><i style={{ width: `${s.data.progress.completion_percent}%` }} /></div>
          <ul className="kyc-requirements"><li>{s.data.progress.identity_document ? "Complete" : "Required"} · Government identity document</li>
            <li>{s.data.progress.proof_of_address ? "Complete" : "Required"} · Proof of address</li></ul>
          <p className="sub">A “Verified” status records an authorized human decision in this app; it does not confirm issuer authenticity or Aadhaar authentication. OCR and format checks are informational only.</p>
        </section>
      </div>
      <section className="card"><h2>Upload a KYC document</h2>
        <div className={"kyc-drop " + (dragging ? "dragging" : "")} onDragOver={e => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)} onDrop={e => { e.preventDefault(); setDragging(false); upload(e.dataTransfer.files[0]); }}>
          <label>Document type<select value={type} onChange={e => setType(e.target.value)}>{TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
          <label className="btn violet">Choose PDF or image<input type="file" hidden accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png" onChange={e => upload(e.target.files?.[0])} /></label>
          <span>or drag and drop a PDF, JPG, JPEG, or PNG (max configured upload size)</span>
        </div>
        {replaceId && <div className="row">Replacing document #{replaceId}<button className="sec" onClick={() => setReplaceId(null)}>Cancel</button></div>}
        {message && <div className="kyc-ok" role="status">{message}</div>}{error && <div className="err" role="alert">{error}</div>}
      </section>
      <section className="card"><h2>Submission history</h2>
        <DocumentList documents={docs} onPreview={setPreview} onRetry={retry}
          onReplace={(doc: any) => { setReplaceId(doc.id); setType(doc.document_type); }} />
      </section>
    </>}
    {preview && <Preview doc={preview} close={() => setPreview(null)} />}
  </Page>;
}

function ReviewerKyc() {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("");
  const [offset, setOffset] = useState(0);
  const s = useApi(`/kyc/applications?q=${encodeURIComponent(query)}&status=${encodeURIComponent(filter)}&offset=${offset}&limit=25`, [query, filter, offset]);
  const stats = useApi("/kyc/stats");
  const [selected, setSelected] = useState<any>(null);
  const [docId, setDocId] = useState<number | null>(null);
  const [reviewDetail, setReviewDetail] = useState<any>(null);
  const [preview, setPreview] = useState<any>(null);
  const [reason, setReason] = useState("");
  const [customerMessage, setCustomerMessage] = useState("");
  const [fields, setFields] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const applications = s.data?.applications || [];
  const selectedDoc = useMemo(() => reviewDetail?.id === docId ? reviewDetail : selected?.documents?.find((d: any) => d.id === docId), [selected, docId, reviewDetail]);
  useEffect(() => {
    if (!docId) { setReviewDetail(null); return; }
    setReviewDetail(null);
    api(`/kyc/documents/${docId}/review`).then(setReviewDetail).catch(e => setError(e.message));
  }, [docId]);
  const reload = () => {
    s.reload(); stats.reload();
    if (selected) api(`/kyc/applications/${selected.customer_id}`).then(setSelected).catch(e => setError(e.message));
    if (docId) api(`/kyc/documents/${docId}/review`).then(setReviewDetail).catch(e => setError(e.message));
  };
  const choose = (application: any) => {
    setSelected(application);
    setDocId(application.documents[0]?.id || null);
    setFields({});
    setMessage("");
  };
  const decide = async (status: string) => {
    if (!selectedDoc || reason.trim().length < 5) { setError("Enter a review reason of at least five characters."); return; }
    try {
      setError(""); setMessage("");
      await api(`/kyc/documents/${selectedDoc.id}/decision`, { body: { status, reason, customer_message: customerMessage } });
      setMessage(`Document decision recorded: ${status}.`);
      setReason(""); setCustomerMessage(""); reload();
    } catch (e: any) { setError(e.message); }
  };
  const escalate = async () => {
    if (!selectedDoc || reason.trim().length < 5) { setError("Enter an escalation reason of at least five characters."); return; }
    try {
      await api(`/kyc/documents/${selectedDoc.id}/escalate`, { body: { reason } });
      setMessage("Document escalated for further human review.");
      setReason(""); reload();
    } catch (e: any) { setError(e.message); }
  };
  const correct = async () => {
    const corrections = Object.fromEntries(Object.entries(fields).filter(([, value]) => String(value).trim()));
    if (!selectedDoc || !Object.keys(corrections).length || reason.trim().length < 5) { setError("Enter at least one corrected field and a reason of at least five characters."); return; }
    try {
      await api(`/kyc/documents/${selectedDoc.id}/corrections`, { body: { fields: corrections, reason } });
      setMessage("Corrections saved to the audit trail. The document remains pending review.");
      setFields({}); reload();
    } catch (e: any) { setError(e.message); }
  };
  const saveField = (key: string, value: string) => setFields(prev => ({ ...prev, [key]: value }));
    const initials = (n: string) => (n || "?").split(" ").map(w => w[0]).slice(0, 2).join("").toUpperCase();
  const CHIPS = ["", "Pending Review", "Verified", "Rejected", "Resubmission Required"];
  return <Page title="KYC Review Queue" sub="Restricted reviewer workspace. OCR and format checks are not issuer or identity verification.">
    {stats.data && <div className="kq-stats">
      {[["Documents", stats.data.total_documents, ""], ["Pending review", stats.data.by_status["Pending Review"] || 0, "warn"],
        ["Extraction failures", stats.data.ocr_or_processing_failures, "bad"], ["Human review rate", stats.data.human_review_rate_percent + "%", ""]].map(([l, v, c]: any) =>
        <div key={l} className={"kq-stat " + c}><b>{v}</b><span>{l}</span></div>)}
    </div>}
    <div className="kq">
      <aside className="kq-panel kq-list">
        <input aria-label="Search applicants" placeholder="Search customer…" value={query} onChange={e => { setQuery(e.target.value); setOffset(0); }} />
        <div className="kq-chips">{CHIPS.map(c => <button key={c} className={"kq-chip" + (filter === c ? " on" : "")} onClick={() => { setFilter(c); setOffset(0); }}>{c || "All"}</button>)}</div>
        <Load s={s} />
        <div className="kq-items">{applications.map((app: any) => <button key={app.customer_id} className={"kq-item" + (selected?.customer_id === app.customer_id ? " active" : "")} onClick={() => choose(app)}>
          <span className="kq-av">{initials(app.customer_name)}</span>
          <span className="kq-who"><b>{app.customer_name}</b><small>{app.documents.length} document(s)</small></span>
          <Badge v={app.kyc_status} />
        </button>)}</div>
        {!s.loading && !applications.length && <div className="empty">No matching KYC submissions.</div>}
        <div className="kq-pager"><button className="sec" disabled={offset <= 0} onClick={() => setOffset(Math.max(0, offset - 25))}>Previous</button>
          <small>{applications.length ? offset + 1 : 0}–{offset + applications.length} of {s.data?.total || 0}</small>
          <button className="sec" disabled={offset + 25 >= (s.data?.total || 0)} onClick={() => setOffset(offset + 25)}>Next</button></div>
      </aside>

      <main className="kq-work">
        {!selected && <div className="kq-panel kq-empty"><h2>Select an application</h2><p className="sub">Choose an applicant from the queue to review their documents.</p></div>}
        {selected && <>
          <div className="kq-panel kq-head">
            <span className="kq-av lg">{initials(selected.customer_name)}</span>
            <div><h2>{selected.customer_name}</h2><small>{selected.documents.length} document(s) submitted</small></div>
            <Badge v={selected.kyc_status} />
          </div>
          {selected.mismatches?.map((m: any) => <div className="kyc-warning" key={m.field}>Cross-document mismatch: {nice(m.field)} differs in documents {m.document_ids.join(", ")}. Confirm with the customer; this is not proof of fraud.</div>)}
          <div className="kq-tabs">{selected.documents.map((d: any) => <button key={d.id} className={"kq-tab" + (docId === d.id ? " on" : "")} onClick={() => { setDocId(d.id); setFields({}); setMessage(""); setError(""); }}>
            {d.document_label || d.document_type} <Badge v={d.status} /></button>)}</div>
          {selectedDoc && <div className="kq-cols">
            <section className="kq-panel">
              <div className="kq-sechead"><h3>{selectedDoc.document_label} · #{selectedDoc.id}</h3><button className="sec" onClick={() => setPreview(selectedDoc)}>Open protected original</button></div>
              <div className="kyc-fields">{Array.from(new Set([...Object.keys(selectedDoc.fields || {}), ...(REQUIRED_FIELDS[selectedDoc.document_type] || [])])).map(key => {
                const item = selectedDoc.fields?.[key];
                return <label key={key}>{nice(key)}<input value={fields[key] ?? item?.value ?? ""} onChange={e => saveField(key, e.target.value)} /></label>;
              })}</div>
              <button className="sec" onClick={correct}>Save corrections</button>
              {selectedDoc.extracted_text && <details><summary>Original extracted text (restricted)</summary><pre>{selectedDoc.extracted_text}</pre></details>}
              {selectedDoc.review_history?.length > 0 && <details><summary>Review audit history</summary><pre>{JSON.stringify(selectedDoc.review_history, null, 2)}</pre></details>}
            </section>
            <aside className="kq-panel kq-decision">
              <h3>Decision</h3>
              <label className="kyc-full">Reviewer reason (required, 5+ characters)<textarea value={reason} onChange={e => setReason(e.target.value)} rows={3} /></label>
              <label className="kyc-full">Customer-facing explanation<textarea value={customerMessage} onChange={e => setCustomerMessage(e.target.value)} rows={2} placeholder="Do not include internal-only compliance notes." /></label>
              {message && <div className="kyc-ok">{message}</div>}{error && <div className="err">{error}</div>}
              <div className="kq-actions">
                <button onClick={() => decide("Verified")}>Mark human-reviewed</button>
                <button className="danger" onClick={() => decide("Rejected")}>Reject</button>
                <button className="sec" onClick={() => decide("Resubmission Required")}>Request resubmission</button>
                <button className="sec" onClick={escalate}>Escalate</button>
              </div>
              <small>“Verified” records a human review decision in this demo. It does not indicate issuer verification, Aadhaar authentication, or a regulatory determination.</small>
            </aside>
          </div>}
        </>}
      </main>
    </div>
    {preview && <Preview doc={preview} close={() => setPreview(null)} />}
  </Page>;
}

export default function Kyc({ me }: any) {
  return me.role === "customer" ? <CustomerKyc me={me} /> : <ReviewerKyc />;
}
