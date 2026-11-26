"use client";
import { ClipboardCheck, FileStack, FlaskConical, LayoutDashboard, Moon, ScrollText, Settings, ShieldCheck, Sun, UploadCloud, FlaskRound } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useApi } from "@/lib/api";
import { cn } from "@/lib/cn";

const NAV = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/intake", label: "Intake", icon: UploadCloud },
  { href: "/review", label: "Review queue", icon: ClipboardCheck, count: true },
  { href: "/claims", label: "All claims", icon: FileStack },
  { href: "/evals", label: "Evals", icon: FlaskConical },
  { href: "/audit", label: "Audit log", icon: ScrollText },
  { href: "/settings", label: "Settings", icon: Settings },
];

function getCookie(name: string): string | null {
  const m = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return m ? decodeURIComponent(m[1]) : null;
}

type Stats = { by_status: Record<string, number> };
type Integrations = { integrations: { is_active: boolean; is_stand_in: boolean; name: string }[] };

export default function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const [role, setRole] = useState("adjuster");
  const [dark, setDark] = useState(false);
  const { data: stats } = useApi<Stats>("/stats", 5000);
  const { data: integ } = useApi<Integrations>("/integrations", 15000);
  useEffect(() => {
    setRole(getCookie("fnol_role") || "adjuster");
    setDark(document.documentElement.classList.contains("dark"));
  }, []);
  const pending = (stats?.by_status?.needs_review ?? 0) + (stats?.by_status?.push_failed ?? 0);
  const active = integ?.integrations.find((i) => i.is_active);

  function changeRole(r: string) {
    const names: Record<string, string> = { adjuster: "demo.adjuster", supervisor: "demo.supervisor", auditor: "demo.auditor" };
    document.cookie = `fnol_role=${r}; path=/; samesite=lax`;
    document.cookie = `fnol_user=${names[r]}; path=/; samesite=lax`;
    setRole(r);
    router.refresh();
    window.location.reload();
  }
  function toggleTheme() {
    const next = !dark;
    document.documentElement.classList.toggle("dark", next);
    localStorage.setItem("fnol_theme", next ? "dark" : "light");
    setDark(next);
  }

  return (
    <div className="flex min-h-screen">
      <aside className="w-[232px] shrink-0 self-stretch border-r border-border bg-sidebar max-md:hidden">
       <div className="sticky top-0 flex h-screen flex-col px-3 py-4">
        <div className="mb-5 flex items-center gap-2.5 px-2">
          <div className="grid h-8 w-8 place-items-center rounded-[9px] bg-gradient-to-br from-indigo-500 via-indigo-600 to-violet-600 text-white shadow-[0_2px_8px_-2px_rgba(79,70,229,0.6)]">
            <ShieldCheck size={17} strokeWidth={2.4} />
          </div>
          <div className="leading-tight">
            <div className="text-[14px] font-semibold tracking-tight">FNOL Desk</div>
            <div className="text-[11px] text-muted-foreground">Claims intake · AI</div>
          </div>
        </div>
        <div className="mb-1.5 px-2 text-[10.5px] font-medium uppercase tracking-wider text-muted-foreground">Workspace</div>
        <nav className="flex flex-col gap-0.5">
          {NAV.map((n) => {
            const on = n.href === "/" ? path === "/" : path.startsWith(n.href);
            const Icon = n.icon;
            return (
              <Link
                key={n.href}
                href={n.href}
                className={cn(
                  "group flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px] font-medium no-underline transition hover:no-underline",
                  on ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
              >
                <Icon size={16} strokeWidth={on ? 2.2 : 1.8} />
                <span className="flex-1">{n.label}</span>
                {n.count && pending > 0 ? (
                  <span className="rounded-full bg-amber-500 px-1.5 text-[10.5px] font-semibold leading-[18px] text-white tabular-nums">{pending}</span>
                ) : null}
              </Link>
            );
          })}
        </nav>

        <div className="mt-auto space-y-3">
          <div className="rounded-lg border border-border bg-muted/40 p-2.5">
            <div className="text-[10.5px] font-medium uppercase tracking-wider text-muted-foreground">Claims system</div>
            <div className="mt-1 flex items-center gap-1.5 text-[12.5px] font-medium">
              <span className={cn("h-1.5 w-1.5 rounded-full", active ? "bg-emerald-500" : "bg-zinc-400")} />
              <span className="truncate">{active ? active.name : "none active"}</span>
            </div>
          </div>
          <div>
            <div className="mb-1 px-0.5 text-[10.5px] font-medium uppercase tracking-wider text-muted-foreground">Signed in role</div>
            <div className="flex items-center gap-1.5">
              <select
                value={role}
                onChange={(e) => changeRole(e.target.value)}
                aria-label="Role"
                className="h-8 min-w-0 flex-1 cursor-pointer rounded-md border border-input bg-card px-2 text-[12.5px] font-medium shadow-card"
              >
                <option value="adjuster">Adjuster (full PII)</option>
                <option value="supervisor">Supervisor (admin)</option>
                <option value="auditor">Auditor (PII masked)</option>
              </select>
              <button
                onClick={toggleTheme}
                aria-label="Toggle theme"
                className="grid h-8 w-8 shrink-0 cursor-pointer place-items-center rounded-md border border-input bg-card text-muted-foreground shadow-card transition hover:text-foreground"
              >
                {dark ? <Sun size={14} /> : <Moon size={14} />}
              </button>
            </div>
          </div>
        </div>
       </div>
      </aside>

      <div className="min-w-0 flex-1">
        {active?.is_stand_in ? (
          <div className="flex items-center gap-2 border-b border-amber-500/25 bg-amber-500/[0.08] px-8 py-2 text-[12.5px] text-amber-900 dark:text-amber-200">
            <FlaskRound size={14} className="shrink-0" />
            <span>
              <b className="font-semibold">Stand-in claims system.</b> Claims are sent to a local mock that follows Guidewire&apos;s published
              ClaimCenter Cloud API shapes. It is not Guidewire software. Connect your real ClaimCenter in Settings.
            </span>
          </div>
        ) : null}
        <main className="rise mx-auto w-full max-w-[1400px] px-8 pb-16 pt-7 max-md:px-4">{children}</main>
      </div>
    </div>
  );
}
