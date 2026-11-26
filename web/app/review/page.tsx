"use client";
import ClaimsTable, { ClaimRow } from "@/components/ClaimsTable";
import { Card, PageHeader } from "@/components/ui";
import { useApi } from "@/lib/api";

export default function Review() {
  const { data } = useApi<{ claims: ClaimRow[] }>("/claims?status=needs_review,push_failed,failed&limit=300", 4000);
  return (
    <>
      <PageHeader
        title="Review queue"
        description="Claims the agent was not sure about, or that broke a business rule. Open one to see the source next to the extracted fields, fix anything highlighted, then approve or reject."
      />
      <Card className="overflow-hidden">
        <ClaimsTable rows={data?.claims ?? []} empty="The queue is empty. Nothing needs a person right now." />
      </Card>
    </>
  );
}
