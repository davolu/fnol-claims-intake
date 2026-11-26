"use client";
import { useState } from "react";
import ClaimsTable, { ClaimRow } from "@/components/ClaimsTable";
import { Card, PageHeader, Segmented } from "@/components/ui";
import { useApi } from "@/lib/api";

const FILTERS = [
  { value: "", label: "All" },
  { value: "needs_review", label: "Needs review" },
  { value: "pushed", label: "In claims system" },
  { value: "failed", label: "Failed" },
  { value: "rejected", label: "Rejected" },
];

export default function Claims() {
  const [status, setStatus] = useState("");
  const { data } = useApi<{ claims: ClaimRow[] }>(`/claims?limit=300${status ? `&status=${status}` : ""}`, 5000);
  return (
    <>
      <PageHeader
        title="All claims"
        description="Every item received, whatever happened to it."
        actions={<Segmented value={status} onChange={setStatus} options={FILTERS} />}
      />
      <Card className="overflow-hidden">
        <ClaimsTable rows={data?.claims ?? []} />
      </Card>
    </>
  );
}
