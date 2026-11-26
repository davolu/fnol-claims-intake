"use client";
import { useState } from "react";
import ClaimsTable, { ClaimRow } from "@/components/ClaimsTable";
import { useApi } from "@/lib/api";
import { STATUS_LABEL } from "@/lib/format";

export default function Claims() {
  const [status, setStatus] = useState("");
  const { data } = useApi<{ claims: ClaimRow[] }>(`/claims?limit=300${status ? `&status=${status}` : ""}`, 5000);
  return (
    <>
      <h1>All claims</h1>
      <p className="sub">Every item received, whatever happened to it.</p>
      <div className="panel">
        <div className="row" style={{ marginBottom: 12 }}>
          <select value={status} onChange={(e) => setStatus(e.target.value)} style={{ width: 220 }}>
            <option value="">All statuses</option>
            {Object.entries(STATUS_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </div>
        <ClaimsTable rows={data?.claims ?? []} />
      </div>
    </>
  );
}
