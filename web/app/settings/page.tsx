"use client";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { ApiError, api, jsonInit, useApi } from "@/lib/api";
import { PageHeader } from "@/components/ui";
import { when } from "@/lib/format";

type CatalogItem = { kind: string; label: string; auth_modes?: string[]; notes: string; verified_against?: string; fields?: string[]; secret?: string };
type Integration = { id: string; kind: string; name: string; base_url: string; auth_mode: string; token_url: string | null; client_id: string | null; scopes: string | null; options: Record<string, unknown>; has_secret: boolean; is_active: boolean; is_stand_in: boolean; last_tested_at: string | null; last_test_ok: boolean | null; last_test_message: string | null };
type Connector = { id: string; kind: string; name: string; config: Record<string, unknown>; has_secret: boolean; is_active: boolean; last_polled_at: string | null; last_status: string | null };
type RuntimeSettings = { llm_provider: string; llm_model: string; confidence_threshold: number; auto_push: boolean; policy_number_regex: string; max_auto_push_amount: number; max_loss_age_days: number; review_if_injuries: boolean; date_order: string; blocking_fields: string[]; review_if_unfilled_mentions: boolean; mention_guard_fields: string[] };

const PLACEHOLDER: Record<string, { base: string; token: string; scopes: string }> = {
  guidewire: { base: "https://<tenant>.<region>.guidewire.net/cc/rest", token: "https://guidewire-hub.okta.com/oauth2/<auth-server-id>/v1/token", scopes: "tenant.<tenantId> <your ClaimCenter API scopes>" },
  duckcreek: { base: "https://<your-duck-creek-host>/api", token: "https://<identity-provider>/oauth2/token", scopes: "" },
  majesco: { base: "https://<your-majesco-host>/api", token: "https://<identity-provider>/oauth2/token", scopes: "" },
  webhook: { base: "https://hooks.example.com/fnol", token: "", scopes: "" },
};

function msg(e: unknown) { const d = (e as ApiError).detail; return typeof d === "string" ? d : JSON.stringify(d); }

