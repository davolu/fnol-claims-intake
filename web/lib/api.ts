"use client";
import { useCallback, useEffect, useRef, useState } from "react";

export class ApiError extends Error {
  constructor(public status: number, public detail: unknown) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
}

export async function api<T = unknown>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`/api${path}`, { cache: "no-store", ...init });
  const text = await r.text();
  const data = text ? JSON.parse(text) : null;
  if (!r.ok) throw new ApiError(r.status, data?.detail ?? data);
  return data as T;
}

export function jsonInit(method: string, body: unknown): RequestInit {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

/** Fetch + optional polling. */
export function useApi<T>(path: string | null, pollMs = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const mounted = useRef(true);
  const load = useCallback(async () => {
    if (!path) return;
    try {
      const d = await api<T>(path);
      if (mounted.current) { setData(d); setError(null); }
    } catch (e) {
      if (mounted.current) setError((e as Error).message);
    } finally {
      if (mounted.current) setLoading(false);
    }
  }, [path]);
  useEffect(() => {
    mounted.current = true;
    load();
    if (!pollMs) return () => { mounted.current = false; };
    const t = setInterval(load, pollMs);
    return () => { mounted.current = false; clearInterval(t); };
  }, [load, pollMs]);
  return { data, error, loading, reload: load, setData };
}
