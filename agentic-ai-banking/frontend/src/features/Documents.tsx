import { useEffect, useState } from "react"; import { api, imgUrl, useApi } from "../api"; import { Badge, ChatPanel, Page } from "../components/ui"; import ChatBot from "../components/ChatBot";
export function Documents() {
  const docs = useApi("/documents");
  const [sel, setSel] = useState<any>(null), [pg, setPg] = useState(1), [msg, setMsg] = useState(""), [full, setFull] = useState(false);
  const [hl, setHl] = useState<{ doc_id: number; page: number; snippet: string } | null>(null);
  const [rects, setRects] = useState<any[]>([]);
  const cur = sel || docs.data?.[0];

  useEffect(() => {
    setRects([]);
    if (!cur || !hl || hl.doc_id !== cur.id || hl.page !== pg || !hl.snippet) return;
    api(`/documents/${cur.id}/pages/${pg}/highlights?q=${encodeURIComponent(hl.snippet)}`).then(r => setRects(r.rects || [])).catch(() => setRects([]));
  }, [cur?.id, pg, hl]);

  const up = async (e: any) => {
    const f = e.target.files[0]; if (!f) return;
    const fd = new FormData(); fd.append("file", f); setMsg("Uploading and processing…");
    try { const d = await api("/documents/upload", { body: fd }); setMsg(d.note || "Processed"); docs.reload(); setSel(d); setPg(1); setHl(null); }
    catch (er: any) { setMsg("Error: " + er.message); }
  };
  const cite = (c: any) => {
    const d = docs.data?.find((x: any) => x.id === c.doc_id);
    if (d) { setSel(d); setPg(c.page); setHl({ doc_id: c.doc_id, page: c.page, snippet: c.snippet || "" }); }
  };
  const ask = async (q: string) => {
    const r = await api("/rag/query", { body: { question: q, document_ids: cur ? [cur.id] : undefined } });
    if (r.citations?.length) cite(r.citations[0]);   // jump to the best source page and highlight it
    return r;
  };
  const marks = rects.map((r, i) => <span key={i} className="da-hl" style={{ left: r.x * 100 + "%", top: r.y * 100 + "%", width: r.w * 100 + "%", height: r.h * 100 + "%" }} />);

  return <Page title="AI Document Assistant" sub="Upload a PDF and ask questions. Answers cite the page, highlight the source text, and show the real tables and page images.">
    <div className="da">
      <section className="card da-view">
        <div className="da-bar">
          <label className="btn violet" style={{ cursor: "pointer" }}>Upload PDF<input type="file" hidden accept="application/pdf" onChange={up} /></label>
          <select aria-label="Document" value={cur?.id ?? ""} onChange={e => { setSel(docs.data.find((d: any) => d.id === +e.target.value)); setPg(1); setHl(null); }}>
            {(docs.data || []).map((d: any) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
          {cur && <Badge v={cur.status} />}
          <span className="grow">{msg}</span>
        </div>
        {cur?.note && <div className="err">{cur.note}</div>}
        {!cur && <div className="empty">Upload a PDF to get started.</div>}
        {cur && cur.pages > 0 && <>
          <div className="da-nav">
            <button className="sec" disabled={pg <= 1} onClick={() => setPg(pg - 1)}>‹ Prev</button>
            <span>Page {pg} / {cur.pages}</span>
            <button className="sec" disabled={pg >= cur.pages} onClick={() => setPg(pg + 1)}>Next ›</button>
            <button className="sec" onClick={() => setFull(true)}>Full screen</button>
          </div>
          <div className="da-stage"><div className="da-page">
            <img src={imgUrl(`/documents/${cur.id}/pages/${pg}`)} alt={`${cur.name} page ${pg}`} />
            {marks}
          </div></div>
          {hl && hl.page === pg && hl.doc_id === cur.id && <div className="da-note">{rects.length ? "Highlighted: the passage used for the answer" : "Source page shown (no exact text to highlight, e.g. a scanned page)"}</div>}
        </>}
      </section>
      <section className="card da-chat">
        <ChatBot name="Document Assistant" onCite={cite} ask={ask}
          greeting="Upload a PDF, then ask me about it. I'll answer from the document, show tables and page images, and point to the page."
          hints={["What is the total amount shown in the statement?", "Show me the table containing loan eligibility criteria", "Show the image on page 3 that explains the transaction process", "What does the chart indicate?"]} />
      </section>
    </div>
    {full && cur && <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.85)", overflow: "auto", padding: 20, zIndex: 9 }} onClick={() => setFull(false)}>
      <div className="da-page" style={{ maxWidth: "min(1000px,100%)", margin: "0 auto" }}><img src={imgUrl(`/documents/${cur.id}/pages/${pg}`)} alt="page" />{marks}</div></div>}
  </Page>;
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
