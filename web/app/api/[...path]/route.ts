// Server-side proxy to the FastAPI backend. Keeps the API token on the server and forwards the
// signed-in reviewer's role so the API can mask PII for read-only roles.
import { cookies } from "next/headers";
import { NextRequest } from "next/server";

const API_URL = process.env.API_URL || "http://localhost:8000";
const TOKEN = process.env.APP_API_TOKEN || "";

async function forward(req: NextRequest, path: string[]) {
  const jar = await cookies();
  const role = jar.get("fnol_role")?.value || "adjuster";
  const name = jar.get("fnol_user")?.value || "demo.adjuster";
  const url = `${API_URL}/api/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;
  const headers: Record<string, string> = { "X-User-Role": role, "X-User-Name": name };
  if (TOKEN) headers["Authorization"] = `Bearer ${TOKEN}`;
  const ct = req.headers.get("content-type");
  if (ct) headers["Content-Type"] = ct;
  const init: RequestInit = { method: req.method, headers, cache: "no-store" };
  if (!["GET", "HEAD"].includes(req.method)) {
    init.body = await req.arrayBuffer();
  }
  try {
    const r = await fetch(url, init);
    const body = await r.arrayBuffer();
    const out = new Headers();
    for (const h of ["content-type", "content-disposition", "cache-control"]) {
      const v = r.headers.get(h);
      if (v) out.set(h, v);
    }
    return new Response(body, { status: r.status, headers: out });
  } catch {
    return Response.json({ detail: "API is unreachable. Is the backend running?" }, { status: 502 });
  }
}

type Ctx = { params: Promise<{ path: string[] }> };
export async function GET(req: NextRequest, ctx: Ctx) { return forward(req, (await ctx.params).path); }
export async function POST(req: NextRequest, ctx: Ctx) { return forward(req, (await ctx.params).path); }
export async function PUT(req: NextRequest, ctx: Ctx) { return forward(req, (await ctx.params).path); }
export async function PATCH(req: NextRequest, ctx: Ctx) { return forward(req, (await ctx.params).path); }
export async function DELETE(req: NextRequest, ctx: Ctx) { return forward(req, (await ctx.params).path); }
