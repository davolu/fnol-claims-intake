"use client";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";
import { ArrowLeft, Ban, Bot, Check, CircleAlert, CircleX, Code2, FileText, Mail, Pencil, Quote, RefreshCw, Save, ScanLine, Send, TriangleAlert, User, Workflow } from "lucide-react";
import Link from "next/link";
import { Alert, Button, Card, Confidence, Pill, Segmented, StatusBadge } from "@/components/ui";
import { cn } from "@/lib/cn";
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

  if (!c)
    return (
      <div className="space-y-4">
        <div className="skeleton h-8 w-72" />
        <div className="grid grid-cols-2 gap-5"><div className="skeleton h-[560px]" /><div className="skeleton h-[560px]" /></div>
      </div>
    );
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

  const ctl = "w-full rounded-md border border-input bg-card px-2.5 py-1.5 text-[13px] text-foreground shadow-card transition focus:border-primary/60 focus:outline-none focus:ring-3 focus:ring-primary/15";
  function input(name: string, f: Field) {
    const spec = c!.field_specs[name];
    const v = name in edits ? edits[name] : f.value;
    const set = (x: unknown) => setEdits({ ...edits, [name]: x });
    if (!editable) return <div className="whitespace-pre-wrap text-[13.5px] font-medium">{displayValue(f.value) || <span className="font-normal text-muted-foreground">not found</span>}</div>;
    if (spec?.type === "boolean") {
      return <select className={ctl} value={v === true ? "true" : v === false ? "false" : ""} onChange={(e) => set(e.target.value === "" ? null : e.target.value === "true")}>
        <option value="">unknown</option><option value="true">Yes</option><option value="false">No</option></select>;
    }
    if (spec?.enum) {
      return <select className={ctl} value={(v as string) ?? ""} onChange={(e) => set(e.target.value || null)}>
        <option value="">—</option>{spec.enum.map((o) => <option key={o} value={o}>{o.replace(/_/g, " ")}</option>)}</select>;
    }
    if (spec?.type === "number") return <input className={ctl} type="number" step="0.01" value={v === null || v === undefined ? "" : String(v)} onChange={(e) => set(e.target.value === "" ? null : Number(e.target.value))} />;
    if (spec?.type === "array") {
      return <textarea className={cn(ctl, "min-h-16 font-mono text-[12px]")} defaultValue={v ? JSON.stringify(v, null, 1) : ""} onBlur={(e) => { try { set(e.target.value.trim() ? JSON.parse(e.target.value) : null); } catch { setErr(`${name}: not valid JSON`); } }} />;
    }
    if (name === "description") return <textarea className={cn(ctl, "min-h-16")} value={(v as string) ?? ""} onChange={(e) => set(e.target.value)} />;
    return <input className={ctl} value={(v as string) ?? ""} onChange={(e) => set(e.target.value)} />;
  }

  const lowCount = ORDER.filter((k) => c.fields[k] && confClass(c.fields[k].confidence) !== "conf-high" && (c.fields[k].value !== null && c.fields[k].value !== "" || c.field_specs[k]?.required)).length;
  const dot = (e: Ev) => (/fail|reject/.test(e.event_type) ? "bad" : e.actor.startsWith("user:") ? "human" : "bot");

  return (
    <>
      <Link href={c.status === "needs_review" ? "/review" : "/claims"} className="mb-3 inline-flex items-center gap-1 text-[12.5px] font-medium text-muted-foreground hover:text-foreground hover:no-underline">
        <ArrowLeft size={13} /> {c.status === "needs_review" ? "Review queue" : "All claims"}
      </Link>
      <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="font-mono text-[20px]">{c.reference}</h1>
            <StatusBadge status={c.status} />
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[12px] text-muted-foreground">
            {c.document.route ? <Pill>{ROUTE_LABEL[c.document.route]}</Pill> : null}
            <Pill><FileText size={11} />{c.document.filename}</Pill>
            <Pill><ScanLine size={11} />OCR {c.document.ocr_engine ?? "—"}{c.document.ocr_confidence !== null ? ` · ${Math.round(c.document.ocr_confidence * 100)}%` : ""}</Pill>
            <Pill>{ms(c.timings_ms?.total)}</Pill>
            <Pill>AI {usd(c.llm_usage?.cost_usd as number)} · {String(c.llm_usage?.model ?? "")}</Pill>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {c.status === "push_failed" ? <Button onClick={retry} disabled={busy}><RefreshCw size={13} />Retry send</Button> : null}
          {["needs_review", "failed", "rejected"].includes(c.status) && !c.pii_masked ? <Button onClick={reprocess} disabled={busy}><Bot size={13} />Re-run AI</Button> : null}
          {editable && dirty ? <Button onClick={save} disabled={busy}><Save size={13} />Save edits</Button> : null}
          {editable && c.status !== "approved" ? <Button variant="destructive" onClick={reject} disabled={busy}><Ban size={13} />Reject</Button> : null}
          {editable && c.status !== "approved" ? <Button variant="default" onClick={approve} disabled={busy}><Check size={13} />Approve &amp; send to claims system</Button> : null}
        </div>
      </div>

      <div className="mb-5 space-y-2.5 empty:hidden">
        {err ? <Alert tone="danger">{err}</Alert> : null}
        {c.pii_masked ? <Alert tone="info">You are viewing as <b>Auditor</b>: personal data is masked and the original scan is hidden.</Alert> : null}
        {c.external_claim_number ? (
          <Alert tone="success" icon={Send}>
            Sent to <b>{c.external_system}</b>{c.payload_preview?.stand_in ? " (stand-in)" : ""}: claim number <b className="font-mono">{c.external_claim_number}</b>
            {c.external_claim_id ? <span className="font-mono text-[12px] opacity-80"> · id {c.external_claim_id}</span> : null}
          </Alert>
        ) : null}
        {c.reject_reason ? <Alert tone="warn">Rejected by {c.reviewed_by}: {c.reject_reason}</Alert> : null}
        {c.error ? <Alert tone="danger">{c.error}</Alert> : null}
      </div>

      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)]">
        <Card className="sticky top-4 max-h-[calc(100vh-32px)] overflow-hidden xl:flex xl:flex-col">
          <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
            <h3 className="flex items-center gap-2"><FileText size={15} className="text-muted-foreground" />Source document</h3>
            <Segmented
              value={hasPages && view === "pages" ? "pages" : "text"}
              onChange={setView}
              options={[...(hasPages ? [{ value: "pages" as const, label: "Scan" }] : []), { value: "text" as const, label: "OCR text" }]}
            />
          </div>
          <div className="overflow-auto bg-muted/40 p-4">
            {c.document.email_subject ? (
              <div className="mb-3 flex items-start gap-2.5 rounded-lg border border-border bg-card p-3">
                <Mail size={15} className="mt-0.5 text-muted-foreground" />
                <div><div className="font-medium">{c.document.email_subject}</div><div className="text-[12px] text-muted-foreground">{c.document.email_from}</div></div>
              </div>
            ) : null}
            {hasPages && view === "pages" && !c.pii_masked
              ? Array.from({ length: c.document.page_count }, (_, i) => (
                // eslint-disable-next-line @next/next/no-img-element
                <img key={i} src={`/api/documents/${c.document.id}/pages/${i + 1}.png`} alt={`page ${i + 1}`} className="mb-3 w-full rounded-lg border border-border bg-white shadow-card" />))
              : <pre className="m-0 max-h-[70vh] overflow-auto whitespace-pre-wrap rounded-lg border border-border bg-card p-3.5 text-[12px] leading-relaxed">{highlighted || <span className="text-muted-foreground">No text yet.</span>}</pre>}
            {focus && quote ? <p className="mt-2 text-[12px] text-muted-foreground">Highlighting the quote for <b className="text-foreground">{FIELD_LABEL[focus]}</b>{hasPages && view === "pages" ? " (switch to OCR text to see it)" : ""}.</p> : null}
          </div>
        </Card>

        <div className="space-y-5">
          {c.review_reasons?.length ? (
            <Card className="border-amber-500/30 bg-amber-500/[0.04] p-4">
              <h3 className="mb-2 flex items-center gap-2 text-amber-800 dark:text-amber-300"><TriangleAlert size={15} />{["needs_review", "failed", "push_failed"].includes(c.status) ? "Why this needs a person" : "Flags raised on arrival"}</h3>
              <ul className="m-0 space-y-1.5 pl-0">
                {c.review_reasons.map((r, i) => (
                  <li key={i} className="flex gap-2 text-[13px]"><span className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-amber-500" />{r.message}</li>
                ))}
              </ul>
              {c.meta?.document_kind && c.meta.document_kind !== "fnol" ? <p className="mt-2 text-rose-600">The agent thinks this is not a new loss report ({c.meta.document_kind}).</p> : null}
            </Card>
          ) : null}

          <Card className="overflow-hidden">
            <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-2.5">
              <Segmented
                value={tab}
                onChange={setTab}
                options={[
                  { value: "fields", label: <span className="inline-flex items-center gap-1.5"><Pencil size={12} />Fields</span> },
                  { value: "trace", label: <span className="inline-flex items-center gap-1.5"><Workflow size={12} />Trace &amp; audit ({c.events.length})</span> },
                  { value: "payload", label: <span className="inline-flex items-center gap-1.5"><Code2 size={12} />Payload</span> },
                ]}
              />
              {tab === "fields" ? <span className="text-[12px] text-muted-foreground">{lowCount ? <b className="text-amber-700 dark:text-amber-400">{lowCount} to check</b> : "All fields confident"}</span> : null}
            </div>

            <div className="p-4">
              {tab === "fields" ? (
                <div className="flex flex-col gap-2.5">
                  {ORDER.filter((k) => c.fields[k]).map((k) => {
                    const f = c.fields[k];
                    const iss = issuesByField[k] ?? [];
                    const req = c.field_specs[k]?.required;
                    const showConf = (f.value !== null && f.value !== "") || req;
                    const cls = showConf ? confClass(f.confidence) : "";
                    const hasErr = iss.some((i) => i.severity === "error");
                    return (
                      <div
                        key={k}
                        onMouseEnter={() => setFocus(k)}
                        className={cn(
                          "relative rounded-lg border bg-card p-3 transition hover:shadow-card",
                          cls === "conf-low" ? "border-rose-300/70 bg-rose-500/[0.04] dark:border-rose-800" : cls === "conf-mid" ? "border-amber-300/70 bg-amber-500/[0.05] dark:border-amber-800/70" : "border-border",
                          hasErr && "ring-1 ring-rose-400/50",
                        )}
                      >
                        {cls === "conf-low" || cls === "conf-mid" ? <span className={cn("absolute inset-y-2 left-0 w-[3px] rounded-r-full", cls === "conf-low" ? "bg-rose-500" : "bg-amber-500")} /> : null}
                        <div className="mb-1.5 flex items-center justify-between gap-2">
                          <span className="text-[12px] font-medium text-muted-foreground">{FIELD_LABEL[k] ?? k}{req ? <span className="text-rose-500"> *</span> : null}</span>
                          <span className="flex items-center gap-2">
                            <span className="inline-flex items-center gap-1 rounded bg-muted px-1.5 py-px text-[10.5px] font-medium text-muted-foreground">
                              {f.method === "human" ? <User size={10} /> : <Bot size={10} />}{f.method === "self_check" ? "self-checked" : f.method}
                            </span>
                            {showConf ? <Confidence value={f.confidence} /> : null}
                          </span>
                        </div>
                        {input(k, f)}
                        {k === "estimated_amount" && f.value !== null ? <div className="mt-1 text-[12px] text-muted-foreground">{money(f.value, c.fields.currency?.value as string)}</div> : null}
                        {f.source ? (
                          <button
                            type="button"
                            onClick={() => { setFocus(k); setView("text"); }}
                            className="mt-2 flex w-full cursor-pointer items-start gap-1.5 rounded-md bg-muted/70 px-2 py-1.5 text-left text-[11.5px] leading-snug text-muted-foreground transition hover:bg-accent hover:text-accent-foreground"
                          >
                            <Quote size={11} className="mt-0.5 shrink-0" /><span className="line-clamp-2">{f.source}</span>
                          </button>
                        ) : null}
                        {f.notes?.length ? <div className="mt-1.5 text-[12px] text-amber-700 dark:text-amber-400">{f.notes.join(" · ")}</div> : null}
                        {iss.map((i, n) => (
                          <div key={n} className={cn("mt-1.5 flex items-start gap-1.5 text-[12px]", i.severity === "error" ? "text-rose-600 dark:text-rose-400" : "text-amber-700 dark:text-amber-400")}>
                            {i.severity === "error" ? <CircleX size={13} className="mt-0.5 shrink-0" /> : <CircleAlert size={13} className="mt-0.5 shrink-0" />}{i.message}
                          </div>
                        ))}
                      </div>
                    );
                  })}
                  {(c.validation ?? []).filter((i) => !i.field).map((i, n) => <div key={n} className="text-[12.5px] text-rose-600">{i.message}</div>)}
                </div>
              ) : null}

              {tab === "trace" ? (
                <ol className="m-0 list-none p-0">
                  {c.events.map((e, idx) => {
                    const d = dot(e);
                    return (
                      <li key={e.id} className="relative pb-5 pl-9 last:pb-0">
                        {idx < c.events.length - 1 ? <span className="absolute bottom-0 left-[13px] top-7 w-px bg-border" /> : null}
                        <span className={cn("absolute left-0 top-0 grid h-[27px] w-[27px] place-items-center rounded-full border bg-card",
                          d === "bad" ? "border-rose-300 text-rose-600" : d === "human" ? "border-amber-300 text-amber-600" : "border-border text-muted-foreground")}>
                          {d === "bad" ? <CircleX size={13} /> : d === "human" ? <User size={13} /> : <Bot size={13} />}
                        </span>
                        <div className="flex flex-wrap items-baseline gap-x-2">
                          <span className="font-medium">{e.step ?? e.event_type}</span>
                          {e.step ? <span className="text-[11.5px] text-muted-foreground">{e.event_type}</span> : null}
                        </div>
                        <div className="text-[11.5px] text-muted-foreground">{when(e.ts)} · {e.actor}{e.duration_ms !== null ? ` · ${ms(e.duration_ms)}` : ""}</div>
                        {Object.keys(e.details ?? {}).length ? (
                          <details className="mt-1 text-[12px]">
                            <summary className="cursor-pointer select-none text-muted-foreground hover:text-foreground">details</summary>
                            <pre className="mt-1.5 max-h-72 overflow-auto whitespace-pre-wrap rounded-md border border-border bg-muted/50 p-2.5 text-[11.5px]">{JSON.stringify(e.details, null, 2)}</pre>
                          </details>
                        ) : null}
                      </li>
                    );
                  })}
                </ol>
              ) : null}

              {tab === "payload" ? (
                c.payload_preview ? (
                  <>
                    <p className="mb-3 text-[12.5px] text-muted-foreground">
                      What will be sent to <b className="text-foreground">{c.payload_preview.system}</b>{c.payload_preview.stand_in ? " (stand-in)" : ""} as the first call
                      (POST /claim/v1/claims). The reporter and other parties are then added as ClaimContacts, the reporter is set,
                      and the draft is submitted. Every call carries a GW-DBTransaction-ID so a retry can never create a second claim.
                    </p>
                    <pre className="m-0 max-h-[560px] overflow-auto rounded-lg bg-[#0d1117] p-4 text-[12px] leading-relaxed text-[#c9d1d9]">
                      {JSON.stringify(c.payload_preview.body ?? c.payload_preview.error, null, 2)}
                    </pre>
                  </>
                ) : <p className="text-muted-foreground">No active claims-system integration, or your role cannot view the payload.</p>
              ) : null}
            </div>
          </Card>

          <div className="px-1 text-[12px] text-muted-foreground">
            Tokens: {String(c.llm_usage?.input_tokens ?? 0)} in / {String(c.llm_usage?.output_tokens ?? 0)} out over {String(c.llm_usage?.calls ?? 0)} call(s) ·
            steps: {Object.entries(c.timings_ms ?? {}).filter(([k]) => k !== "total").map(([k, v]) => `${k} ${ms(v)}`).join(" · ")}
            {c.reviewed_by ? ` · reviewed by ${c.reviewed_by}` : ""}
          </div>
        </div>
      </div>
    </>
  );
}
