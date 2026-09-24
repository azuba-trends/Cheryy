import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Camera } from "lucide-react";

export default function LivePCPage() {
  const [monitors, setMonitors] = useState<any[]>([]);
  const [apps, setApps] = useState<any[]>([]);
  const [screenshot, setScreenshot] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = async () => {
    try {
      const m = await api.monitors();
      setMonitors(m.monitors);
      const a = await api.runningApps();
      setApps(a.apps);
    } catch {}
  };

  const snap = async () => {
    setBusy(true);
    try {
      const r = await api.filesAction("computer.get_screen", {});
      if (r?.data?.png_b64) setScreenshot(r.data.png_b64);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 5000);
    return () => clearInterval(id);
  }, []);

  return (
    <div style={{ padding: 22, overflowY: "auto" }}>
      <h2 style={{ marginTop: 0 }}>Live PC</h2>
      <div className="grid-2">
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Monitors</h3>
          {monitors.length === 0 && <p className="muted">Detecting…</p>}
          {monitors.map((m) => (
            <div key={m.index} className="kv-row">
              <span className="k">{m.is_primary ? "Primary" : `#${m.index}`}</span>
              <span className="v">{m.width}×{m.height} @ {(m.scale * 100).toFixed(0)}%</span>
            </div>
          ))}
        </div>
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Running applications</h3>
          {apps.length === 0 && <p className="muted">Scanning…</p>}
          {apps.slice(0, 20).map((a) => (
            <div key={a.pid} className="kv-row">
              <span className="k">{a.name}</span>
              <span className="v" style={{ maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.title}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h3 style={{ margin: 0 }}>Desktop preview</h3>
          <button className="primary" disabled={busy} onClick={snap}>
            <Camera size={14} /> Capture
          </button>
        </div>
        <div className="screen-preview" style={{ marginTop: 10 }}>
          {screenshot
            ? <img src={`data:image/png;base64,${screenshot}`} style={{ maxWidth: "100%" }} />
            : <span className="muted">Click Capture to take a snapshot.</span>}
        </div>
        <p className="muted" style={{ fontSize: 11, marginTop: 8 }}>
          CHERYY only captures the screen when needed for a task. Nothing is recorded continuously.
        </p>
      </div>
    </div>
  );
}