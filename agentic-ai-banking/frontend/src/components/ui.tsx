import { useMemo, useState, useRef, useEffect } from "react";
import { imgUrl } from "../api";
export const Badge = ({ v }: any) => <span className={"badge b-" + String(v).toLowerCase().replace(/[^a-z]/g, "")}>{String(v).replace(/_/g, " ")}</span>;
export const Load = ({ s }: any) => s.loading && !s.data ? <div className="load">Loading…</div> : s.err ? <div className="err">{s.err}</div> : null;
export const Page = ({ title, sub, children }: any) => <div><div className="pagehead"><div><h1>{title}</h1><p className="sub">{sub}</p></div></div>{children}</div>;

export function DataTable({ cols, rows, onRow, size = 8 }: any) {
  const [q, setQ] = useState(""), [sort, setSort] = useState<any>(null), [p, setP] = useState(0);
  const f = useMemo(() => { let r = rows || []; if (q) r = r.filter((x: any) => JSON.stringify(x).toLowerCase().includes(q.toLowerCase()));
    if (sort) r = [...r].sort((a: any, b: any) => (a[sort.k] > b[sort.k] ? 1 : -1) * sort.d); return r; }, [rows, q, sort]);
  const pages = Math.max(1, Math.ceil(f.length / size)), cur = f.slice(p * size, p * size + size);
  return <div><div className="row"><input placeholder="Search…" value={q} onChange={e => { setQ(e.target.value); setP(0); }} /><span className="sub" style={{ margin: 0 }}>{f.length} rows</span></div>
    {!f.length ? <div className="empty">No records found.</div> : <div style={{ overflow: "auto" }}><table><thead><tr>{cols.map((c: any) => <th key={c.k} onClick={() => setSort({ k: c.k, d: sort?.k === c.k ? -sort.d : 1 })}>{c.label}</th>)}</tr></thead>
      <tbody>{cur.map((r: any, i: number) => <tr key={i} className={onRow ? "click" : ""} onClick={() => onRow?.(r)}>{cols.map((c: any) => <td key={c.k}>{c.render ? c.render(r) : String(r[c.k] ?? "")}</td>)}</tr>)}</tbody></table></div>}
    <div className="row"><button className="sec" disabled={p === 0} onClick={() => setP(p - 1)}>Prev</button><span>{p + 1} / {pages}</span><button className="sec" disabled={p + 1 >= pages} onClick={() => setP(p + 1)}>Next</button></div></div>;
}

export function Blocks({ blocks, onCite }: any) {
  return <>{(blocks || []).map((b: any, i: number) => b.type === "table" ? <div key={i} style={{ marginTop: 8, overflow: "auto" }}>
    <table><tbody>{b.rows.map((r: string[], ri: number) => <tr key={ri}>{r.map((c, ci) => ri === 0 ? <th key={ci}>{c}</th> : <td key={ci} className={b.uncertain?.some((u: number[]) => u[0] === ri && u[1] === ci) ? "unc" : ""}>{c || "⚠ unreadable"}</td>)}</tr>)}</tbody></table>
    <small>Source: {b.doc}, page {b.page}</small></div>
    : <div key={i} style={{ marginTop: 8 }}><img className="pg" src={imgUrl(b.url)} alt={`${b.doc} page ${b.page}`} /><br /><small>Source: {b.doc}, page {b.page}</small></div>)}</>;
}

export function ChatPanel({ ask, hints, onCite }: any) {
  const [msgs, setM] = useState<any[]>([]), [t, setT] = useState(""), [busy, setB] = useState(false), end = useRef<any>();
  useEffect(() => { end.current?.scrollIntoView(); }, [msgs]);
  const send = async (text: string) => { if (!text.trim() || busy) return; setM(m => [...m, { role: "user", answer: text }]); setT(""); setB(true);
    try { const r = await ask(text); setM(m => [...m, { role: "ai", ...r }]); } catch (e: any) { setM(m => [...m, { role: "ai", answer: "Error: " + e.message }]); } setB(false); };
  return <div className="chat chatwrap"><div className="msgs">{!msgs.length && <div><div className="empty" style={{ paddingBottom: 8 }}>Ask anything — try one of these:</div>{hints.map((h: string) => <a key={h} className="hint" href="#" onClick={e => { e.preventDefault(); send(h); }}>{h}</a>)}</div>}
    {msgs.map((m, i) => <div key={i} className={"msgrow " + m.role}><div className="av">{m.role === "user" ? "🙂" : "🤖"}</div><div className={"m " + m.role}>{m.answer}<Blocks blocks={m.blocks} />
      {(m.citations || []).map((c: any, j: number) => <button key={j} className="cite" onClick={() => onCite?.(c)}>{c.doc} · p.{c.page}</button>)}
      {(m.sources || []).map((s: string) => <span key={s} className="cite">{s}</span>)}
      {m.grounded === false && <div><small>⚠ No supporting evidence found</small></div>}</div></div>)}
    {busy && <div className="load">Thinking…</div>}<div ref={end} /></div>
    <div className="composer"><input value={t} placeholder="Enter your question here…" onChange={e => setT(e.target.value)} onKeyDown={e => e.key === "Enter" && send(t)} /><button onClick={() => send(t)} disabled={busy}>Send ➤</button></div></div>;
}
