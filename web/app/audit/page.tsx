"use client";
import { Bot, CircleCheck, CircleX, Cpu, FilePlus2, Pencil, Send, ShieldCheck, User } from "lucide-react";
import Link from "next/link";
import { Card, PageHeader, Pill, Td, Th } from "@/components/ui";
import { useApi } from "@/lib/api";
import { ms, when } from "@/lib/format";

type Ev = { id: number; ts: string; actor: string; event_type: string; step: string | null; duration_ms: number | null; details: Record<string, unknown>; claim_id?: string };

function kind(t: string): { tone: "neutral" | "amber" | "green" | "red" | "blue" | "violet"; icon: typeof Bot } {
  if (/fail|reject/.test(t)) return { tone: "red", icon: CircleX };
  if (t === "pushed") return { tone: "green", icon: Send };
  if (t === "approved") return { tone: "green", icon: CircleCheck };
  if (t === "fields_edited") return { tone: "amber", icon: Pencil };
  if (t === "received") return { tone: "blue", icon: FilePlus2 };
  if (t === "decision" || t === "needs_review") return { tone: "violet", icon: ShieldCheck };
  return { tone: "neutral", icon: Cpu };
}

export default function Audit() {
  const { data } = useApi<{ events: Ev[] }>("/audit?limit=300", 5000);
  return (
    <>
      <PageHeader
        title="Audit log"
        description="Append-only record of every extraction step, human edit, decision and push. Personal data is masked in this log."
        actions={<Link href="/claims" className="text-[12.5px] font-medium">Open a claim for its full trace →</Link>}
      />
      <Card className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-[13px]">
            <thead><tr><Th>#</Th><Th>Time</Th><Th>Actor</Th><Th>Event</Th><Th className="text-right">Duration</Th><Th>Details</Th></tr></thead>
            <tbody>
              {(data?.events ?? []).map((e) => {
                const k = kind(e.event_type);
                const Icon = k.icon;
                const human = e.actor.startsWith("user:");
                return (
                  <tr key={e.id} className="transition hover:bg-muted/40">
                    <Td className="font-mono text-[11.5px] text-muted-foreground">{e.id}</Td>
                    <Td className="whitespace-nowrap text-[12px] text-muted-foreground">{when(e.ts)}</Td>
                    <Td>
                      <span className="inline-flex items-center gap-1.5 text-[12.5px]">
                        {human ? <User size={13} className="text-amber-600" /> : <Bot size={13} className="text-muted-foreground" />}
                        {e.actor.replace(/^user:/, "")}
                      </span>
                    </Td>
                    <Td>
                      <Pill tone={k.tone}><Icon size={11} />{e.step ?? e.event_type}</Pill>
                      {e.step ? <span className="ml-1.5 text-[11.5px] text-muted-foreground">{e.event_type}</span> : null}
                    </Td>
                    <Td className="text-right text-[12px] tabular-nums text-muted-foreground">{ms(e.duration_ms)}</Td>
                    <Td className="max-w-[460px]"><div className="truncate font-mono text-[11.5px] text-muted-foreground">{JSON.stringify(e.details).slice(0, 200)}</div></Td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
