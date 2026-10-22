import { Link } from "react-router-dom";
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, PieChart, Pie, Cell, Legend, BarChart, Bar } from "recharts";
import { useApi } from "../api"; import { Load, Page, Badge } from "../components/ui";
export const COLORS = ["#2f63f0", "#7c4dff", "#10a37f", "#f59e0b", "#ef4444"];
export function Hero() {
  const s = useApi("/dashboard/summary"), d = s.data, n = (v: any) => (v ?? "—").toLocaleString?.() ?? v;
  const rate = d && d.total_transactions ? (100 * (1 - d.flagged / d.total_transactions)).toFixed(1) + "%" : "—";
  return <div className="kpis">{[["▤", "Monitored transactions", n(d?.total_transactions), "live", ""], ["✔", "Clean rate", rate, "unflagged", ""], ["⚑", "Flagged for review", n(d?.flagged), "needs review", "warn"], ["🛡", "Open compliance cases", n(d?.open_cases), "KYC / AML", "warn"], ["💳", "Pending loans", n(d?.pending_loans), "in queue", ""]].map(([i, l, v, t, c]: any) => <div key={l}><label>{i} {l}</label><b>{v}</b><em className={c}>{t}</em></div>)}</div>;
}
export default function Overview() {
  const s = useApi("/dashboard/summary"), d = s.data;
  return <Page title="Overview" sub="Live metrics from the backend API (synthetic demo data)"><Load s={s} />{d && <>
    <div className="grid g4">{[["Monitored transactions", d.total_transactions, "▤", ""], ["Flagged for review", d.flagged, "⚑", "o"], ["Open compliance cases", d.open_cases, "🛡", "v"], ["Pending loan applications", d.pending_loans, "💳", "g"]].map(([l, v, ic, c]: any) => <div className="card kpi" key={l}><div className={"ico " + c}>{ic}</div><div><b>{v}</b><span>{l}</span></div></div>)}</div>
    <div className="row" style={{ marginBottom: 18 }}>{[["/fraud", "Review alerts"], ["/compliance", "Screen a customer"], ["/loans", "Loan queue"], ["/documents", "Ask a document"]].map(([p, l]) => <Link key={p} to={p} className="btn">{l}</Link>)}</div>
    <div className="grid g2"><div className="card"><h2>Transaction trend (30 days)</h2><ResponsiveContainer width="100%" height={240}><LineChart data={d.trend}><CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e6ebf4" /><XAxis dataKey="date" /><YAxis /><Tooltip /><Legend /><Line dataKey="count" name="Transactions" stroke="#2f63f0" strokeWidth={2.5} dot={false} /><Line dataKey="flagged" name="Flagged" stroke="#ef4444" strokeWidth={2.5} dot={false} /></LineChart></ResponsiveContainer></div>
      <div className="card"><h2>Risk score distribution</h2><ResponsiveContainer width="100%" height={240}><BarChart data={d.risk_distribution}><CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e6ebf4" /><XAxis dataKey="name" /><YAxis /><Tooltip /><Bar dataKey="value" name="Transactions" fill="#2f63f0" radius={[8, 8, 0, 0]} /></BarChart></ResponsiveContainer></div>
      <div className="card"><h2>Fraud alerts by severity</h2>{Object.entries(d.alerts_by_severity).map(([k, v]: any) => <div className="row" key={k}><Badge v={k} /> <b>{v}</b></div>)}</div>
      <div className="card"><h2>KYC verification status</h2><ResponsiveContainer width="100%" height={200}><PieChart><Pie data={d.kyc} dataKey="value" nameKey="name" innerRadius={55} outerRadius={80} paddingAngle={3} stroke="none">{d.kyc.map((_: any, i: number) => <Cell key={i} fill={COLORS[i % 5]} />)}</Pie><Tooltip /><Legend /></PieChart></ResponsiveContainer></div></div>
    <div className="card" style={{ marginTop: 16 }}><h2>Recent activity</h2>{d.recent_activity.map((a: any) => <div key={a.id}><small>{a.ts.slice(0, 19).replace("T", " ")}</small> · {a.actor} · <b>{a.action}</b> {a.detail}</div>)}</div></>}</Page>;
}
