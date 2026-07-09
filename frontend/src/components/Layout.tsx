import { NavLink, Outlet } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { systemApi } from "../api/system";

const NAV_ITEMS: { to: string; label: string }[] = [
  { to: "/environment", label: "기상 환경" },
  { to: "/growth", label: "생육 데이터" },
  { to: "/control", label: "온실 제어" },
  { to: "/chat", label: "AI 상담" },
  { to: "/diary", label: "영농일지" },
  { to: "/reports", label: "리포트" },
];

export default function Layout() {
  const { data: health } = useQuery({
    queryKey: ["system-health"],
    queryFn: systemApi.health,
    refetchInterval: 60_000,
  });

  return (
    <div style={{ minHeight: "100%", display: "flex", flexDirection: "column" }}>
      <header
        style={{
          position: "sticky",
          top: 0,
          zIndex: 50,
          background: "rgba(255, 255, 255, 0.78)",
          borderBottom: "1px solid rgba(120, 113, 108, 0.18)",
          padding: "0 24px",
          backdropFilter: "blur(20px)",
          boxShadow: "0 10px 30px rgba(41, 37, 36, 0.06)",
        }}
      >
        <div
          style={{
            maxWidth: 1180,
            margin: "0 auto",
            display: "flex",
            alignItems: "center",
            gap: 32,
            height: 68,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 10, whiteSpace: "nowrap" }}>
            <span
              style={{
                width: 34,
                height: 34,
                borderRadius: 12,
                display: "grid",
                placeItems: "center",
                background: "linear-gradient(135deg, #065f46, #10b981)",
                color: "white",
                boxShadow: "0 10px 24px rgba(4, 120, 87, 0.22)",
                fontWeight: 900,
              }}
            >
              G
            </span>
            <div>
              <strong style={{ fontSize: 22, color: "var(--color-primary-dark)", display: "block", lineHeight: 1.1 }}>
                Greenhouse AI
              </strong>
              <span style={{ fontSize: 17, color: "var(--color-text-muted)", fontWeight: 700 }}>
                토마토 의사결정 지원
              </span>
            </div>
          </div>
          <nav style={{ display: "flex", gap: 4, flex: 1, overflowX: "auto" }}>
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                style={({ isActive }) => ({
                  padding: "8px 14px",
                  borderRadius: 999,
                  fontSize: 20,
                  fontWeight: 800,
                  whiteSpace: "nowrap",
                  color: isActive ? "white" : "var(--color-text-muted)",
                  background: isActive ? "linear-gradient(135deg, #047857, #10b981)" : "transparent",
                  textDecoration: "none",
                  boxShadow: isActive ? "0 10px 24px rgba(4, 120, 87, 0.18)" : "none",
                })}
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <span
            title={health?.ollama_reachable ? "Ollama 연결됨" : "Ollama 연결 안 됨"}
            style={{
              width: 8,
              height: 8,
              borderRadius: "50%",
              background: health?.ollama_reachable ? "var(--color-good)" : "var(--color-bad)",
              flexShrink: 0,
            }}
          />
        </div>
      </header>
      <main style={{ flex: 1, maxWidth: 1180, width: "100%", margin: "0 auto", padding: "30px 24px 44px" }}>
        <Outlet />
      </main>
    </div>
  );
}
