import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, PieChart, Pie, Cell, Legend } from "recharts";
import { useApi } from "../api"; import { DataTable, Load, Page } from "../components/ui"; import { COLORS } from "./Overview";
export function Audit() { const r = useApi("/audit-logs"); return <Page title="Audit Logs" sub="Every sensitive action is recorded."><Load s={r} /><div className="card">{r.data && <DataTable size={12} rows={r.data} cols={[{ k: "ts", label: "Time", render: (x: any) => x.ts.slice(0, 19).replace("T", " ") }, { k: "actor", label: "Actor" }, { k: "action", label: "Action" }, { k: "detail", label: "Detail" }]} />}</div></Page>; }
export function Reports() {
  const s = useApi("/dashboard/summary"), d = s.data;
  return <Page title="Reports & Analytics" sub="Aggregates computed by the backend."><Load s={s} />{d && <div className="grid g2">
    <div className="card"><h2>Transactions by type</h2><ResponsiveContainer width="100%" height={240}><PieChart><Pie data={d.by_type} dataKey="value" nameKey="name" innerRadius={55} outerRadius={85} paddingAngle={3} stroke="none">{d.by_type.map((_: any, i: number) => <Cell key={i} fill={COLORS[i % 5]} />)}</Pie><Tooltip /><Legend /></PieChart></ResponsiveContainer></div>
    <div className="card"><h2>Daily flagged transactions</h2><ResponsiveContainer width="100%" height={240}><BarChart data={d.trend}><CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e6ebf4" /><XAxis dataKey="date" /><YAxis allowDecimals={false} /><Tooltip /><Bar dataKey="flagged" fill="#7c4dff" name="Flagged" radius={[8, 8, 0, 0]} /></BarChart></ResponsiveContainer></div></div>}</Page>;
}
export function Settings() {
  const h = useApi("/health");
  return <Page title="Settings" sub="Configuration is read from backend environment variables (see .env.example)."><div className="card"><Load s={h} />{h.data && <pre>{JSON.stringify(h.data, null, 2)}</pre>}
    <p>Demo credentials, LLM provider, OCR provider and upload limits are set server-side; secrets are never sent to the browser.</p></div></Page>;
}
