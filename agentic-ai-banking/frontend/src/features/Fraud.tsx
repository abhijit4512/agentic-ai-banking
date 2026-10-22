import { useState } from "react"; import { api, useApi } from "../api"; import { Badge, DataTable, Load, Page } from "../components/ui"; import { usePrompt } from "../components/Dialog";
export function Transactions({ me }: any) {
  const [st, setSt] = useState(""), [sel, setSel] = useState<any>(null), [msg, setMsg] = useState(""), r = useApi("/transactions" + (st ? `?status=${st}` : ""));
  const sim = async () => { try { const x = await api("/transactions/simulate?n=10", { method: "POST" }); setMsg(`Simulated ${x.created.length} events through the rules engine`); r.reload(); } catch (e: any) { setMsg(e.message); } };
  return <Page title="Transactions" sub="Searchable, sortable, paginated. Click a row for the explanation."><div className="row"><select value={st} onChange={e => setSt(e.target.value)}><option value="">All statuses</option><option>flagged</option><option>completed</option><option>failed</option></select>
    {me.role !== "customer" && <button onClick={sim}>Simulate 10 live events</button>}<span>{msg}</span></div><Load s={r} />
    {r.data && <DataTable rows={r.data} onRow={setSel} cols={[{ k: "id", label: "ID" }, { k: "ts", label: "Time", render: (x: any) => x.ts.slice(0, 16).replace("T", " ") }, { k: "account", label: "Account" }, { k: "merchant", label: "Merchant" }, { k: "amount", label: "Amount", render: (x: any) => `${x.amount.toLocaleString()} ${x.currency}` }, { k: "country", label: "Country" }, { k: "score", label: "Risk" }, { k: "status", label: "Status", render: (x: any) => <Badge v={x.status} /> }]} />}
    {sel && <div className="card"><h2>{sel.id} — risk {sel.score} <Badge v={sel.severity} /></h2>{(sel.reasons || []).length ? sel.reasons.map((x: any) => <div key={x.code}><b>{x.code}</b> (+{x.points}): {x.message}</div>) : "No rules triggered."}</div>}</Page>;
}
export function Fraud({ me }: any) {
  const r = useApi("/fraud/alerts"), [sel, setSel] = useState<any>(null), [err, setErr] = useState(""), [ask, dialog] = usePrompt();
  const act = async (path: string, body: any) => { try { setErr(""); await api(path, { body }); r.reload(); setSel(null); } catch (e: any) { setErr(e.message); } };
  return <Page title="Fraud Detection" sub="Deterministic rules with reason codes. Holds are simulated and need admin approval."><Load s={r} />{err && <div className="err">{err}</div>}{dialog}
    {r.data && <DataTable rows={r.data} onRow={setSel} cols={[{ k: "id", label: "Alert" }, { k: "txn_id", label: "Txn" }, { k: "account", label: "Account" }, { k: "amount", label: "Amount", render: (x: any) => x.amount.toLocaleString() }, { k: "score", label: "Score" }, { k: "severity", label: "Severity", render: (x: any) => <Badge v={x.severity} /> }, { k: "status", label: "Status", render: (x: any) => <Badge v={x.status} /> }, { k: "action_state", label: "Hold" }]} />}
    {sel && <div className="card"><h2>Alert #{sel.id} · {sel.merchant}</h2>{sel.reasons.map((x: any) => <div key={x.code}><b>{x.code}</b>: {x.message}</div>)}
      {(sel.notes || []).map((n: any, i: number) => <div key={i}><small>{n.ts.slice(0, 16)} {n.by}</small>: {n.text}</div>)}
      <div className="row"><button onClick={async () => { const note = await ask("Resolve as false positive", "Resolution note"); note && act(`/fraud/alerts/${sel.id}/review`, { status: "resolved_false_positive", note }); }}>Resolve: false positive</button>
        <button className="danger" onClick={async () => { const note = await ask("Resolve as confirmed fraud", "Resolution note"); note && act(`/fraud/alerts/${sel.id}/review`, { status: "resolved_fraud", note }); }}>Resolve: confirmed fraud</button>
        <button className="sec" onClick={async () => { const reason = await ask("Request simulated hold", "Reason for hold"); reason && act(`/fraud/alerts/${sel.id}/action`, { action: "request_hold", reason }); }}>Request hold</button>
        {me.role === "admin" && <button className="sec" onClick={async () => { const reason = await ask("Approve hold", "Approval reason"); reason && act(`/fraud/alerts/${sel.id}/action`, { action: "approve_hold", reason }); }}>Approve hold</button>}
        <button className="sec" onClick={async () => { const reason = await ask("Release hold", "Reason for release"); reason && act(`/fraud/alerts/${sel.id}/action`, { action: "release", reason }); }}>Release</button></div></div>}</Page>;
}
