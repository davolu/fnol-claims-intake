"use client";
import Link from "next/link";
import ClaimsTable, { ClaimRow } from "@/components/ClaimsTable";
import { Kpi } from "@/components/ui";
import { useApi } from "@/lib/api";
import { ms, pct, usd } from "@/lib/format";

type Stats = {
  by_status: Record<string, number>; processed: number; auto_push: number; review: number;
  straight_through_rate: number | null; total_cost_usd: number; avg_cost_usd: number | null;
  avg_processing_ms: number | null; queue_depth: number;
};

export default function Dashboard() {
  const { data: s } = useApi<Stats>("/stats", 4000);
  const { data: claims } = useApi<{ claims: ClaimRow[] }>("/claims?limit=12", 4000);
  return (
    <>
      <h1>Dashboard</h1>
      <p className="sub">Clean claims go straight to the claims system. Anything uncertain waits for an adjuster.</p>
      <div className="cards">
        <Kpi label="Processed" value={s?.processed ?? "—"} hint={`${s?.queue_depth ?? 0} in queue`} />
        <Kpi label="Straight-through" value={pct(s?.straight_through_rate)} hint={`${s?.auto_push ?? 0} auto-sent`} />
        <Kpi label="Needs review" value={s?.by_status?.needs_review ?? 0} hint="human in the loop" />
        <Kpi label="In claims system" value={s?.by_status?.pushed ?? 0} hint={`${s?.by_status?.push_failed ?? 0} send failures`} />
        <Kpi label="Avg processing" value={ms(s?.avg_processing_ms)} hint="OCR + AI + checks" />
        <Kpi label="Avg AI cost / claim" value={usd(s?.avg_cost_usd)} hint={`total ${usd(s?.total_cost_usd)}`} />
      </div>
      <div className="panel">
        <div className="spread"><h2>Latest claims</h2><Link href="/claims">All claims →</Link></div>
        <ClaimsTable rows={claims?.claims ?? []} empty="Nothing yet. Upload a claim form on the Intake page or connect a claims inbox." />
      </div>
    </>
  );
}
