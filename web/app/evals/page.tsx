"use client";
import { useEffect, useState } from "react";
import { Check, CircleDollarSign, Clock, FlaskConical, Play, ShieldAlert, Target, X, Percent, FileCheck2 } from "lucide-react";
import { Button, Card, CardHeader, Empty, Kpi, PageHeader, Pill, Td, Th } from "@/components/ui";
import { cn } from "@/lib/cn";
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

  const cs = run?.cases ?? [];
  const dec = {
    autoOk: cs.filter((c) => c.decision === "auto_push" && c.decision_ok).length,
    reviewOk: cs.filter((c) => c.decision !== "auto_push" && c.decision_ok).length,
    wrong: cs.filter((c) => !c.decision_ok).length,
  };
  const maxLat = Math.max(1, ...cs.map((c) => c.latency_s));
  const barTone = (v: number) => (v >= 0.99 ? "from-emerald-400 to-emerald-500" : v >= 0.9 ? "from-amber-300 to-amber-500" : "from-rose-400 to-rose-500");
  return (
    <>
      <PageHeader
        title="Evals"
        description="The pipeline run over a labelled set of SAMPLE claims (fictional people): scans, typed PDFs and emails, including deliberately bad ones."
        actions={
          <>
            <select
              value={sel ?? run?.id ?? ""}
              onChange={(e) => setSel(Number(e.target.value))}
              className="h-8 w-72 cursor-pointer rounded-md border border-input bg-card px-2 text-[12.5px] shadow-card"
            >
              {(data?.runs ?? []).map((r) => <option key={r.id} value={r.id}>#{r.id} · {r.model} · {when(r.created_at)}</option>)}
            </select>
            <Button variant="default" onClick={async () => { await api("/evals/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }); setQueued(true); }}>
              <Play size={12} />Run evals
            </Button>
          </>
        }
      />
      {queued ? <p className="mb-4 text-[12.5px] text-emerald-600">Eval run queued on the worker. It appears here when finished.</p> : null}
      {!s ? <Card><Empty icon={FlaskConical} title="No eval runs yet">Press Run evals to score the pipeline on the labelled sample set.</Empty></Card> : (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-3 xl:grid-cols-6">
            <Kpi label="Field accuracy" value={pct(s.overall_field_accuracy)} hint={`${fields.length} fields × ${s.cases - 1} claims`} icon={Target} tone="green" />
            <Kpi label="Right decision" value={pct(s.decision_accuracy)} hint="auto-send vs review" icon={Percent} tone="indigo" />
            <Kpi label="Unsafe auto-sends" value={s.unsafe_auto_push.length} hint={`${s.auto_push_count} auto-sent`} icon={ShieldAlert} tone={s.unsafe_auto_push.length ? "rose" : "green"} />
            <Kpi label="Doc type" value={pct(s.doc_kind_accuracy)} hint="FNOL vs not a claim" icon={FileCheck2} tone="sky" />
            <Kpi label="Cost, whole set" value={usd(s.total_cost_usd)} hint={`${s.llm_calls} calls · ${s.model}`} icon={CircleDollarSign} tone="amber" />
            <Kpi label="Avg time / claim" value={`${s.avg_latency_s} s`} hint="OCR + AI + checks" icon={Clock} tone="violet" />
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <Card className="p-5">
              <h2 className="mb-4">Accuracy by field</h2>
              <div className="space-y-2.5">
                {fields.map((k) => (
                  <div key={k} className="grid grid-cols-[150px_1fr_52px] items-center gap-3 text-[12.5px]">
                    <span className="text-muted-foreground">{FIELD_LABEL[k] ?? k}</span>
                    <span className="h-2 overflow-hidden rounded-full bg-muted">
                      <i className={cn("block h-full rounded-full bg-gradient-to-r", barTone(s.field_accuracy[k]))} style={{ width: `${s.field_accuracy[k] * 100}%` }} />
                    </span>
                    <b className="text-right font-semibold tabular-nums">{pct(s.field_accuracy[k])}</b>
                  </div>
                ))}
              </div>
              <p className="mt-4 text-[12px] text-muted-foreground">Before the self-check pass: {pct(Object.values(s.field_accuracy_before_self_check).reduce((a, b) => a + b, 0) / Math.max(1, fields.length))} average.</p>
            </Card>

            <div className="grid gap-4">
              <Card className="p-5">
                <h2 className="mb-4">Send-or-review decisions</h2>
                <div className="flex items-center gap-6">
                  <Donut parts={[{ v: dec.autoOk, c: "#10b981" }, { v: dec.reviewOk, c: "#6366f1" }, { v: dec.wrong, c: "#f43f5e" }]} label={`${dec.autoOk + dec.reviewOk}/${cs.length}`} sub="correct" />
                  <ul className="m-0 flex-1 list-none space-y-2 p-0 text-[12.5px]">
                    <Legend color="bg-emerald-500" label="Auto-sent, correctly" n={dec.autoOk} />
                    <Legend color="bg-indigo-500" label="Held for review, correctly" n={dec.reviewOk} />
                    <Legend color="bg-rose-500" label="Wrong call" n={dec.wrong} />
                  </ul>
                </div>
              </Card>
              <Card className="p-5">
                <h2 className="mb-4">Accuracy by document type</h2>
                <div className="space-y-2.5">
                  {Object.entries(s.by_format).map(([k, v]) => (
                    <div key={k} className="grid grid-cols-[150px_1fr_52px] items-center gap-3 text-[12.5px]">
                      <span className="capitalize text-muted-foreground">{k.replace(/_/g, " ")}</span>
                      <span className="h-2 overflow-hidden rounded-full bg-muted"><i className={cn("block h-full rounded-full bg-gradient-to-r", barTone(v))} style={{ width: `${v * 100}%` }} /></span>
                      <b className="text-right font-semibold tabular-nums">{pct(v)}</b>
                    </div>
                  ))}
                </div>
                <p className="mt-4 text-[12px] text-muted-foreground">Tokens: {s.input_tokens.toLocaleString()} in / {s.output_tokens.toLocaleString()} out.</p>
              </Card>
            </div>
          </div>

          <Card className="mt-4 overflow-hidden">
            <CardHeader title="Cases" description="One row per labelled sample. Time bars show relative latency." />
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-[13px]">
                <thead><tr><Th>Case</Th><Th>Route</Th><Th>Doc type</Th><Th>Decision</Th><Th>Expected</Th><Th>Fields</Th><Th>Flags</Th><Th>Time</Th><Th className="text-right">Cost</Th></tr></thead>
                <tbody>
                  {cs.map((c) => {
                    const ok = Object.values(c.fields_ok).filter(Boolean).length;
                    const tot = Object.keys(c.fields_ok).length;
                    const missed = Object.entries(c.fields_ok).filter(([, v]) => !v).map(([k]) => k);
                    return (
                      <tr key={c.id} className="transition hover:bg-muted/40">
                        <Td className="font-mono text-[12px] font-medium">{c.id}</Td>
                        <Td className="text-[12px] text-muted-foreground">{c.route.replace(/_/g, " ")}</Td>
                        <Td><Mark ok={c.kind_ok} />{c.kind}</Td>
                        <Td className="whitespace-nowrap"><Mark ok={c.decision_ok} /><Pill tone={c.decision === "auto_push" ? "green" : "amber"}>{c.decision === "auto_push" ? "auto-send" : "review"}</Pill></Td>
                        <Td className="text-[12px] text-muted-foreground">{c.expect_decision === "auto_push" ? "auto-send" : c.expect_decision}</Td>
                        <Td>{tot ? <span className={cn("tabular-nums", ok < tot && "font-semibold text-rose-600")}>{ok}/{tot}</span> : <span className="text-muted-foreground">n/a</span>}{missed.length ? <div className="text-[11.5px] text-rose-600">{missed.join(", ")}</div> : null}</Td>
                        <Td className="max-w-[280px]"><div className="flex flex-wrap gap-1">{Array.from(new Set(c.reasons)).map((r) => <Pill key={r} tone="neutral" className="font-mono text-[10.5px]">{r}</Pill>)}</div></Td>
                        <Td>
                          <div className="flex items-center gap-2"><span className="h-1.5 w-16 overflow-hidden rounded-full bg-muted"><i className="block h-full rounded-full bg-primary/70" style={{ width: `${(c.latency_s / maxLat) * 100}%` }} /></span><span className="text-[12px] tabular-nums text-muted-foreground">{c.latency_s}s</span></div>
                        </Td>
                        <Td className="text-right tabular-nums">{usd(c.usage?.cost_usd)}</Td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </>
  );
}

function Mark({ ok }: { ok: boolean }) {
  return ok
    ? <span className="mr-1.5 inline-grid h-4 w-4 place-items-center rounded-full bg-emerald-500/15 align-middle text-emerald-600"><Check size={10} strokeWidth={3} /></span>
    : <span className="mr-1.5 inline-grid h-4 w-4 place-items-center rounded-full bg-rose-500/15 align-middle text-rose-600"><X size={10} strokeWidth={3} /></span>;
}

function Legend({ color, label, n }: { color: string; label: string; n: number }) {
  return <li className="flex items-center gap-2"><i className={cn("h-2.5 w-2.5 rounded-full", color)} /><span className="flex-1 text-muted-foreground">{label}</span><b className="tabular-nums">{n}</b></li>;
}

function Donut({ parts, label, sub }: { parts: { v: number; c: string }[]; label: string; sub: string }) {
  const total = parts.reduce((a, p) => a + p.v, 0) || 1;
  const R = 42, C = 2 * Math.PI * R;
  let off = 0;
  return (
    <svg width="116" height="116" viewBox="0 0 116 116" className="shrink-0">
      <circle cx="58" cy="58" r={R} fill="none" stroke="var(--muted)" strokeWidth="12" />
      {parts.map((p, i) => {
        const len = (p.v / total) * C;
        const el = <circle key={i} cx="58" cy="58" r={R} fill="none" stroke={p.c} strokeWidth="12" strokeDasharray={`${Math.max(0, len - 2)} ${C}`} strokeDashoffset={-off} transform="rotate(-90 58 58)" strokeLinecap="butt" />;
        off += len;
        return p.v ? el : null;
      })}
      <text x="58" y="56" textAnchor="middle" className="fill-foreground text-[18px] font-semibold">{label}</text>
      <text x="58" y="72" textAnchor="middle" className="fill-muted-foreground text-[10px]">{sub}</text>
    </svg>
  );
}
