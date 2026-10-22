import { useEffect, useRef, useState } from "react";

type Request = { title: string; label: string; confirm: string; resolve: (value: string | null) => void };

/** Accessible replacement for window.prompt(): `const [ask, dialog] = usePrompt();`
 *  render {dialog} once, then `const note = await ask("Title", "Label")` (null when cancelled). */
export function usePrompt() {
  const [req, setReq] = useState<Request | null>(null);
  const ask = (title: string, label = "Reason", confirm = "Confirm") =>
    new Promise<string | null>(resolve => setReq({ title, label, confirm, resolve }));
  const dialog = req ? <PromptDialog title={req.title} label={req.label} confirm={req.confirm}
    onClose={(value: string | null) => { req.resolve(value); setReq(null); }} /> : null;
  return [ask, dialog] as const;
}

function PromptDialog({ title, label, confirm, onClose }: any) {
  const [value, setValue] = useState("");
  const field = useRef<HTMLTextAreaElement>(null);
  useEffect(() => { field.current?.focus(); }, []);
  const valid = value.trim().length >= 5;
  return <div className="kyc-modal" role="dialog" aria-modal="true" aria-label={title} onClick={() => onClose(null)}
    onKeyDown={e => { if (e.key === "Escape") onClose(null); }}>
    <div className="dialog" onClick={e => e.stopPropagation()}>
      <h2>{title}</h2>
      <label>{label}<textarea ref={field} rows={3} value={value} onChange={e => setValue(e.target.value)} /></label>
      <small>At least 5 characters. This is recorded in the audit log.</small>
      <div className="row"><button className="sec" onClick={() => onClose(null)}>Cancel</button>
        <button disabled={!valid} onClick={() => valid && onClose(value.trim())}>{confirm}</button></div>
    </div>
  </div>;
}
