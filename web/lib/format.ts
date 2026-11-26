export const STATUS_LABEL: Record<string, string> = {
  queued: "Queued",
  processing: "Processing",
  needs_review: "Needs review",
  approved: "Approved",
  pushing: "Sending",
  pushed: "In claims system",
  push_failed: "Send failed",
  rejected: "Rejected",
  failed: "Failed",
};

export const ROUTE_LABEL: Record<string, string> = {
  text_pdf: "Typed PDF",
  scanned_form: "Scanned form",
  free_text_email: "Email",
  email_with_attachments: "Email + attachment",
};

export const FIELD_LABEL: Record<string, string> = {
  policy_number: "Policy number",
  line_of_business: "Line of business",
  loss_date: "Loss date",
  loss_time: "Loss time",
  loss_cause: "Cause of loss",
  loss_location: "Loss location",
  description: "Description",
  insured_name: "Insured",
  insured_phone: "Insured phone",
  insured_email: "Insured email",
  reporter_name: "Reported by",
  reporter_relationship: "Reporter relationship",
  other_parties: "Other parties",
  vehicle_or_property: "Vehicle / property",
  police_report_number: "Police / fire report",
  injuries: "Injuries",
  estimated_amount: "Estimated amount",
  currency: "Currency",
  line_items: "Damage line items",
};

export function money(v: unknown, currency?: string | null): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  return n.toLocaleString("en-US", { style: "currency", currency: currency || "USD" });
}

export function usd(v: number | null | undefined, digits = 4): string {
  if (v === null || v === undefined) return "—";
  return `$${v.toFixed(digits)}`;
}

export function ms(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return v >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${v} ms`;
}

export function when(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function pct(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `${Math.round(v * 1000) / 10}%`;
}

export function confClass(c: number | undefined, threshold = 0.85): string {
  if (c === undefined) return "";
  if (c >= threshold) return "conf-high";
  if (c >= 0.6) return "conf-mid";
  return "conf-low";
}

export function displayValue(v: unknown): string {
  if (v === null || v === undefined || v === "") return "";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (Array.isArray(v)) {
    return v
      .map((x) =>
        typeof x === "object" && x
          ? Object.values(x as Record<string, unknown>).filter((y) => y !== null && y !== "").join(" · ")
          : String(x))
      .join("\n");
  }
  return String(v);
}
