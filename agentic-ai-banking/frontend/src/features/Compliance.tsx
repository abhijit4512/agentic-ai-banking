import { useState } from "react"; import { api, useApi } from "../api"; import { Badge, DataTable, Load, Page } from "../components/ui"; import { usePrompt } from "../components/Dialog";
export default function Compliance() {
  const [ask, dialog] = usePrompt();
  const cases = useApi("/compliance/cases"), [f, setF] = useState({ name: "", type: "individual", country: "", occupation: "", source_of_funds: "" }), [res, setRes] = useState<any>(null), [sar, setSar] = useState(""), [err, setErr] = useState("");
  const submit = async () => { try { setErr(""); setRes(await api("/compliance/customers", { body: f })); cases.reload(); } catch (e: any) { setErr(e.message); } };
  const review = async (c: any, outcome: string) => { const note = await ask("Case review", "Reviewer note (required)"); if (!note) return; try { await api(`/compliance/cases/${c.id}/review`, { body: { outcome, note } }); cases.reload(); } catch (e: any) { setErr(e.message); } };
  return <Page title="KYC / AML Compliance" sub="Onboarding, screening against a SYNTHETIC list, human case review and draft-only SAR generation.">
    {err && <div className="err">{err}</div>}{dialog}<div className="card"><h2>Onboard & screen a customer</h2><div className="row">
      <input placeholder="Full name (try: Daniel Okafor)" value={f.name} onChange={e => setF({ ...f, name: e.target.value })} /><select value={f.type} onChange={e => setF({ ...f, type: e.target.value })}><option>individual</option><option>business</option></select>
      <input placeholder="Country (ISO)" size={8} value={f.country} onChange={e => setF({ ...f, country: e.target.value })} /><input placeholder="Occupation" value={f.occupation} onChange={e => setF({ ...f, occupation: e.target.value })} /><input placeholder="Source of funds" value={f.source_of_funds} onChange={e => setF({ ...f, source_of_funds: e.target.value })} />
      <button disabled={!f.name || !f.country} onClick={submit}>Create & screen</button></div>
      {res && <div><b>{res.matches.length ? `${res.matches.length} potential match(es) — case #${res.case_id} opened for human review.` : "No potential matches."}</b> {res.note}{res.matches.map((m: any, i: number) => <div key={i}>{m.matched_name} [{m.list}] confidence {m.confidence} on {m.matched_on.join(", ")}</div>)}</div>}</div>
    <div className="card" style={{ marginTop: 16 }}><h2>Compliance cases</h2><Load s={cases} />{cases.data && <DataTable rows={cases.data} cols={[{ k: "id", label: "Case" }, { k: "customer", label: "Customer" }, { k: "kind", label: "Kind" }, { k: "status", label: "Status", render: (x: any) => <Badge v={x.status} /> },
      { k: "matches", label: "Top match", render: (x: any) => x.matches[0] ? `${x.matches[0].matched_name} (${x.matches[0].confidence})` : "-" },
      { k: "a", label: "Actions", render: (x: any) => <div className="row" style={{ margin: 0 }}><button className="sec" onClick={() => review(x, "false_positive")}>False positive</button><button className="sec" onClick={() => review(x, "escalate")}>Escalate</button>
        <button className="sec" onClick={async () => setSar((await api(`/compliance/cases/${x.id}/sar-draft`, { body: {} })).text)}>SAR draft</button></div> }]} />}</div>
    {sar && <div className="card"><h2>SAR draft (not filed)</h2><pre>{sar}</pre></div>}</Page>;
}
