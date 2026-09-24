import { useApp } from "../store/app";
import { api } from "../lib/api";
import { useEffect, useState } from "react";

export default function TopBar() {
  const voiceState = useApp((s) => s.voiceState);
  const setPage = useApp((s) => s.setPage);
  const [providers, setProviders] = useState<any>(null);
  const [taskActive, setTaskActive] = useState<any>(null);

  useEffect(() => {
    const tick = async () => {
      try {
        const s = await api.providerStatus();
        setProviders(s);
        const tasks = await api.tasks();
        const active = tasks.find((t: any) => ["PLANNING", "RUNNING", "WAITING", "VERIFYING", "RECOVERING"].includes(t.status));
        setTaskActive(active || null);
      } catch {}
    };
    tick();
    const id = setInterval(tick, 4000);
    return () => clearInterval(id);
  }, []);

  const gemini = providers?.quota?.gemini;
  const dotClass = !providers ? "" : gemini?.quota_exhausted ? "err" : gemini?.rate_limited > 0 ? "warn" : "";

  return (
    <header className="app-header">
      <div className="brand">CHERYY</div>
      <div className="status">
        {taskActive && (
          <span className="pill" style={{ background: "var(--bg-3)", padding: "4px 10px", borderRadius: 999, color: "var(--fg-2)", fontSize: 11 }}>
            {taskActive.status}: {taskActive.user_request.slice(0, 40)}{taskActive.user_request.length > 40 ? "…" : ""}
          </span>
        )}
        <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span className={`dot ${dotClass}`} /> Gemini
        </span>
        <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span className="dot" /> Voice: {voiceState}
        </span>
        <button className="ghost" onClick={() => setPage("settings")}>Settings</button>
      </div>
    </header>
  );
}