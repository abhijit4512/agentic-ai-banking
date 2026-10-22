import { useEffect, useState } from "react"; import { Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { api, refreshMedia, useApi } from "./api"; import Overview, { Hero } from "./features/Overview"; import { Transactions, Fraud } from "./features/Fraud";
import Compliance from "./features/Compliance"; import Loans from "./features/Loans"; import { Documents, Support } from "./features/Documents"; import { Audit, Reports, Settings } from "./features/Misc";
import Kyc from "./features/Kyc"; import Icon from "./components/Icon";
const NAV = [["/", "Overview", "overview"], ["/compliance", "KYC / AML Compliance", "shield"], ["/kyc", "KYC Documents", "id"], ["/fraud", "Fraud Detection", "alert"], ["/support", "Customer Service", "chat"], ["/loans", "Loan Underwriting", "card"], ["/documents", "AI Document Assistant", "doc"], ["/transactions", "Transactions", "swap"], ["/reports", "Reports & Analytics", "chart"], ["/audit", "Audit Logs", "list"], ["/settings", "Settings", "gear"]];
const TOP = ["/", "/kyc", "/transactions", "/reports", "/loans", "/documents"];
const SECTIONS: [string, string[]][] = [["OVERVIEW", ["/"]], ["AI MODULES", ["/compliance", "/fraud", "/support", "/loans", "/documents"]], ["CUSTOMER KYC", ["/kyc"]], ["FINANCE", ["/transactions", "/reports"]], ["SYSTEM", ["/audit", "/settings"]]];
const CUSTOMER = ["/kyc", "/support", "/transactions", "/loans", "/documents"];
// Demo credentials and DEMO pills are shown only when the frontend is built with VITE_DEMO_MODE=true.
const DEMO_UI = import.meta.env.VITE_DEMO_MODE === "true";
const DEMO_EMAIL = DEMO_UI ? "admin@finpilot.demo" : "", DEMO_PW = DEMO_UI ? "Demo@12345" : "";

function Login({ onOk }: any) {
  const [email, setE] = useState(DEMO_EMAIL), [pw, setP] = useState(DEMO_PW), [err, setErr] = useState("");
  const [creating, setCreating] = useState(false), [name, setName] = useState(""), [country, setCountry] = useState("IN");
  const go = async () => { try { const path = creating ? "/auth/register" : "/auth/login"; const body = creating ? { email, password: pw, name, country } : { email, password: pw };
    const r = await api(path, { body }); localStorage.setItem("fp_token", r.token); onOk(); } catch (e: any) { setErr(e.message); } };
  return <div className="loginbg"><div className="login"><div className="card"><div className="brand"><i>✦</i><div>FinPilot AI<small>Banking intelligence platform</small></div></div>{DEMO_UI && <span className="pill">DEMO MODE · synthetic data</span>}
    {creating && <><input value={name} onChange={e => setName(e.target.value)} aria-label="Full name" placeholder="Full name" />
      <input value={country} onChange={e => setCountry(e.target.value)} aria-label="Country ISO code" placeholder="Country ISO code (IN)" maxLength={2} /></>}
    <input type="email" value={email} onChange={e => setE(e.target.value)} aria-label="Email" placeholder="Email" autoComplete="username" />
    <input type="password" value={pw} onChange={e => setP(e.target.value)} aria-label="Password" placeholder={creating ? "Password (12+ characters)" : "Password"} autoComplete={creating ? "new-password" : "current-password"} onKeyDown={e => e.key === "Enter" && go()} />
    {err && <div className="err" role="alert">{err}</div>}<button onClick={go}>{creating ? "Create demo customer account" : "Sign in"}</button>
    {DEMO_UI && <button className="sec" onClick={() => {
      const next = !creating; setCreating(next); setErr("");
      setE(next ? "" : DEMO_EMAIL); setP(next ? "" : DEMO_PW); setName("");
    }}>{creating ? "Back to sign in" : "New customer? Create a demo account"}</button>}
    {DEMO_UI && <small>Demo accounts (password Demo@12345): admin@, analyst@, underwriter@, customer@finpilot.demo. New signups are sandbox-only; email verification is not configured.</small>}</div></div></div>;
}

/** Live platform status from the backend's /ready probe (database + storage), refreshed every 30 s. */
function useReady() {
  const [rd, setRd] = useState<any>(null);
  useEffect(() => {
    let alive = true;
    const poll = () => fetch("/api/v1/ready").then(r => r.json()).then(d => alive && setRd(d)).catch(() => alive && setRd({ status: "unreachable", checks: {} }));
    poll(); const t = setInterval(poll, 30000);
    return () => { alive = false; clearInterval(t); };
  }, []);
  return rd;
}

export default function App() {
  const [authed, setA] = useState(!!localStorage.getItem("fp_token")); const [me, setMe] = useState<any>(null); const [bell, setBell] = useState<any[]>([]);
  useEffect(() => { if (authed) Promise.all([api("/auth/me"), refreshMedia()]).then(([m]) => setMe(m)).catch(() => { localStorage.removeItem("fp_token"); setA(false); }); }, [authed]);
  useEffect(() => { if (!authed) return; const t = setInterval(refreshMedia, 10 * 60 * 1000); return () => clearInterval(t); }, [authed]);
  useEffect(() => { if (me && me.role !== "customer") api("/notifications").then(setBell).catch(() => {}); }, [me]);
  const health = useApi("/health"), loc = useLocation(), rd = useReady();
  if (!authed) return <Login onOk={() => setA(true)} />;
  if (!me) return <div className="load">Loading…</div>;
  const cust = me.role === "customer", nav = NAV.filter(n => cust ? CUSTOMER.includes(n[0]) : me.role !== "underwriter" || n[0] !== "/kyc");
  const allowed = nav.map(n => n[0]);
  const guard = (path: string, el: any) => allowed.includes(path) ? el : <Navigate to="/" replace />;  // role-based route guard (the API enforces roles too)
  const staff = !cust, initials = (me.name || "U").split(" ").map((x: string) => x[0]).slice(0, 2).join("").toUpperCase();
  const logout = () => { api("/auth/logout", { method: "POST" }).catch(() => {}); localStorage.removeItem("fp_token"); setA(false); setMe(null); };
  const ok = rd?.status === "ready";
  return <div className="app"><header className="topbar"><div className="brand"><i>✦</i><div>FinPilot AI<small>Banking intelligence platform</small></div></div>
    <nav className="tabs">{nav.filter(n => TOP.includes(n[0])).map(([p, l]) => <NavLink key={p} to={p} end={p === "/"} className={({ isActive }) => isActive ? "active" : ""}>{l}</NavLink>)}</nav>
    <div className="user">{(health.data?.demo_mode || DEMO_UI) && <span className="pill">{health.data?.demo_mode ? "DEMO · synthetic data" : "DEMO UI"}</span>}
      <button className="iconbtn" aria-label={`${bell.length} high-severity alerts`} title={bell.map(b => b.text).join("\n")}><Icon name="bell" />{bell.length > 0 && <b>{bell.length}</b>}</button>
      <div className="who">{me.name}<small>{me.role}</small></div><div className="avatar">{initials}</div><button className="sec" style={{ padding: "6px 12px" }} onClick={logout}>Sign out</button></div></header>
    {staff && loc.pathname === "/" && <Hero />}
    <div className="ticker"><span><i className={"dot" + (ok ? "" : " y")} /> Platform <b>{ok ? "ready" : rd ? rd.status : "checking…"}</b></span><span>Database <b>{rd?.checks?.database ?? "…"}</b></span><span>Storage <b>{rd?.checks?.storage ?? "…"}</b></span>{health.data?.env && <span>Environment <b>{health.data.env}</b></span>}<span><i className="dot y" /> Human review <b>required for decisions</b></span><span className="r">Today: <b>{new Date().toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}</b></span></div>
    <div className="body"><nav className="side"><div className="case"><span className="tag">AI Platform</span><b>FinPilot AI Banking Suite</b><p>KYC/AML, fraud rules, loan underwriting and a document assistant in one workspace.</p></div>
      {SECTIONS.map(([h, paths]) => { const items = nav.filter(n => paths.includes(n[0])); return items.length ? <div key={h}><h6>{h}</h6>{items.map(([p, l, ic]) => <NavLink key={p} to={p} end={p === "/"} className={({ isActive }) => isActive ? "active" : ""}><span className="ic"><Icon name={ic} /></span>{l}</NavLink>)}</div> : null; })}</nav>
    <main className="main"><div className="content"><Routes>
      <Route path="/" element={cust ? <Kyc me={me} /> : <Overview />} /><Route path="/compliance" element={guard("/compliance", <Compliance />)} /><Route path="/fraud" element={guard("/fraud", <Fraud me={me} />)} />
      <Route path="/kyc" element={guard("/kyc", <Kyc me={me} />)} />
      <Route path="/support" element={guard("/support", <Support me={me} />)} /><Route path="/loans" element={guard("/loans", <Loans me={me} />)} /><Route path="/documents" element={guard("/documents", <Documents />)} />
      <Route path="/transactions" element={guard("/transactions", <Transactions me={me} />)} /><Route path="/reports" element={guard("/reports", <Reports />)} /><Route path="/audit" element={guard("/audit", <Audit />)} /><Route path="/settings" element={guard("/settings", <Settings />)} />
      <Route path="*" element={<Navigate to="/" replace />} /></Routes></div></main></div></div>;
}
