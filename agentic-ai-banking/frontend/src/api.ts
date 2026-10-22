import { useEffect, useState } from "react";
export const tok = () => localStorage.getItem("fp_token") || "";
export async function api(path: string, o: any = {}) {
  const fd = o.body instanceof FormData;
  const r = await fetch("/api/v1" + path, { method: o.method || (o.body ? "POST" : "GET"), headers: { ...(fd ? {} : { "Content-Type": "application/json" }), Authorization: "Bearer " + tok() }, body: fd ? o.body : o.body ? JSON.stringify(o.body) : undefined });
  if (r.status === 401 && !path.startsWith("/auth/login")) { localStorage.removeItem("fp_token"); location.reload(); }
  if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(typeof e.detail === "string" ? e.detail : r.statusText); }
  return r.json();
}
// <img> tags cannot send headers, so page images use a short-lived, image-only "media" token (never the session token).
let media = "";
export async function refreshMedia() {
  try { media = (await api("/auth/media-token", { method: "POST" })).token; } catch { media = ""; }
}
export const imgUrl = (u: string) => `/api/v1${u}?token=${media}`;
export function useApi(path: string, deps: any[] = []) {
  const [data, setData] = useState<any>(null), [err, setErr] = useState(""), [loading, setL] = useState(true);
  const load = () => { setL(true); api(path).then(d => { setData(d); setErr(""); }).catch(e => setErr(e.message)).finally(() => setL(false)); };
  useEffect(load, [path, ...deps]);
  return { data, err, loading, reload: load };
}
