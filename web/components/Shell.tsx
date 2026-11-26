"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useApi } from "@/lib/api";

const NAV = [
  { href: "/", label: "Dashboard" },
  { href: "/intake", label: "Intake" },
  { href: "/review", label: "Review queue", count: true },
  { href: "/claims", label: "All claims" },
  { href: "/evals", label: "Evals" },
  { href: "/audit", label: "Audit log" },
  { href: "/settings", label: "Settings" },
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
  const { data: stats } = useApi<Stats>("/stats", 5000);
  const { data: integ } = useApi<Integrations>("/integrations", 15000);
  useEffect(() => setRole(getCookie("fnol_role") || "adjuster"), []);
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

  return (
    <div className="shell">
      <aside className="side">
        <div className="brand">
          <div className="logo">F</div>
          <div><b>FNOL Claims Desk</b><span>First Notice of Loss intake</span></div>
        </div>
        <nav className="nav">
          {NAV.map((n) => (
            <Link key={n.href} href={n.href} className={(n.href === "/" ? path === "/" : path.startsWith(n.href)) ? "active" : ""}>
              {n.label}
              {n.count && pending > 0 ? <span className="count">{pending}</span> : null}
            </Link>
          ))}
        </nav>
        <div className="foot">
          Signed in role
          <select value={role} onChange={(e) => changeRole(e.target.value)} aria-label="Role">
            <option value="adjuster">Adjuster (full PII)</option>
            <option value="supervisor">Supervisor (admin)</option>
            <option value="auditor">Auditor (PII masked)</option>
          </select>
          <div style={{ marginTop: 10 }}>
            Claims system:<br />
            <b style={{ color: "#fff" }}>{active ? active.name : "none active"}</b>
          </div>
        </div>
      </aside>
      <main className="main">
        {active?.is_stand_in ? (
          <div className="banner">
            <b>Stand-in claims system.</b> Claims are sent to a local mock that follows Guidewire&apos;s published
            ClaimCenter Cloud API shapes. It is not Guidewire software. Connect your real ClaimCenter in Settings.
          </div>
        ) : null}
        {children}
      </main>
    </div>
  );
}
