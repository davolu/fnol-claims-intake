"use client";
import Link from "next/link";
import { useRef, useState } from "react";
import { ArrowRight, FileText, Loader2, Mail, RefreshCw, UploadCloud } from "lucide-react";
import { Button, Card, CardHeader, Empty, PageHeader, Pill, StatusBadge, Td, Th } from "@/components/ui";
import { cn } from "@/lib/cn";
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
      <PageHeader title="Intake" description="Drop scanned claim forms (PDF, TIFF, PNG/JPEG), typed PDFs or saved emails (.eml). Each file becomes one claim." />
      <div
        className={cn(
          "group relative cursor-pointer overflow-hidden rounded-2xl border-2 border-dashed px-6 py-14 text-center transition",
          over ? "border-primary bg-accent/70" : "border-input bg-card hover:border-primary/50 hover:bg-accent/30",
        )}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); upload(e.dataTransfer.files); }}
        onClick={() => input.current?.click()}
        role="button"
        tabIndex={0}
      >
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(60%_80%_at_50%_0%,color-mix(in_srgb,var(--primary)_9%,transparent),transparent)]" />
        <div className="relative">
          <span className={cn("mx-auto mb-4 grid h-12 w-12 place-items-center rounded-xl bg-accent text-accent-foreground shadow-card transition", over && "scale-110")}>
            {busy ? <Loader2 size={22} className="animate-spin" /> : <UploadCloud size={22} />}
          </span>
          <div className="text-[16px] font-semibold tracking-tight">{busy ? "Uploading…" : over ? "Release to upload" : "Drag & drop claim documents here"}</div>
          <div className="mt-1 text-[12.5px] text-muted-foreground">or click to choose files</div>
          <div className="mt-4 flex flex-wrap items-center justify-center gap-1.5">
            {["PDF", "TIFF", "PNG", "JPEG", "EML", "TXT"].map((t) => <Pill key={t}>{t}</Pill>)}
            <span className="text-[11.5px] text-muted-foreground">· max 25 MB each</span>
          </div>
          <input ref={input} type="file" multiple hidden accept=".pdf,.tif,.tiff,.png,.jpg,.jpeg,.eml,.txt"
            onChange={(e) => e.target.files && upload(e.target.files)} />
        </div>
      </div>

      {results.length ? (
        <Card className="mt-5 overflow-hidden">
          <CardHeader title="This session" description={`${results.length} file${results.length > 1 ? "s" : ""} uploaded`} />
          <table className="w-full border-collapse text-[13px]">
            <thead><tr><Th>File</Th><Th>Claim</Th><Th>Status</Th></tr></thead>
            <tbody>
              {results.map((r, i) => (
                <tr key={i}>
                  <Td><span className="inline-flex items-center gap-2"><FileText size={14} className="text-muted-foreground" />{r.filename}</span></Td>
                  <Td className="font-mono text-[12px]">{r.claim_id ? <Link href={`/claims/${r.claim_id}`}>{r.reference}</Link> : "—"}</Td>
                  <Td>
                    {r.error ? <span className="text-rose-600">{r.error}</span> : <StatusBadge status={statusOf(r.claim_id) ?? r.status ?? "queued"} />}
                    {r.duplicate ? <span className="ml-2 text-[12px] text-muted-foreground">duplicate of an earlier upload, not processed twice</span> : null}
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      ) : null}

      <Card className="mt-5 overflow-hidden">
        <CardHeader
          icon={Mail}
          title="Claims inboxes"
          description="Inbox access is read-only: the app never sends, deletes, moves or labels email."
          action={<Link href="/settings?tab=email" className="inline-flex items-center gap-1 text-[12.5px] font-medium">Manage connectors <ArrowRight size={13} /></Link>}
        />
        {msg ? <div className="px-5 pt-3 text-[12.5px] text-emerald-600">{msg}</div> : null}
        {!conns?.connectors.length ? <Empty icon={Mail} title="No inbox connected yet">Add Gmail or Microsoft 365 in Settings to pull FNOL emails automatically.</Empty> : (
          <table className="w-full border-collapse text-[13px]">
            <thead><tr><Th>Connector</Th><Th>Filter</Th><Th>State</Th><Th>Last check</Th><Th>Result</Th><Th /></tr></thead>
            <tbody>
              {conns.connectors.map((c) => (
                <tr key={c.id}>
                  <Td><div className="font-medium">{c.name}</div><div className="text-[11.5px] text-muted-foreground">{c.kind}</div></Td>
                  <Td><code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11.5px]">{String(c.config?.query ?? c.config?.subject_filter ?? "")}</code></Td>
                  <Td>{c.is_active ? <Pill tone="green">Watching</Pill> : <Pill>Paused</Pill>}</Td>
                  <Td className="text-[12px] text-muted-foreground">{when(c.last_polled_at)}</Td>
                  <Td className="max-w-[260px] text-[12px] text-muted-foreground">{c.last_status ?? "—"}</Td>
                  <Td className="text-right"><Button size="sm" onClick={() => poll(c.id)}><RefreshCw size={12} />Check now</Button></Td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}
