import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useApp } from "../store/app";

export default function SettingsPage() {
  const setToast = useApp((s) => s.setToast);
  const [key, setKey] = useState("");
  const [preview, setPreview] = useState<string | null>(null);
  const [status, setStatus] = useState<any>(null);
  const [caps, setCaps] = useState<any>(null);
  const [repairing, setRepairing] = useState(false);

  const load = async () => {
    const s = await api.status();
    setStatus(s);
    setPreview(s?.preview_key || null);
  };
  const caps_load = async () => {
    const r = await api.selfTest();
    setCaps(r);
  };

  useEffect(() => { load(); caps_load(); }, []);

  const updateKey = async () => {
    if (!key.trim()) return;
    await api.applyKey(key.trim());
    setToast("API key updated.");
    setKey("");
    load();
  };

  const repair = async () => {
    setRepairing(true);
    try {
      const r = await api.diagRepair();
      setToast(`Repair attempted: ${r.actions?.length ?? 0} actions.`);
      caps_load();
    } finally {
      setRepairing(false);
    }
  };

  return (
    <div style={{ padding: 22, overflowY: "auto", maxWidth: 820 }}>
      <h2 style={{ marginTop: 0 }}>Settings</h2>

      <div className="card" style={{ marginBottom: 14 }}>
        <h3 style={{ marginTop: 0 }}>Gemini API key</h3>
        <p className="muted" style={{ fontSize: 12 }}>
          Stored in Windows Credential Manager (encrypted when keyring is unavailable). Never written to logs.
        </p>
        <div className="row" style={{ marginBottom: 8 }}>
          <div className="muted">Current</div>
          <input value={preview || "(not set)"} disabled />
        </div>
        <input
          type="password"
          placeholder="Paste new Gemini API key…"
          value={key}
          onChange={(e) => setKey(e.target.value)}
        />
        <div className="row" style={{ justifyContent: "flex-end", marginTop: 10 }}>
          <button className="primary" disabled={!key.trim()} onClick={updateKey}>Update API key</button>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 14 }}>
        <h3 style={{ marginTop: 0 }}>AI Status</h3>
        {status?.providers?.map((p: string) => (
          <div key={p} className="kv-row">
            <span className="k">{p}</span>
            <span className="v">
              {status.quota?.[p]?.requests_today ?? 0} reqs •
              quota: {status.quota?.[p]?.quota_exhausted ? "exhausted" : "ok"}
            </span>
          </div>
        ))}
        <h4 style={{ marginTop: 12 }}>Default models</h4>
        {status && Object.entries(status.default_models || {}).map(([k, v]) => (
          <div key={k} className="kv-row"><span className="k">{k}</span><span className="v">{String(v || "—")}</span></div>
        ))}
      </div>

      <div className="card" style={{ marginBottom: 14 }}>
        <h3 style={{ marginTop: 0 }}>Capabilities</h3>
        {caps?.capabilities && Object.entries(caps.capabilities).map(([k, v]: any) => (
          <div key={k} className="kv-row"><span className="k">{k}</span><span className="v">{v ? "ok" : "unavailable"}</span></div>
        ))}
      </div>

      <div className="card" style={{ marginBottom: 14 }}>
        <h3 style={{ marginTop: 0 }}>Diagnostics</h3>
        <p className="muted" style={{ fontSize: 12 }}>
          Auto-repair never deletes user files. It re-creates cache directories, ensures the database, reinstalls Playwright browsers, and resets provider state.
        </p>
        <button className="primary" disabled={repairing} onClick={repair}>
          {repairing ? "Repairing…" : "Run safe repair"}
        </button>
      </div>

      <div className="card">
        <h3 style={{ marginTop: 0 }}>Privacy</h3>
        <p className="muted">CHERYY captures the screen only when needed for a task, never continuously.</p>
        <p className="muted">Your conversations and memory are stored locally only.</p>
      </div>
    </div>
  );
}