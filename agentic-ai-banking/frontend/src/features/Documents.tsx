import { useState } from "react"; import { api, imgUrl, useApi } from "../api"; import { Badge, ChatPanel, Page } from "../components/ui"; import ChatBot from "../components/ChatBot";
export function Documents() {
  const docs = useApi("/documents"), [sel, setSel] = useState<any>(null), [pg, setPg] = useState(1), [msg, setMsg] = useState(""), [full, setFull] = useState(false);
  const cur = sel || docs.data?.[0];
  const up = async (e: any) => { const f = e.target.files[0]; if (!f) return; const fd = new FormData(); fd.append("file", f); setMsg("Uploading and processing…");
    try { const d = await api("/documents/upload", { body: fd }); setMsg(d.note || "Processed"); docs.reload(); setSel(d); setPg(1); } catch (er: any) { setMsg("Error: " + er.message); } };
  const cite = (c: any) => { const d = docs.data?.find((x: any) => x.id === c.doc_id); if (d) { setSel(d); setPg(c.page); } };
  return <Page title="AI Document Assistant" sub="Upload PDFs, then ask. Answers cite document + page and show the real extracted table or original page image.">
    <div className="split"><div className="card"><div className="toolbar"><label className="btn violet" style={{ cursor: "pointer" }}>⬆ Upload<input type="file" hidden accept="application/pdf" onChange={up} /></label><span className="grow">{msg}</span></div>
      <div className="toolbar">{(docs.data || []).map((d: any) => <button key={d.id} className={cur?.id === d.id ? "" : "sec"} onClick={() => { setSel(d); setPg(1); }}>{d.name} <Badge v={d.status} /></button>)}</div>
      {cur?.note && <div className="err">{cur.note}</div>}
      {cur && cur.pages > 0 && <div className="docview"><div className="row" style={{ justifyContent: "center" }}><button className="sec" disabled={pg <= 1} onClick={() => setPg(pg - 1)}>‹</button> Page {pg} / {cur.pages} <button className="sec" disabled={pg >= cur.pages} onClick={() => setPg(pg + 1)}>›</button><button className="sec" onClick={() => setFull(true)}>Full screen</button></div>
        <img className="pg" src={imgUrl(`/documents/${cur.id}/pages/${pg}`)} alt="page" /></div>}</div>
      <div className="card"><div className="toolbar"><b>💬 Ask this document</b></div><ChatPanel onCite={cite} hints={["What is the total amount shown in the statement?", "Show me the table containing loan eligibility criteria", "Show the image on page 3 that explains the transaction process", "What does the chart indicate?"]}
        ask={(q: string) => api("/rag/query", { body: { question: q, document_ids: cur ? [cur.id] : undefined } })} /></div></div>
    {full && cur && <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.85)", overflow: "auto", padding: 20, zIndex: 9 }} onClick={() => setFull(false)}><img className="pg" style={{ maxWidth: "min(1000px,100%)", display: "block", margin: "0 auto" }} src={imgUrl(`/documents/${cur.id}/pages/${pg}`)} /></div>}</Page>;
}
export function Support({ me }: any) {
  const [last, setLast] = useState<any>(null), [cid, setCid] = useState(1);
  const acts = last ? [["Tools used", (last.sources || []).length ? last.sources.join(", ") : "No tool needed"], ["Scope", "Read-only, limited to your own account"], ["Live handoff", last.escalate ? "Escalation to a human agent suggested" : "Not needed for this answer"]] : [];
  return <Page title="Customer Service" sub="Assistant uses narrow read-only tools scoped to your own account. Never share PINs, passwords or OTPs.">
    {me.role !== "customer" && <div className="row">Acting for customer id <input type="number" min={1} aria-label="Customer id" value={cid} onChange={e => setCid(+e.target.value)} style={{ width: 90 }} /></div>}
    <div className="grid" style={{ gridTemplateColumns: "minmax(0,1fr) 320px", alignItems: "start" }}>
      <div className="card" style={{ padding: 0, overflow: "hidden" }}><ChatBot name="FinPilot Assistant"
        greeting="Hi! I'm your FinPilot assistant. I can look up your transactions, loan status, KYC requirements and fees. What can I help with?"
        hints={["What transactions occurred this month?", "Why was a transaction flagged?", "What documents are required for KYC?", "What is the status of my loan application?", "What is the wire transfer fee?"]}
        ask={async (m: string) => { const r = await api("/support/chat", { body: { message: m, ...(me.role !== "customer" ? { customer_id: cid } : {}) } }); setLast(r); return r; }} /></div>
      <div className="actions"><h3>AI Actions Triggered</h3>{acts.length ? <ul>{acts.map(([a, b]) => <li key={a}><i>✓</i><div><b>{a}</b><small>{b}</small></div></li>)}</ul> : <div className="empty">Actions appear here after your first question.</div>}</div></div></Page>;
}
