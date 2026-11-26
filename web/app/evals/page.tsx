"use client";
import { useEffect, useState } from "react";
import { Kpi } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { FIELD_LABEL, pct, usd, when } from "@/lib/format";

type Summary = {
  model: string; cases: number; field_accuracy: Record<string, number>; field_accuracy_before_self_check: Record<string, number>;
  overall_field_accuracy: number; doc_kind_accuracy: number; decision_accuracy: number; auto_push_count: number;
  auto_push_precision: number | null; unsafe_auto_push: string[]; total_cost_usd: number; input_tokens: number;
  output_tokens: number; llm_calls: number; avg_latency_s: number; by_format: Record<string, number>;
};
type Case = { id: string; format: string; route: string; kind: string; kind_ok: boolean; decision: string; expect_decision: string;
  decision_ok: boolean; reasons: string[]; fields_ok: Record<string, boolean>; latency_s: number; usage: { cost_usd: number }; self_checked: string[] };
type Run = { id: number; created_at: string; model: string; summary: Summary; cases?: Case[] };

export default function Evals() {
  const { data } = useApi<{ runs: Run[] }>("/evals", 10000);
  const [sel, setSel] = useState<number | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [queued, setQueued] = useState(false);
  useEffect(() => {
    const id = sel ?? data?.runs[0]?.id;
    if (id) api<Run>(`/evals/${id}`).then(setRun).catch(() => setRun(null));
  }, [sel, data]);
  const s = run?.summary;
  const fields = s ? Object.keys(s.field_accuracy) : [];
  return (
    <>
      <div className="spread">
        <div>
          <h1>Evals</h1>
          <p className="sub">The pipeline run over a labelled set of SAMPLE claims (fictional people): scans, typed PDFs and emails, including deliberately bad ones.</p>
        </div>
        <div className="row">
          <select value={sel ?? ""} onChange={(e) => setSel(Number(e.target.value))} style={{ width: 300 }}>
            {(data?.runs ?? []).map((r) => <option key={r.id} value={r.id}>#{r.id} · {r.model} · {when(r.created_at)}</option>)}
          </select>
          <button onClick={async () => { await api("/evals/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }); setQueued(true); }}>Run evals</button>
        </div>
      </div>
      {queued ? <p className="ok">Eval run queued on the worker. It appears here when finished.</p> : null}
      {!s ? <p className="muted">No eval runs yet.</p> : (
        <>
          <div className="cards">
            <Kpi label="Field accuracy" value={pct(s.overall_field_accuracy)} hint={`${fields.length} fields × ${s.cases - 1} claims`} />
            <Kpi label="Right decision" value={pct(s.decision_accuracy)} hint="auto-send vs review" />
            <Kpi label="Unsafe auto-sends" value={s.unsafe_auto_push.length} hint={`${s.auto_push_count} auto-sent`} />
            <Kpi label="Doc type" value={pct(s.doc_kind_accuracy)} hint="FNOL vs not a claim" />
            <Kpi label="Cost, whole set" value={usd(s.total_cost_usd)} hint={`${s.llm_calls} calls · ${s.model}`} />
            <Kpi label="Avg time / claim" value={`${s.avg_latency_s} s`} hint="OCR + AI + checks" />
          </div>
          <div className="grid2">
            <div className="panel">
              <h2>Accuracy by field</h2>
              {fields.map((k) => (
                <div className="accbar" key={k}>
                  <span>{FIELD_LABEL[k] ?? k}</span>
                  <span className="track"><i style={{ width: `${s.field_accuracy[k] * 100}%` }} /></span>
                  <b>{pct(s.field_accuracy[k])}</b>
                </div>
              ))}
              <p className="small muted">Before the self-check pass: {pct(Object.values(s.field_accuracy_before_self_check).reduce((a, b) => a + b, 0) / Math.max(1, fields.length))} average.</p>
            </div>
            <div className="panel">
              <h2>Accuracy by document type</h2>
              {Object.entries(s.by_format).map(([k, v]) => (
                <div className="accbar" key={k}><span>{k.replace(/_/g, " ")}</span><span className="track"><i style={{ width: `${v * 100}%` }} /></span><b>{pct(v)}</b></div>
              ))}
              <p className="small muted">Tokens: {s.input_tokens.toLocaleString()} in / {s.output_tokens.toLocaleString()} out.</p>
            </div>
          </div>
          <div className="panel">
            <h2>Cases</h2>
            <table>
              <thead><tr><th>Case</th><th>Route</th><th>Doc type</th><th>Decision</th><th>Expected</th><th>Fields right</th><th>Missed</th><th>Flags</th><th>Time</th><th>Cost</th></tr></thead>
              <tbody>
                {(run?.cases ?? []).map((c) => {
                  const ok = Object.values(c.fields_ok).filter(Boolean).length;
                  const tot = Object.keys(c.fields_ok).length;
                  return (
                    <tr key={c.id}>
                      <td className="mono small">{c.id}</td>
                      <td className="small">{c.route}</td>
                      <td>{c.kind} {c.kind_ok ? <span className="check">✓</span> : <span className="cross">✕</span>}</td>
                      <td>{c.decision} {c.decision_ok ? <span className="check">✓</span> : <span className="cross">✕</span>}</td>
                      <td className="small muted">{c.expect_decision}</td>
                      <td>{tot ? `${ok}/${tot}` : "n/a"}</td>
                      <td className="small">{Object.entries(c.fields_ok).filter(([, v]) => !v).map(([k]) => k).join(", ")}</td>
                      <td className="small">{c.reasons.join(", ")}</td>
                      <td>{c.latency_s}s</td>
                      <td>{usd(c.usage?.cost_usd)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}
