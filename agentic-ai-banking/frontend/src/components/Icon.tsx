/** Small dependency-free SVG icon set (stroke icons), used instead of emoji. */
const P: Record<string, string> = {
  overview: "M3 3h8v8H3zM13 3h8v5h-8zM13 10h8v11h-8zM3 13h8v8H3z",
  shield: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z",
  id: "M3 5h18v14H3zM7 10a2 2 0 104 0 2 2 0 10-4 0M5 16c0-2 6-2 6 0M14 9h5M14 13h5",
  alert: "M12 3l10 18H2zM12 10v5M12 18v.5",
  chat: "M4 4h16v12H9l-5 4z",
  card: "M2 5h20v14H2zM2 10h20M6 15h4",
  doc: "M6 2h9l5 5v15H6zM14 2v6h6M9 13h7M9 17h7",
  swap: "M4 8h14l-4-4M20 16H6l4 4",
  chart: "M4 20V4M4 20h16M8 16v-5M12 16V8M16 16v-8",
  list: "M4 6h16M4 12h16M4 18h16",
  gear: "M12 9a3 3 0 100 6 3 3 0 000-6zM12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2",
  send: "M3 11l18-8-8 18-2-8z",
  bot: "M5 8h14v10H5zM12 4v4M9 13h.01M15 13h.01M9 16h6M3 12v3M21 12v3",
  wrench: "M14 6a4 4 0 005 5l-9 9a2 2 0 01-3-3l9-9a4 4 0 00-2-2z",
  bell: "M6 16V11a6 6 0 1112 0v5l2 2H4zM10 21h4",
};
export default function Icon({ name, size = 16 }: { name: string; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={P[name] || P.list} /></svg>;
}
