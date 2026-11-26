import { type LucideIcon, Check, CircleAlert, CircleCheck, CircleDashed, CircleX, Clock, Loader2, Send, ShieldCheck, TriangleAlert } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/cn";
import { STATUS_LABEL, confClass } from "@/lib/format";

/* ---------- Button (shadcn-style variants) ---------- */
type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "default" | "outline" | "ghost" | "destructive" | "secondary";
  size?: "sm" | "md" | "icon";
};
export function Button({ variant = "outline", size = "md", className, ...p }: BtnProps) {
  const v = {
    default: "bg-primary text-primary-foreground border-primary shadow-card hover:bg-primary/90",
    outline: "bg-card text-foreground border-input shadow-card hover:bg-muted",
    secondary: "bg-muted text-foreground border-transparent hover:bg-muted/70",
    ghost: "bg-transparent border-transparent text-muted-foreground hover:bg-muted hover:text-foreground",
    destructive: "bg-card text-rose-600 dark:text-rose-400 border-rose-200 dark:border-rose-900 hover:bg-rose-50 dark:hover:bg-rose-950/40",
  }[variant];
  const s = { sm: "h-7 px-2.5 text-[12px]", md: "h-8 px-3 text-[12.5px]", icon: "h-8 w-8 justify-center" }[size];
  return (
    <button
      {...p}
      className={cn("inline-flex shrink-0 cursor-pointer items-center gap-1.5 rounded-md border font-medium transition disabled:pointer-events-none disabled:opacity-50", v, s, className)}
    />
  );
}

/* ---------- Card ---------- */
export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn("rounded-xl border border-border bg-card shadow-card", className)}>{children}</div>;
}
export function CardHeader({ title, description, action, icon: Icon }: { title: ReactNode; description?: ReactNode; action?: ReactNode; icon?: LucideIcon }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-3.5">
      <div className="flex items-start gap-2.5">
        {Icon ? <span className="mt-0.5 grid h-7 w-7 place-items-center rounded-md bg-accent text-accent-foreground"><Icon size={15} /></span> : null}
        <div>
          <h2 className="leading-tight">{title}</h2>
          {description ? <p className="mt-0.5 text-[12px] text-muted-foreground">{description}</p> : null}
        </div>
      </div>
      {action}
    </div>
  );
}

export function PageHeader({ title, description, actions }: { title: ReactNode; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1>{title}</h1>
        {description ? <p className="mt-1 max-w-3xl text-[13.5px] text-muted-foreground">{description}</p> : null}
      </div>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </div>
  );
}

