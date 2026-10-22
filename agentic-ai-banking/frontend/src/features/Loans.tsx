import { useState } from "react"; import { api, useApi } from "../api"; import { Badge, DataTable, Load, Page } from "../components/ui"; import { usePrompt } from "../components/Dialog";
export default function Loans({ me }: any) {
  const r = useApi("/loans/applications"), [sel, setSel] = useState<any>(null), [a, setA] = useState<any>(null), [err, setErr] = useState(""), staff = me.role !== "customer", [ask, dialog] = usePrompt();
  const [f, setF] = useState({ applicant: me.name, loan_type: "personal", amount: 15000, term_months: 48, rate: 11.5, income: 4200, debt: 900, customer_id: 1 });
  const run = async (fn: () => Promise<any>) => { try { setErr(""); await fn(); r.reload(); } catch (e: any) { setErr(e.message); } };
  const open = async (x: any) => { setSel(await api(`/loans/applications/${x.id}`)); setA(x.assessment); };
  const num = (k: string) => (e: any) => setF({ ...f, [k]: +e.target.value });
  return <Page title="Loan Underwriting" sub="Deterministic Decimal maths. The system recommends; only a human underwriter decides.">{err && <div className="err">{err}</div>}{dialog}
    <div className="card"><h2>New application</h2><div className="row"><input value={f.applicant} onChange={e => setF({ ...f, applicant: e.target.value })} /><select value={f.loan_type} onChange={e => setF({ ...f, loan_type: e.target.value })}><option>personal</option><option>auto</option><option>home</option></select>
      <input type="number" title="Amount" value={f.amount} onChange={num("amount")} /><input type="number" title="Term (months)" value={f.term_months} onChange={num("term_months")} /><input type="number" title="Monthly income" value={f.income} onChange={num("income")} /><input type="number" title="Monthly debt" value={f.debt} onChange={num("debt")} />
      {staff && <input type="number" title="Customer id" value={f.customer_id} onChange={num("customer_id")} />}<button onClick={() => run(() => api("/loans/applications", { body: f }))}>Submit</button></div><small>Fields: amount · term (months) · monthly income · monthly debt{staff ? " · customer id" : ""}</small></div>
    <div className="card" style={{ marginTop: 16 }}><Load s={r} />{r.data && <DataTable rows={r.data} onRow={open} cols={[{ k: "id", label: "#" }, { k: "applicant", label: "Applicant" }, { k: "loan_type", label: "Type" }, { k: "amount", label: "Amount", render: (x: any) => x.amount.toLocaleString() }, { k: "term_months", label: "Term" }, { k: "status", label: "Status", render: (x: any) => <Badge v={x.status} /> }]} />}</div>
    {sel && <div className="card" style={{ marginTop: 16 }}><h2>Application #{sel.id} — {sel.applicant}</h2><div className="row">
      {["income_proof", "bank_statement", "identity"].map(d => <button key={d} className="sec" onClick={() => run(async () => { await api(`/loans/applications/${sel.id}/documents`, { body: { doc_type: d } }); setSel(await api(`/loans/applications/${sel.id}`)); })}>+ {d}</button>)}
      {staff && <button onClick={() => run(async () => { setA(await api(`/loans/applications/${sel.id}/assess`, { body: {} })); })}>Run assessment</button>}</div>
      <small>Documents on file: {(sel.docs || []).map((d: any) => d.doc_type).join(", ") || "none"}</small>
      {a && <div><h2 style={{ marginTop: 12 }}>{a.recommendation}</h2><div>Instalment {a.monthly_instalment.toLocaleString()} · DTI {a.dti} · LTI {a.lti}</div>
        <table><thead><tr><th>Policy check</th><th>Value</th><th>Limit</th><th>Result</th></tr></thead><tbody>{a.checks.map((c: any) => <tr key={c.name}><td>{c.name}</td><td>{c.value}</td><td>{c.limit}</td><td><Badge v={c.status} /></td></tr>)}</tbody></table>
        <small>{a.credit_bureau}. {a.disclaimer}</small></div>}
      {staff && me.role !== "analyst" && a && <div className="row"><button onClick={async () => { const note = await ask("Approve application", "Written explanation"); note && run(() => api(`/loans/applications/${sel.id}/decision`, { body: { decision: "approved", note } })); }}>Approve (human)</button>
        <button className="danger" onClick={async () => { const note = await ask("Reject application", "Written explanation"); note && run(() => api(`/loans/applications/${sel.id}/decision`, { body: { decision: "rejected", note } })); }}>Reject (human)</button></div>}
      <h2 style={{ marginTop: 12 }}>Repayment schedule (first 6)</h2><DataTable size={6} rows={sel.schedule.slice(0, 24)} cols={["n", "payment", "interest", "principal", "balance"].map(k => ({ k, label: k }))} /></div>}</Page>;
}
