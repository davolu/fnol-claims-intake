"use client";
import Link from "next/link";
import { useRef, useState } from "react";
import { StatusBadge } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { when } from "@/lib/format";

type Result = { filename: string; claim_id?: string; reference?: string; duplicate?: boolean; status?: string; error?: string };
type Connector = { id: string; kind: string; name: string; is_active: boolean; last_polled_at: string | null; last_status: string | null; config: Record<string, unknown> };
type ClaimLite = { id: string; status: string; reference: string };

export default function Intake() {
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<Result[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const { data: conns, reload } = useApi<{ connectors: Connector[] }>("/email-connectors", 10000);
  const { data: live } = useApi<{ claims: ClaimLite[] }>("/claims?limit=100", 3000);
  const statusOf = (id?: string) => live?.claims.find((c) => c.id === id)?.status;

  async function upload(files: FileList | File[]) {
    const list = Array.from(files);
    if (!list.length) return;
    setBusy(true);
    const fd = new FormData();
    list.forEach((f) => fd.append("files", f));
    try {
      const r = await api<{ results: Result[] }>("/documents", { method: "POST", body: fd });
      setResults((prev) => [...r.results, ...prev]);
    } catch (e) {
      setResults((prev) => [{ filename: list.map((f) => f.name).join(", "), error: (e as Error).message }, ...prev]);
    } finally {
      setBusy(false);
    }
  }

  async function poll(id: string) {
    await api(`/email-connectors/${id}/poll`, { method: "POST" });
    setMsg("Inbox check queued. New FNOL emails will appear below and in the claims list.");
    setTimeout(reload, 4000);
  }

  return (
    <>
      <h1>Intake</h1>
      <p className="sub">Drop scanned claim forms (PDF, TIFF, PNG/JPEG), typed PDFs or saved emails (.eml). Each file becomes one claim.</p>
      <div
        className={`drop ${over ? "over" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); upload(e.dataTransfer.files); }}
        onClick={() => input.current?.click()}
        role="button"
        tabIndex={0}
      >
        <div className="big">{busy ? "Uploading…" : "Drag & drop claim documents here"}</div>
        <div className="muted">or click to choose files · PDF, TIFF, PNG, JPEG, EML, TXT · max 25 MB each</div>
        <input ref={input} type="file" multiple hidden accept=".pdf,.tif,.tiff,.png,.jpg,.jpeg,.eml,.txt"
          onChange={(e) => e.target.files && upload(e.target.files)} />
      </div>

      {results.length ? (
        <div className="panel" style={{ marginTop: 18 }}>
          <h2>This session</h2>
          <table>
            <thead><tr><th>File</th><th>Claim</th><th>Status</th></tr></thead>
            <tbody>
              {results.map((r, i) => (
                <tr key={i}>
                  <td>{r.filename}</td>
                  <td className="mono">{r.claim_id ? <Link href={`/claims/${r.claim_id}`}>{r.reference}</Link> : "—"}</td>
                  <td>
                    {r.error ? <span className="err">{r.error}</span> : <StatusBadge status={statusOf(r.claim_id) ?? r.status ?? "queued"} />}
                    {r.duplicate ? <span className="small muted"> · duplicate of an earlier upload, not processed twice</span> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      <div className="panel" style={{ marginTop: 18 }}>
        <div className="spread"><h2>Claims inboxes</h2><Link href="/settings?tab=email">Manage connectors →</Link></div>
        {msg ? <p className="ok">{msg}</p> : null}
        {!conns?.connectors.length ? <p className="muted">No inbox connected yet.</p> : (
          <table>
            <thead><tr><th>Connector</th><th>Filter</th><th>State</th><th>Last check</th><th>Result</th><th></th></tr></thead>
            <tbody>
              {conns.connectors.map((c) => (
                <tr key={c.id}>
                  <td><b>{c.name}</b><div className="small muted">{c.kind}</div></td>
                  <td className="mono small">{String(c.config?.query ?? c.config?.subject_filter ?? "")}</td>
                  <td>{c.is_active ? <span className="badge s-pushed">Watching</span> : <span className="badge s-rejected">Paused</span>}</td>
                  <td className="small">{when(c.last_polled_at)}</td>
                  <td className="small">{c.last_status ?? "—"}</td>
                  <td><button onClick={() => poll(c.id)}>Check now</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="small muted">Inbox access is read-only: the app never sends, deletes, moves or labels email.</p>
      </div>
    </>
  );
}