/* ---------- Status badge ---------- */
const STATUS_STYLE: Record<string, { cls: string; icon: LucideIcon; spin?: boolean }> = {
  queued: { cls: "bg-sky-500/10 text-sky-700 dark:text-sky-400 ring-sky-500/20", icon: Clock },
  processing: { cls: "bg-sky-500/10 text-sky-700 dark:text-sky-400 ring-sky-500/20", icon: Loader2, spin: true },
  needs_review: { cls: "bg-amber-500/10 text-amber-700 dark:text-amber-400 ring-amber-500/25", icon: TriangleAlert },
  approved: { cls: "bg-teal-500/10 text-teal-700 dark:text-teal-400 ring-teal-500/20", icon: Check },
  pushing: { cls: "bg-sky-500/10 text-sky-700 dark:text-sky-400 ring-sky-500/20", icon: Send },
  pushed: { cls: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 ring-emerald-500/20", icon: CircleCheck },
  push_failed: { cls: "bg-rose-500/10 text-rose-700 dark:text-rose-400 ring-rose-500/20", icon: CircleAlert },
  failed: { cls: "bg-rose-500/10 text-rose-700 dark:text-rose-400 ring-rose-500/20", icon: CircleX },
  rejected: { cls: "bg-zinc-500/10 text-zinc-600 dark:text-zinc-400 ring-zinc-500/20", icon: CircleDashed },
};

export function StatusBadge({ status }: { status: string }) {
  const s = STATUS_STYLE[status] ?? STATUS_STYLE.rejected;
  const Icon = s.icon;
  return (
    <span className={cn("inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[11.5px] font-medium ring-1 ring-inset", s.cls)}>
      <Icon size={12} className={s.spin ? "animate-spin" : ""} />
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

export function Pill({ children, tone = "neutral", className }: { children: ReactNode; tone?: "neutral" | "amber" | "green" | "red" | "blue" | "violet"; className?: string }) {
  const t = {
    neutral: "bg-muted text-muted-foreground ring-border",
    amber: "bg-amber-500/10 text-amber-700 dark:text-amber-400 ring-amber-500/25",
    green: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 ring-emerald-500/20",
    red: "bg-rose-500/10 text-rose-700 dark:text-rose-400 ring-rose-500/20",
    blue: "bg-sky-500/10 text-sky-700 dark:text-sky-400 ring-sky-500/20",
    violet: "bg-violet-500/10 text-violet-700 dark:text-violet-400 ring-violet-500/20",
  }[tone];
  return <span className={cn("inline-flex items-center gap-1 whitespace-nowrap rounded-md px-1.5 py-0.5 text-[11.5px] font-medium ring-1 ring-inset", t, className)}>{children}</span>;
}

/* ---------- Confidence meter ---------- */
const BAR = { "conf-high": "bg-emerald-500", "conf-mid": "bg-amber-500", "conf-low": "bg-rose-500" } as Record<string, string>;
const TXT = { "conf-high": "text-emerald-700 dark:text-emerald-400", "conf-mid": "text-amber-700 dark:text-amber-400", "conf-low": "text-rose-700 dark:text-rose-400" } as Record<string, string>;

export function Confidence({ value, threshold = 0.85, wide }: { value?: number | null; threshold?: number; wide?: boolean }) {
  if (value === undefined || value === null) return <span className="text-muted-foreground">—</span>;
  const k = confClass(value, threshold);
  return (
    <span className="inline-flex items-center gap-2" title={`confidence ${value}`}>
      <span className={cn("h-1.5 overflow-hidden rounded-full bg-muted", wide ? "w-24" : "w-14")}>
        <span className={cn("block h-full rounded-full", BAR[k])} style={{ width: `${Math.round(value * 100)}%` }} />
      </span>
      <span className={cn("w-8 text-[11.5px] font-semibold tabular-nums", TXT[k])}>{Math.round(value * 100)}%</span>
    </span>
  );
}

/* ---------- KPI ---------- */
export function Kpi({ label, value, hint, icon: Icon, tone = "indigo" }: { label: string; value: ReactNode; hint?: string; icon?: LucideIcon; tone?: "indigo" | "green" | "amber" | "sky" | "violet" | "rose" }) {
  const t = {
    indigo: "bg-indigo-500/10 text-indigo-600 dark:text-indigo-400",
    green: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
    amber: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
    sky: "bg-sky-500/10 text-sky-600 dark:text-sky-400",
    violet: "bg-violet-500/10 text-violet-600 dark:text-violet-400",
    rose: "bg-rose-500/10 text-rose-600 dark:text-rose-400",
  }[tone];
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between">
        <span className="text-[12px] font-medium text-muted-foreground">{label}</span>
        {Icon ? <span className={cn("grid h-7 w-7 place-items-center rounded-md", t)}><Icon size={15} /></span> : null}
      </div>
      <div className="mt-2 text-[26px] font-semibold leading-none tracking-tight tabular-nums">{value}</div>
      {hint ? <div className="mt-1.5 text-[12px] text-muted-foreground">{hint}</div> : null}
    </Card>
  );
}

/* ---------- Alert ---------- */
export function Alert({ tone = "info", title, children, icon: Icon }: { tone?: "info" | "warn" | "danger" | "success"; title?: ReactNode; children?: ReactNode; icon?: LucideIcon }) {
  const t = {
    info: "border-sky-500/25 bg-sky-500/[0.07] text-sky-900 dark:text-sky-200",
    warn: "border-amber-500/30 bg-amber-500/[0.08] text-amber-900 dark:text-amber-200",
    danger: "border-rose-500/30 bg-rose-500/[0.07] text-rose-900 dark:text-rose-200",
    success: "border-emerald-500/25 bg-emerald-500/[0.07] text-emerald-900 dark:text-emerald-200",
  }[tone];
  const D = Icon ?? (tone === "danger" ? CircleAlert : tone === "warn" ? TriangleAlert : tone === "success" ? ShieldCheck : CircleAlert);
  return (
    <div className={cn("flex gap-2.5 rounded-lg border px-3.5 py-2.5 text-[13px]", t)}>
      <D size={16} className="mt-0.5 shrink-0 opacity-80" />
      <div>{title ? <b className="font-semibold">{title} </b> : null}{children}</div>
    </div>
  );
}

export function Segmented<T extends string>({ value, onChange, options }: { value: T; onChange: (v: T) => void; options: { value: T; label: ReactNode }[] }) {
  return (
    <div className="inline-flex gap-0.5 rounded-lg bg-muted p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          className={cn("cursor-pointer rounded-md px-2.5 py-1 text-[12px] font-medium transition", value === o.value ? "bg-card text-foreground shadow-card" : "text-muted-foreground hover:text-foreground")}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Empty({ icon: Icon, title, children }: { icon: LucideIcon; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      <span className="mb-3 grid h-10 w-10 place-items-center rounded-full bg-muted text-muted-foreground"><Icon size={18} /></span>
      <div className="font-medium">{title}</div>
      {children ? <p className="mt-1 max-w-sm text-[12.5px] text-muted-foreground">{children}</p> : null}
    </div>
  );
}

export function Th({ children, className }: { children?: ReactNode; className?: string }) {
  return <th className={cn("whitespace-nowrap border-b border-border bg-muted/40 px-3.5 py-2 text-left text-[11px] font-medium uppercase tracking-wider text-muted-foreground first:pl-5 last:pr-5", className)}>{children}</th>;
}
export function Td({ children, className, ...p }: { children?: ReactNode; className?: string } & React.TdHTMLAttributes<HTMLTableCellElement>) {
  return <td {...p} className={cn("border-b border-border/70 px-3.5 py-3 align-middle first:pl-5 last:pr-5", className)}>{children}</td>;
}