function Integrations() {
  const { data, reload } = useApi<{ catalog: CatalogItem[]; integrations: Integration[] }>("/integrations");
  const [kind, setKind] = useState("guidewire");
  const [form, setForm] = useState({ name: "", base_url: "", auth_mode: "oauth2", token_url: "", client_id: "", secret: "", scopes: "" });
  const [editing, setEditing] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const item = data?.catalog.find((c) => c.kind === kind);
  const set = (k: string, v: string) => setForm({ ...form, [k]: v });

  async function save() {
    setNote(null);
    try {
      const body = { kind, ...form, name: form.name || item?.label, secret: form.secret || null };
      const r = editing ? await api<Integration>(`/integrations/${editing}`, jsonInit("PUT", body)) : await api<Integration>("/integrations", jsonInit("POST", body));
      setForm({ ...form, secret: "" }); setEditing(r.id); setNote("Saved. Credentials are encrypted and will not be shown again. Now press Test connection."); reload();
    } catch (e) { setNote(msg(e)); }
  }
  async function test(id: string) { try { await api(`/integrations/${id}/test`, { method: "POST" }); reload(); } catch (e) { setNote(msg(e)); } }
  async function activate(id: string) { try { await api(`/integrations/${id}/activate`, { method: "POST" }); reload(); } catch (e) { setNote(msg(e)); } }
  function edit(i: Integration) {
    setEditing(i.id); setKind(i.kind);
    setForm({ name: i.name, base_url: i.base_url, auth_mode: i.auth_mode, token_url: i.token_url ?? "", client_id: i.client_id ?? "", secret: "", scopes: i.scopes ?? "" });
  }

  return (
    <>
      <div className="panel">
        <h2>Connected claims systems</h2>
        {!data?.integrations.length ? <p className="muted">None yet.</p> : (
          <table>
            <thead><tr><th>Name</th><th>System</th><th>Base URL</th><th>Auth</th><th>Last test</th><th>State</th><th></th></tr></thead>
            <tbody>
              {data.integrations.map((i) => (
                <tr key={i.id}>
                  <td><b>{i.name}</b> {i.is_stand_in ? <span className="tag standin">stand-in</span> : null}</td>
                  <td>{data.catalog.find((c) => c.kind === i.kind)?.label}</td>
                  <td className="mono small">{i.base_url}</td>
                  <td className="small">{i.auth_mode}{i.has_secret ? " · secret stored 🔒" : ""}</td>
                  <td className="small">{i.last_test_ok === null ? "never" : i.last_test_ok ? <span className="ok">✓ {i.last_test_message}</span> : <span className="err">✕ {i.last_test_message}</span>}<div className="muted">{when(i.last_tested_at)}</div></td>
                  <td>{i.is_active ? <span className="badge s-pushed">Active</span> : <span className="badge s-rejected">Inactive</span>}</td>
                  <td className="row">
                    <button onClick={() => test(i.id)}>Test connection</button>
                    {!i.is_active ? <button className="primary" onClick={() => activate(i.id)} disabled={!i.last_test_ok}>Activate</button> : null}
                    <button onClick={() => edit(i)}>Edit</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <div className="panel">
        <h2>{editing ? "Edit connection" : "Connect a claims system"}</h2>
        <div className="catalog">
          {(data?.catalog ?? []).map((c) => (
            <button key={c.kind} className={`opt ${kind === c.kind ? "on" : ""}`} onClick={() => { setKind(c.kind); setForm({ ...form, auth_mode: c.auth_modes?.[0] ?? "oauth2" }); }}>
              <b>{c.label}</b><span className="small muted">{c.notes}</span>
            </button>
          ))}
        </div>
        {item?.verified_against ? <p className="small muted">Request shapes follow: {item.verified_against}.</p> : null}
        <div className="grid2">
          <div>
            <label className="f">Display name</label><input value={form.name} placeholder={item?.label} onChange={(e) => set("name", e.target.value)} />
            <label className="f">{kind === "webhook" ? "Webhook URL" : "API base URL"}</label><input value={form.base_url} placeholder={PLACEHOLDER[kind]?.base} onChange={(e) => set("base_url", e.target.value)} />
            <label className="f">Authentication</label>
            <select value={form.auth_mode} onChange={(e) => set("auth_mode", e.target.value)}>
              {(item?.auth_modes ?? ["oauth2"]).map((m) => <option key={m} value={m}>{m === "oauth2" ? "OAuth 2.0 client credentials" : m === "basic" ? "Basic auth (self-managed / dev)" : m === "hmac" ? "HMAC-signed payload" : "None"}</option>)}
            </select>
          </div>
          <div>
            {form.auth_mode === "oauth2" ? (<>
              <label className="f">Token URL</label><input value={form.token_url} placeholder={PLACEHOLDER[kind]?.token} onChange={(e) => set("token_url", e.target.value)} />
              <label className="f">Scopes</label><input value={form.scopes} placeholder={PLACEHOLDER[kind]?.scopes} onChange={(e) => set("scopes", e.target.value)} />
            </>) : null}
            {form.auth_mode !== "none" && form.auth_mode !== "hmac" ? (<><label className="f">{form.auth_mode === "basic" ? "Username" : "Client ID"}</label><input value={form.client_id} onChange={(e) => set("client_id", e.target.value)} /></>) : null}
            {form.auth_mode !== "none" ? (<><label className="f">{form.auth_mode === "basic" ? "Password" : form.auth_mode === "hmac" ? "Signing secret" : "Client secret"}</label>
              <input type="password" autoComplete="new-password" value={form.secret} placeholder={editing ? "leave blank to keep the stored secret" : ""} onChange={(e) => set("secret", e.target.value)} /></>) : null}
          </div>
        </div>
        <div className="row" style={{ marginTop: 14 }}>
          <button className="primary" onClick={save}>{editing ? "Save changes" : "Save connection"}</button>
          {editing ? <button onClick={() => { setEditing(null); setForm({ name: "", base_url: "", auth_mode: "oauth2", token_url: "", client_id: "", secret: "", scopes: "" }); }}>New connection</button> : null}
          {note ? <span className="small">{note}</span> : null}
        </div>
        <p className="small muted">Secrets are encrypted at rest (Fernet, key from FNOL_SECRETS_KEY) and are never returned by the API. Only supervisors can change connections.</p>
      </div>
    </>
  );
}

function Email() {
  const { data, reload } = useApi<{ catalog: CatalogItem[]; connectors: Connector[] }>("/email-connectors");
  const [kind, setKind] = useState("composio_gmail");
  const [name, setName] = useState("");
  const [cfg, setCfg] = useState<Record<string, string>>({});
  const [secret, setSecret] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const item = data?.catalog.find((c) => c.kind === kind);
  async function create() {
    try { await api("/email-connectors", jsonInit("POST", { kind, name: name || item?.label, config: cfg, secret: secret || null })); setSecret(""); setNote("Saved."); reload(); }
    catch (e) { setNote(msg(e)); }
  }
  async function test(id: string) { try { const r = await api<{ ok: boolean; message: string }>(`/email-connectors/${id}/test`, { method: "POST" }); setNote((r.ok ? "✓ " : "✕ ") + r.message); reload(); } catch (e) { setNote(msg(e)); } }
  async function toggle(id: string) { await api(`/email-connectors/${id}/toggle`, { method: "POST" }); reload(); }
  return (
    <>
      <div className="panel">
        <h2>Claims inboxes</h2>
        {note ? <p className="small">{note}</p> : null}
        {!data?.connectors.length ? <p className="muted">None yet.</p> : (
          <table>
            <thead><tr><th>Name</th><th>Type</th><th>Settings</th><th>Watching</th><th>Last status</th><th></th></tr></thead>
            <tbody>{data.connectors.map((c) => (
              <tr key={c.id}>
                <td><b>{c.name}</b></td><td>{data.catalog.find((x) => x.kind === c.kind)?.label}</td>
                <td className="mono small">{Object.entries(c.config).map(([k, v]) => `${k}: ${v}`).join(" · ")}</td>
                <td>{c.is_active ? "Yes" : "No"}</td><td className="small">{c.last_status ?? "—"}</td>
                <td className="row"><button onClick={() => test(c.id)}>Test</button><button onClick={() => toggle(c.id)}>{c.is_active ? "Pause" : "Start watching"}</button></td>
              </tr>))}
            </tbody>
          </table>
        )}
      </div>
      <div className="panel">
        <h2>Add an inbox</h2>
        <div className="catalog">
          {(data?.catalog ?? []).map((c) => (
            <button key={c.kind} className={`opt ${kind === c.kind ? "on" : ""}`} onClick={() => { setKind(c.kind); setCfg({}); }}>
              <b>{c.label}</b><span className="small muted">{c.notes}</span>
            </button>))}
        </div>
        <div className="grid2">
          <div>
            <label className="f">Display name</label><input value={name} placeholder={item?.label} onChange={(e) => setName(e.target.value)} />
            {(item?.fields ?? []).map((f) => (<div key={f}><label className="f">{f.replace(/_/g, " ")}</label><input value={cfg[f] ?? ""} onChange={(e) => setCfg({ ...cfg, [f]: e.target.value })} /></div>))}
          </div>
          <div><label className="f">{item?.secret ?? "Secret"}</label><input type="password" autoComplete="new-password" value={secret} onChange={(e) => setSecret(e.target.value)} /></div>
        </div>
        <div className="row" style={{ marginTop: 14 }}><button className="primary" onClick={create}>Save inbox</button></div>
        <p className="small muted">All inbox connectors are read-only. Filter emails by subject, for example <span className="mono">subject:FNOL</span>.</p>
      </div>
    </>
  );
}

function Pipeline() {
  const { data, reload } = useApi<{ settings: RuntimeSettings; models: string[]; providers: string[] }>("/settings");
  const [s, setS] = useState<RuntimeSettings | null>(null);
  const [note, setNote] = useState<string | null>(null);
  useEffect(() => { if (data) setS(data.settings); }, [data]);
  if (!s || !data) return <div className="skeleton h-64" />;
  const set = (k: keyof RuntimeSettings, v: unknown) => setS({ ...s, [k]: v });
  async function save() { try { await api("/settings", jsonInit("PUT", s)); setNote("Saved."); reload(); } catch (e) { setNote(msg(e)); } }
  return (
    <div className="panel">
      <h2>AI and decision rules</h2>
      <div className="grid2">
        <div>
          <label className="f">LLM provider</label>
          <select value={s.llm_provider} onChange={(e) => set("llm_provider", e.target.value)}>{data.providers.map((p) => <option key={p}>{p}</option>)}</select>
          <label className="f">Model (or Azure deployment name)</label>
          <input list="models" value={s.llm_model} onChange={(e) => set("llm_model", e.target.value)} />
          <datalist id="models">{data.models.map((m) => <option key={m} value={m} />)}</datalist>
          <label className="f">Confidence threshold for auto-send ({Math.round(s.confidence_threshold * 100)}%)</label>
          <input type="range" min={0.5} max={0.99} step={0.01} value={s.confidence_threshold} onChange={(e) => set("confidence_threshold", Number(e.target.value))} />
          <label className="f"><input type="checkbox" style={{ width: "auto" }} checked={s.auto_push} onChange={(e) => set("auto_push", e.target.checked)} /> Send clean claims automatically (otherwise everything waits for review)</label>
        </div>
        <div>
          <label className="f">Policy number format (regex)</label><input className="mono" value={s.policy_number_regex} onChange={(e) => set("policy_number_regex", e.target.value)} />
          <label className="f">Auto-send authority limit (amount)</label><input type="number" value={s.max_auto_push_amount} onChange={(e) => set("max_auto_push_amount", Number(e.target.value))} />
          <label className="f">Late-notice warning after (days)</label><input type="number" value={s.max_loss_age_days} onChange={(e) => set("max_loss_age_days", Number(e.target.value))} />
          <label className="f">Forms write dates as</label><select value={s.date_order} onChange={(e) => set("date_order", e.target.value)}><option value="month_first">Month first (11/03/2026 = 3 Nov)</option><option value="day_first">Day first (03/11/2026 = 3 Nov)</option></select>
          <label className="f">Fields that must be confident before auto-send</label><input value={(s.blocking_fields || []).join(", ")} onChange={(e) => set("blocking_fields", e.target.value.split(",").map((x) => x.trim()).filter(Boolean))} />
          <label className="f"><input type="checkbox" style={{ width: "auto" }} checked={s.review_if_injuries} onChange={(e) => set("review_if_injuries", e.target.checked)} /> Always send bodily-injury claims to an adjuster</label>
          <label className="f"><input type="checkbox" style={{ width: "auto" }} checked={s.review_if_unfilled_mentions} onChange={(e) => set("review_if_unfilled_mentions", e.target.checked)} /> Hold for review if the source mentions an amount or another party that was not extracted</label>
        </div>
      </div>
      <div className="row" style={{ marginTop: 14 }}><button className="primary" onClick={save}>Save rules</button>{note ? <span className="small">{note}</span> : null}</div>
      <p className="small muted">API keys for the model provider are set as environment variables on the server, never in this screen.</p>
    </div>
  );
}

function SettingsInner() {
  const params = useSearchParams();
  const [tab, setTab] = useState(params.get("tab") ?? "claims");
  return (
    <>
      <PageHeader title="Settings" description="Where claims go, where they come from, and when a person must look first. Changes are written to the audit log." />
      <div className="tabs">
        <button className={tab === "claims" ? "on" : ""} onClick={() => setTab("claims")}>Claims system</button>
        <button className={tab === "email" ? "on" : ""} onClick={() => setTab("email")}>Email intake</button>
        <button className={tab === "pipeline" ? "on" : ""} onClick={() => setTab("pipeline")}>AI & rules</button>
      </div>
      {tab === "claims" ? <Integrations /> : tab === "email" ? <Email /> : <Pipeline />}
    </>
  );
}

export default function SettingsPage() {
  return <Suspense fallback={<div className="skeleton h-64" />}><SettingsInner /></Suspense>;
}
