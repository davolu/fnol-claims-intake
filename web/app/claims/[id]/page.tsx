"use client";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";
import { Confidence, StatusBadge } from "@/components/ui";
import { ApiError, api, jsonInit, useApi } from "@/lib/api";
import { FIELD_LABEL, ROUTE_LABEL, confClass, displayValue, money, ms, usd, when } from "@/lib/format";

type Field = { value: unknown; confidence: number; source: string | null; method: string; notes?: string[]; grounding?: number };
type Issue = { rule: string; field: string | null; severity: "error" | "warning"; message: string };
type Reason = { code: string; field?: string; message: string };
type Ev = { id: number; ts: string; actor: string; event_type: string; step: string | null; duration_ms: number | null; details: Record<string, unknown> };
type Spec = { type: string; enum?: string[]; required: boolean; desc: string };
type Claim = {
  id: string; reference: string; status: string; decision: string | null; fields: Record<string, Field>;
  meta: { document_kind?: string; document_kind_confidence?: number }; validation: Issue[]; review_reasons: Reason[];
  llm_usage: Record<string, number | string | null>; timings_ms: Record<string, number>; error: string | null;
  external_claim_number: string | null; external_claim_id: string | null; external_system: string | null;
  reviewed_by: string | null; reject_reason: string | null; pii_masked: boolean; push_attempts: number;
  document: { id: string; filename: string; route: string | null; ocr_engine: string | null; ocr_confidence: number | null;
    page_count: number; source: string; email_subject: string | null; email_from: string | null; text: string | null; content_type: string };
  events: Ev[]; field_specs: Record<string, Spec>;
  payload_preview?: { system: string; stand_in: boolean; body?: unknown; error?: string };
};

const ORDER = ["policy_number", "line_of_business", "loss_date", "loss_time", "loss_cause", "loss_location", "description",
  "insured_name", "insured_phone", "insured_email", "reporter_name", "reporter_relationship", "other_parties",
  "vehicle_or_property", "police_report_number", "injuries", "estimated_amount", "currency", "line_items"];

function escapeRe(s: string) { return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }

