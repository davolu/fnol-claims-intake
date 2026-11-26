"use client";
import Link from "next/link";
import { useApi } from "@/lib/api";
import { ms, when } from "@/lib/format";

type Ev = { id: number; ts: string; actor: string; event_type: string; step: string | null; duration_ms: number | null; details: Record<string, unknown>; claim_id?: string };

export default function Audit() {
  const { data } = useApi<{ events: (Ev & { claim_id?: string })[] }>("/audit?limit=300", 5000);
  return (
    <>
      <h1>Audit log</h1>
      <p className="sub">Append-only record of every extraction step, human edit, decision and push. Personal data is masked in this log.</p>
      <div className="panel">
        <table>
          <thead><tr><th>#</th><th>Time</th><th>Actor</th><th>Event</th><th>Step</th><th>Duration</th><th>Details</th></tr></thead>
          <tbody>
            {(data?.events ?? []).map((e) => (
              <tr key={e.id}>
                <td className="mono small">{e.id}</td>
                <td className="small">{when(e.ts)}</td>
                <td className="small">{e.actor}</td>
                <td><b>{e.event_type}</b></td>
                <td>{e.step ?? ""}</td>
                <td>{ms(e.duration_ms)}</td>
                <td className="mono small" style={{ maxWidth: 520, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {JSON.stringify(e.details).slice(0, 220)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="small muted">Open a claim to see its full trace. <Link href="/claims">All claims →</Link></p>
      </div>
    </>
  );
}
