"use client";
import { ArrowRight, CircleDollarSign, ClipboardCheck, Gauge, Layers, Send, Zap } from "lucide-react";
import Link from "next/link";
import ClaimsTable, { ClaimRow } from "@/components/ClaimsTable";
import { Card, CardHeader, Kpi, PageHeader } from "@/components/ui";
import { useApi } from "@/lib/api";
import { STATUS_LABEL, ms, pct, usd } from "@/lib/format";

type Stats = {
  by_status: Record<string, number>; processed: number; auto_push: number; review: number;
  straight_through_rate: number | null; total_cost_usd: number; avg_cost_usd: number | null;
  avg_processing_ms: number | null; queue_depth: number;
};

const SEG: Record<string, string> = {
  pushed: "bg-emerald-500", approved: "bg-teal-500", needs_review: "bg-amber-500", processing: "bg-sky-500", queued: "bg-sky-400",
  pushing: "bg-sky-500", push_failed: "bg-rose-500", failed: "bg-rose-600", rejected: "bg-zinc-400",
};

export default function Dashboard() {
  const { data: s } = useApi<Stats>("/stats", 4000);
  const { data: claims } = useApi<{ claims: ClaimRow[] }>("/claims?limit=12", 4000);
  const total = Object.values(s?.by_status ?? {}).reduce((a, b) => a + b, 0);
  return (
    <>
      <PageHeader title="Dashboard" description="Clean claims go straight to the claims system. Anything uncertain waits for an adjuster." />
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-3 xl:grid-cols-6">
        <Kpi label="Processed" value={s?.processed ?? "—"} hint={`${s?.queue_depth ?? 0} in queue`} icon={Layers} tone="indigo" />
        <Kpi label="Straight-through" value={pct(s?.straight_through_rate)} hint={`${s?.auto_push ?? 0} sent automatically`} icon={Zap} tone="green" />
        <Kpi label="Needs review" value={s?.by_status?.needs_review ?? 0} hint="human in the loop" icon={ClipboardCheck} tone="amber" />
        <Kpi label="In claims system" value={s?.by_status?.pushed ?? 0} hint={`${s?.by_status?.push_failed ?? 0} send failures`} icon={Send} tone="sky" />
        <Kpi label="Avg processing" value={ms(s?.avg_processing_ms)} hint="OCR + AI + checks" icon={Gauge} tone="violet" />
        <Kpi label="AI cost / claim" value={usd(s?.avg_cost_usd)} hint={`total ${usd(s?.total_cost_usd)}`} icon={CircleDollarSign} tone="rose" />
      </div>

      <Card className="mt-4 p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2>Where claims are right now</h2>
          <span className="text-[12px] text-muted-foreground">{total} total</span>
        </div>
        {total ? (
          <>
            <div className="flex h-2.5 overflow-hidden rounded-full bg-muted">
              {Object.entries(s?.by_status ?? {}).map(([k, v]) => (
                <div key={k} className={SEG[k] ?? "bg-zinc-400"} style={{ width: `${(v / total) * 100}%` }} title={`${STATUS_LABEL[k] ?? k}: ${v}`} />
              ))}
            </div>
            <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5">
              {Object.entries(s?.by_status ?? {}).map(([k, v]) => (
                <span key={k} className="inline-flex items-center gap-1.5 text-[12.5px] text-muted-foreground">
                  <i className={`h-2 w-2 rounded-full ${SEG[k] ?? "bg-zinc-400"}`} />
                  {STATUS_LABEL[k] ?? k} <b className="font-semibold text-foreground tabular-nums">{v}</b>
                </span>
              ))}
            </div>
          </>
        ) : <p className="text-muted-foreground">No claims yet.</p>}
      </Card>

      <Card className="mt-4 overflow-hidden">
        <CardHeader
          title="Latest claims"
          description="Updates every few seconds"
          action={<Link href="/claims" className="inline-flex items-center gap-1 text-[12.5px] font-medium">All claims <ArrowRight size={13} /></Link>}
        />
        <ClaimsTable rows={claims?.claims ?? []} empty="Upload a claim form on the Intake page or connect a claims inbox." />
      </Card>
    </>
  );
}