export default function ClaimPage() {
  const { id } = useParams<{ id: string }>();
  const { data: c, reload, setData } = useApi<Claim>(`/claims/${id}`, 4000);
  const [edits, setEdits] = useState<Record<string, unknown>>({});
  const [focus, setFocus] = useState<string | null>(null);
  const [tab, setTab] = useState<"fields" | "trace" | "payload">("fields");
  const [view, setView] = useState<"pages" | "text">("pages");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const issuesByField = useMemo(() => {
    const m: Record<string, Issue[]> = {};
    (c?.validation ?? []).forEach((i) => { if (i.field) (m[i.field] ||= []).push(i); });
    return m;
  }, [c]);

  if (!c) return <p className="muted">Loading…</p>;
  const editable = ["needs_review", "push_failed", "failed", "approved"].includes(c.status) && !c.pii_masked;
  const hasPages = c.document.page_count > 0 && !c.document.filename.toLowerCase().endsWith(".eml");
  const dirty = Object.keys(edits).length > 0;

  async function run(fn: () => Promise<unknown>) {
    setBusy(true); setErr(null);
    try { await fn(); await reload(); }
    catch (e) {
      const d = (e as ApiError).detail as { message?: string; issues?: Issue[] } | string;
      setErr(typeof d === "string" ? d : `${d?.message ?? "Error"}${d?.issues ? ": " + d.issues.map((i) => i.message).join("; ") : ""}`);
    } finally { setBusy(false); }
  }
  const save = () => run(async () => { const r = await api<Claim>(`/claims/${id}/fields`, jsonInit("PATCH", { fields: edits })); setEdits({}); setData({ ...c, ...r }); });
  const approve = () => run(async () => { if (dirty) { await api(`/claims/${id}/fields`, jsonInit("PATCH", { fields: edits })); setEdits({}); } await api(`/claims/${id}/approve`, jsonInit("POST", { reason: "Reviewed against source" })); });
  const reject = () => { const reason = window.prompt("Reason for rejecting this claim intake?"); if (reason) run(() => api(`/claims/${id}/reject`, jsonInit("POST", { reason }))); };
  const reprocess = () => run(() => api(`/claims/${id}/reprocess`, { method: "POST" }));
  const retry = () => run(() => api(`/claims/${id}/retry-push`, { method: "POST" }));

  const quote = focus ? c.fields[focus]?.source : null;
  const text = c.document.text ?? "";
  const highlighted = quote && !c.pii_masked
    ? text.split(new RegExp(`(${escapeRe(quote)})`, "i")).map((part, i) => i % 2 ? <mark key={i}>{part}</mark> : part)
    : text;

  function input(name: string, f: Field) {
    const spec = c!.field_specs[name];
    const v = name in edits ? edits[name] : f.value;
    const set = (x: unknown) => setEdits({ ...edits, [name]: x });
    if (!editable) return <div style={{ whiteSpace: "pre-wrap" }}>{displayValue(f.value) || <span className="muted">not found</span>}</div>;
    if (spec?.type === "boolean") {
      return <select value={v === true ? "true" : v === false ? "false" : ""} onChange={(e) => set(e.target.value === "" ? null : e.target.value === "true")}>
        <option value="">unknown</option><option value="true">Yes</option><option value="false">No</option></select>;
    }
    if (spec?.enum) {
      return <select value={(v as string) ?? ""} onChange={(e) => set(e.target.value || null)}>
        <option value="">—</option>{spec.enum.map((o) => <option key={o} value={o}>{o.replace(/_/g, " ")}</option>)}</select>;
    }
    if (spec?.type === "number") return <input type="number" step="0.01" value={v === null || v === undefined ? "" : String(v)} onChange={(e) => set(e.target.value === "" ? null : Number(e.target.value))} />;
    if (spec?.type === "array") {
      return <textarea className="mono" defaultValue={v ? JSON.stringify(v, null, 1) : ""} onBlur={(e) => { try { set(e.target.value.trim() ? JSON.parse(e.target.value) : null); } catch { setErr(`${name}: not valid JSON`); } }} />;
    }
    if (name === "description") return <textarea value={(v as string) ?? ""} onChange={(e) => set(e.target.value)} />;
    return <input value={(v as string) ?? ""} onChange={(e) => set(e.target.value)} />;
  }

  return (
    <>
      <div className="spread" style={{ marginBottom: 14 }}>
        <div>
          <h1 className="mono">{c.reference} <StatusBadge status={c.status} /></h1>
          <div className="muted small">
            {c.document.route ? ROUTE_LABEL[c.document.route] : ""} · {c.document.filename} · OCR {c.document.ocr_engine ?? "—"}
            {c.document.ocr_confidence !== null ? ` (${Math.round(c.document.ocr_confidence * 100)}% word confidence)` : ""} ·
            processed in {ms(c.timings_ms?.total)} · AI cost {usd(c.llm_usage?.cost_usd as number)} ({String(c.llm_usage?.model ?? "")})
          </div>
        </div>
        <div className="row">
          {c.status === "push_failed" ? <button onClick={retry} disabled={busy}>Retry send</button> : null}
          {["needs_review", "failed", "rejected"].includes(c.status) && !c.pii_masked ? <button onClick={reprocess} disabled={busy}>Re-run AI</button> : null}
          {editable && dirty ? <button onClick={save} disabled={busy}>Save edits</button> : null}
          {editable && c.status !== "approved" ? <button className="danger" onClick={reject} disabled={busy}>Reject</button> : null}
          {editable && c.status !== "approved" ? <button className="primary" onClick={approve} disabled={busy}>Approve & send to claims system</button> : null}
        </div>
      </div>
      {err ? <div className="banner" style={{ background: "var(--red-soft)", borderColor: "#f0c4bf", color: "var(--red)" }}>{err}</div> : null}
      {c.pii_masked ? <div className="banner info">You are viewing as <b>Auditor</b>: personal data is masked and the original scan is hidden.</div> : null}
      {c.external_claim_number ? (
        <div className="banner info">
          Sent to <b>{c.external_system}</b>{c.payload_preview?.stand_in ? " (stand-in)" : ""}: claim number <b className="mono">{c.external_claim_number}</b>
          {c.external_claim_id ? <span className="mono"> · id {c.external_claim_id}</span> : null}
        </div>
      ) : null}
      {c.reject_reason ? <div className="banner">Rejected by {c.reviewed_by}: {c.reject_reason}</div> : null}
      {c.error ? <div className="banner" style={{ background: "var(--red-soft)", borderColor: "#f0c4bf", color: "var(--red)" }}>{c.error}</div> : null}

      <div className="workspace">
        <div className="panel viewer">
          <div className="spread">
            <h3>Source document</h3>
            <div className="tabs" style={{ marginBottom: 8 }}>
              {hasPages ? <button className={view === "pages" ? "on" : ""} onClick={() => setView("pages")}>Scan</button> : null}
              <button className={view === "text" || !hasPages ? "on" : ""} onClick={() => setView("text")}>Text read by OCR</button>
            </div>
          </div>
          {c.document.email_subject ? <p className="small"><b>{c.document.email_subject}</b><br /><span className="muted">{c.document.email_from}</span></p> : null}
          {hasPages && view === "pages" && !c.pii_masked
            ? Array.from({ length: c.document.page_count }, (_, i) => (
              // eslint-disable-next-line @next/next/no-img-element
              <img key={i} src={`/api/documents/${c.document.id}/pages/${i + 1}.png`} alt={`page ${i + 1}`} />))
            : <pre>{highlighted || <span className="muted">No text yet.</span>}</pre>}
          {focus && quote ? <p className="small muted">Highlighting the quote for <b>{FIELD_LABEL[focus]}</b>{hasPages && view === "pages" ? " (switch to the text view to see it)" : ""}.</p> : null}
        </div>

        <div>
          {c.review_reasons?.length ? (
            <div className="panel">
              <h3>Why this needs a person</h3>
              <ul className="reasons">{c.review_reasons.map((r, i) => <li key={i}>{r.message}</li>)}</ul>
              {c.meta?.document_kind && c.meta.document_kind !== "fnol" ? <p className="err">The agent thinks this is not a new loss report ({c.meta.document_kind}).</p> : null}
            </div>
          ) : null}
          <div className="panel">
            <div className="tabs">
              <button className={tab === "fields" ? "on" : ""} onClick={() => setTab("fields")}>Extracted fields</button>
              <button className={tab === "trace" ? "on" : ""} onClick={() => setTab("trace")}>Agent trace & audit ({c.events.length})</button>
              <button className={tab === "payload" ? "on" : ""} onClick={() => setTab("payload")}>Claims-system payload</button>
            </div>

            {tab === "fields" ? (
              <div className="fields">
                {ORDER.filter((k) => c.fields[k]).map((k) => {
                  const f = c.fields[k];
                  const iss = issuesByField[k] ?? [];
                  const req = c.field_specs[k]?.required;
                  const showConf = f.value !== null && f.value !== "" || req;
                  return (
                    <div key={k} className={`field ${showConf ? confClass(f.confidence) : ""} ${iss.some((i) => i.severity === "error") ? "issue" : ""}`}
                      onMouseEnter={() => setFocus(k)}>
                      <div className="top">
                        <span className="name">{FIELD_LABEL[k] ?? k}{req ? " *" : ""}</span>
                        <span className="row" style={{ gap: 8 }}>
                          <span className="method">{f.method === "self_check" ? "self-checked" : f.method}</span>
                          {showConf ? <Confidence value={f.confidence} /> : null}
                        </span>
                      </div>
                      {input(k, f)}
                      {k === "estimated_amount" && f.value !== null ? <div className="small muted">{money(f.value, c.fields.currency?.value as string)}</div> : null}
                      {f.source ? <div className="src" onClick={() => { setFocus(k); setView("text"); }}>“{f.source}”</div> : null}
                      {f.notes?.length ? <div className="notes">{f.notes.join(" · ")}</div> : null}
                      {iss.map((i, n) => <div key={n} className={i.severity === "error" ? "err small" : "notes"}>{i.severity === "error" ? "✕ " : "⚠ "}{i.message}</div>)}
                    </div>
                  );
                })}
                {(c.validation ?? []).filter((i) => !i.field).map((i, n) => <div key={n} className="err small">{i.message}</div>)}
              </div>
            ) : null}

            {tab === "trace" ? (
              <ul className="timeline">
                {c.events.map((e) => (
                  <li key={e.id} className={/fail|reject/.test(e.event_type) ? "bad" : e.actor.startsWith("user:") ? "human" : ""}>
                    <div className="t">{e.step ?? e.event_type}{e.step ? <span className="muted small"> · {e.event_type}</span> : null}</div>
                    <div className="small muted">{when(e.ts)} · {e.actor}{e.duration_ms !== null ? ` · ${ms(e.duration_ms)}` : ""}</div>
                    {Object.keys(e.details ?? {}).length ? (
                      <details><summary className="small">details</summary><pre>{JSON.stringify(e.details, null, 2)}</pre></details>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : null}

            {tab === "payload" ? (
              c.payload_preview ? (
                <>
                  <p className="small muted">
                    What will be sent to <b>{c.payload_preview.system}</b>{c.payload_preview.stand_in ? " (stand-in)" : ""} as the first call
                    (POST /claim/v1/claims). The reporter and other parties are then added as ClaimContacts, the reporter is set,
                    and the draft is submitted. Every call carries a GW-DBTransaction-ID so a retry can never create a second claim.
                  </p>
                  <pre className="mono" style={{ background: "#0f1b2d", color: "#d5e3f5", padding: 14, borderRadius: 8, overflow: "auto" }}>
                    {JSON.stringify(c.payload_preview.body ?? c.payload_preview.error, null, 2)}
                  </pre>
                </>
              ) : <p className="muted">No active claims-system integration, or your role cannot view the payload.</p>
            ) : null}
          </div>
          <div className="panel small muted">
            Tokens: {String(c.llm_usage?.input_tokens ?? 0)} in / {String(c.llm_usage?.output_tokens ?? 0)} out over {String(c.llm_usage?.calls ?? 0)} call(s) ·
            steps: {Object.entries(c.timings_ms ?? {}).filter(([k]) => k !== "total").map(([k, v]) => `${k} ${ms(v)}`).join(" · ")}
            {c.reviewed_by ? ` · reviewed by ${c.reviewed_by}` : ""}
          </div>
        </div>
      </div>
    </>
  );
}
