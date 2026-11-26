"use client";
import { FileText, Inbox, Mail, Paperclip, ScanLine } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ROUTE_LABEL, money, ms, usd, when } from "@/lib/format";
import { Confidence, Empty, Pill, StatusBadge, Td, Th } from "./ui";

export type ClaimRow = {
  id: string; reference: string; status: string; decision: string | null; policy_number: string | null;
  insured_name: string | null; loss_date: string | null; loss_cause: string | null; estimated_amount: number | null;
  currency: string | null; min_confidence: number | null; review_reason_count: number; route: string | null;
  source: string | null; filename: string | null; external_claim_number: string | null; cost_usd: number | null;
  total_ms: number | null; created_at: string;
};

const ROUTE_ICON: Record<string, typeof FileText> = {
  text_pdf: FileText,
  scanned_form: ScanLine,
  free_text_email: Mail,
  email_with_attachments: Paperclip,
};

export default function ClaimsTable({ rows, empty }: { rows: ClaimRow[]; empty?: string }) {
  const router = useRouter();
  if (!rows.length) return <Empty icon={Inbox} title="Nothing here yet">{empty ?? "No claims yet."}</Empty>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-[13px]">
        <thead>
          <tr>
            <Th>Claim</Th><Th>Status</Th><Th>Insured</Th><Th>Loss</Th><Th className="text-right">Amount</Th>
            <Th>Confidence</Th><Th>Claim #</Th><Th className="text-right">Time · cost</Th><Th>Received</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => {
            const Icon = (c.route && ROUTE_ICON[c.route]) || FileText;
            return (
              <tr key={c.id} className="group cursor-pointer transition hover:bg-muted/50" onClick={() => router.push(`/claims/${c.id}`)}>
                <Td>
                  <div className="flex items-center gap-2.5">
                    <span className="grid h-8 w-8 shrink-0 place-items-center rounded-md bg-muted text-muted-foreground"><Icon size={15} /></span>
                    <div className="min-w-0">
                      <Link href={`/claims/${c.id}`} className="whitespace-nowrap font-mono text-[12px] font-medium text-foreground hover:text-primary" onClick={(e) => e.stopPropagation()}>{c.reference}</Link>
                      <div className="text-[11.5px] text-muted-foreground">{c.route ? ROUTE_LABEL[c.route] ?? c.route : "—"}{c.source?.startsWith("email") ? " · inbox" : ""}</div>
                    </div>
                  </div>
                </Td>
                <Td>
                  <StatusBadge status={c.status} />
                  {c.review_reason_count ? <div className="mt-1 text-[11.5px] text-amber-700 dark:text-amber-400">{c.review_reason_count} flag{c.review_reason_count > 1 ? "s" : ""}</div> : null}
                </Td>
                <Td>
                  <div className="font-medium">{c.insured_name ?? <span className="text-muted-foreground">—</span>}</div>
                  <div className="font-mono text-[11.5px] text-muted-foreground">{c.policy_number ?? "no policy"}</div>
                </Td>
                <Td>
                  <div className="tabular-nums">{c.loss_date ?? "—"}</div>
                  {c.loss_cause ? <Pill className="mt-0.5 capitalize">{c.loss_cause.replace(/_/g, " ")}</Pill> : null}
                </Td>
                <Td className="text-right font-medium tabular-nums">{money(c.estimated_amount, c.currency)}</Td>
                <Td>{c.min_confidence !== null ? <Confidence value={c.min_confidence} /> : <span className="text-muted-foreground">—</span>}</Td>
                <Td className="font-mono text-[12px]">{c.external_claim_number ?? <span className="text-muted-foreground">—</span>}</Td>
                <Td className="text-right">
                  <div className="tabular-nums">{ms(c.total_ms)}</div>
                  <div className="text-[11.5px] text-muted-foreground tabular-nums">{usd(c.cost_usd)}</div>
                </Td>
                <Td className="whitespace-nowrap text-[12px] text-muted-foreground">{when(c.created_at)}</Td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
