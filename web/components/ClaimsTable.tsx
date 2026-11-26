"use client";
import { useRouter } from "next/navigation";
import { ROUTE_LABEL, money, ms, usd, when } from "@/lib/format";
import { Confidence, StatusBadge } from "./ui";

export type ClaimRow = {
  id: string; reference: string; status: string; decision: string | null; policy_number: string | null;
  insured_name: string | null; loss_date: string | null; loss_cause: string | null; estimated_amount: number | null;
  currency: string | null; min_confidence: number | null; review_reason_count: number; route: string | null;
  source: string | null; filename: string | null; external_claim_number: string | null; cost_usd: number | null;
  total_ms: number | null; created_at: string;
};

export default function ClaimsTable({ rows, empty }: { rows: ClaimRow[]; empty?: string }) {
  const router = useRouter();
  if (!rows.length) return <p className="muted">{empty ?? "No claims yet."}</p>;
  return (
    <table>
      <thead>
        <tr>
          <th>Reference</th><th>Status</th><th>Source</th><th>Policy</th><th>Insured</th><th>Loss date</th>
          <th>Cause</th><th>Amount</th><th>Lowest conf.</th><th>Claim #</th><th>Time</th><th>LLM cost</th>
          <th>Received</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((c) => (
          <tr key={c.id} className="click" onClick={() => router.push(`/claims/${c.id}`)}>
            <td className="mono"><a href={`/claims/${c.id}`}>{c.reference}</a></td>
            <td><StatusBadge status={c.status} />{c.review_reason_count ? <div className="small muted">{c.review_reason_count} flag(s)</div> : null}</td>
            <td><span className="tag">{c.route ? ROUTE_LABEL[c.route] ?? c.route : "—"}</span><div className="small muted">{c.source?.startsWith("email") ? "email" : "upload"}</div></td>
            <td className="mono">{c.policy_number ?? "—"}</td>
            <td>{c.insured_name ?? "—"}</td>
            <td>{c.loss_date ?? "—"}</td>
            <td>{c.loss_cause?.replace(/_/g, " ") ?? "—"}</td>
            <td>{money(c.estimated_amount, c.currency)}</td>
            <td>{c.min_confidence !== null ? <Confidence value={c.min_confidence} /> : "—"}</td>
            <td className="mono">{c.external_claim_number ?? "—"}</td>
            <td>{ms(c.total_ms)}</td>
            <td>{usd(c.cost_usd)}</td>
            <td className="small">{when(c.created_at)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
