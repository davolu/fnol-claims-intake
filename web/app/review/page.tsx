"use client";
import ClaimsTable, { ClaimRow } from "@/components/ClaimsTable";
import { useApi } from "@/lib/api";

export default function Review() {
  const { data } = useApi<{ claims: ClaimRow[] }>("/claims?status=needs_review,push_failed,failed&limit=300", 4000);
  return (
    <>
      <h1>Review queue</h1>
      <p className="sub">
        Claims the agent was not sure about, or that broke a business rule. Open one to see the source next to the
        extracted fields, fix anything highlighted, then approve or reject.
      </p>
      <div className="panel">
        <ClaimsTable rows={data?.claims ?? []} empty="Queue is empty. Nice." />
      </div>
    </>
  );
}
