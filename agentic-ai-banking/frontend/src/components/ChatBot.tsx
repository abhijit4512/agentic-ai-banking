import { useEffect, useRef, useState } from "react";
import { Blocks } from "./ui";
import Icon from "./Icon";

type Msg = { role: "user" | "bot"; text: string; at: Date; blocks?: any[]; sources?: string[]; escalate?: boolean };
const clock = (d: Date) => d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

export default function ChatBot({ name = "FinPilot Assistant", greeting, hints, ask }: {
  name?: string; greeting: string; hints: string[]; ask: (m: string) => Promise<any>;
}) {
  const welcome = (): Msg => ({ role: "bot", text: greeting, at: new Date() });
  const [msgs, setMsgs] = useState<Msg[]>([welcome()]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [msgs, busy]);

  const send = async (t: string) => {
    const q = t.trim();
    if (!q || busy) return;
    setMsgs(m => [...m, { role: "user", text: q, at: new Date() }]);
    setText(""); setBusy(true);
    try {
      const r = await ask(q);
      setMsgs(m => [...m, { role: "bot", text: r.answer, at: new Date(), blocks: r.blocks, sources: r.sources, escalate: r.escalate }]);
    } catch (e: any) {
      setMsgs(m => [...m, { role: "bot", text: "Sorry, something went wrong: " + e.message, at: new Date() }]);
    }
    setBusy(false);
  };

  return <div className="bot">
    <div className="bot-head">
      <span className="bot-av"><Icon name="bot" size={22} /><i className="bot-dot" /></span>
      <div><b>{name}</b><small>Online · read-only access to your account</small></div>
      <button className="bot-new" onClick={() => setMsgs([welcome()])}>New chat</button>
    </div>
    <div className="bot-body" role="log" aria-live="polite">
      <div className="bot-day">Today</div>
      {msgs.map((m, i) => <div key={i} className={"bot-row " + m.role}>
        {m.role === "bot" && <span className="bot-av sm"><Icon name="bot" size={16} /></span>}
        <div className="bot-col">
          <div className={"bot-bubble " + m.role}>{m.text}<Blocks blocks={m.blocks} /></div>
          {m.role === "bot" && (m.sources || []).length > 0 && <div className="bot-tools">{m.sources!.map(s => <span key={s} className="bot-tool"><Icon name="wrench" size={11} /> {s}</span>)}</div>}
          {m.escalate && <div className="bot-handoff">This may need a human agent. No live agent is connected in this demo.</div>}
          <small className="bot-time">{clock(m.at)}</small>
        </div>
      </div>)}
      {msgs.length === 1 && <div className="bot-quick"><small>Suggested questions</small>{hints.map(h => <button key={h} className="bot-chip" onClick={() => send(h)}>{h}</button>)}</div>}
      {busy && <div className="bot-row bot"><span className="bot-av sm"><Icon name="bot" size={16} /></span><div className="bot-bubble bot typing"><i /><i /><i /></div></div>}
      <div ref={end} />
    </div>
    <div className="bot-foot">
      <div className="bot-input">
        <input value={text} placeholder="Type your message…" aria-label="Message" onChange={e => setText(e.target.value)} onKeyDown={e => e.key === "Enter" && send(text)} />
        <button onClick={() => send(text)} disabled={busy || !text.trim()} aria-label="Send message"><Icon name="send" size={16} /></button>
      </div>
      <small>Never share your PIN, password, CVV or OTP in this chat.</small>
    </div>
  </div>;
}
