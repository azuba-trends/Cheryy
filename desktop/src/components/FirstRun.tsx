import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useApp } from "../store/app";

export default function FirstRun() {
  const setSetupDone = useApp((s) => s.setSetupDone);
  const setToast = useApp((s) => s.setToast);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<string[]>([]);
  const [result, setResult] = useState<any>(null);

  // Preload existing status (in case the user already added a key)
  useEffect(() => {
    api.status().then((s) => {
      if (s?.providers?.gemini && !s?.providers?.gemini?.quota_exhausted) {
        // Looks like there's a working provider; auto-finish.
        setProgress(["Found existing AI configuration. Verifying…"]);
        api.selfTest().then(() => setSetupDone(true));
      }
    }).catch(() => {/* no backend yet */});
  }, [setSetupDone]);

  const validate = async () => {
    if (!key.trim()) return;
    setBusy(true);
    setProgress(["Validating Gemini API key…"]);
    try {
      const r = await api.validateKey(key.trim());
      if (!r.ok) {
        setProgress([...progress, `❌ ${r.category || "error"}: ${r.message}`]);
        setBusy(false);
        return;
      }
      setProgress([
        ...progress,
        `✅ Key accepted (${r.preview}). ${r.models ?? "?"} models available.`,
      ]);
      setResult(r);
    } catch (e: any) {
      setProgress([...progress, `❌ network error: ${e?.message || e}`]);
    } finally {
      setBusy(false);
    }
  };

  const apply = async () => {
    setBusy(true);
    try {
      setProgress([...progress, "Applying configuration…"]);
      await api.applyKey(key.trim());
      setProgress([...progress, "Running self-test…"]);
      const r = await api.selfTest();
      setProgress([
        ...progress,
        "✅ Setup complete.",
        ...Object.entries(r.capabilities || {}).map(([k, v]) => `  • ${k}: ${v ? "ok" : "unavailable"}`),
      ]);
      setToast("CHERYY is ready.");
      setTimeout(() => setSetupDone(true), 700);
    } catch (e: any) {
      setProgress([...progress, `❌ ${e?.message || e}`]);
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop">
      <div className="modal">
        <h2>Welcome to CHERYY</h2>
        <p>Your personal AI office assistant. Add your Gemini API key to begin.</p>
        <input
          type="password"
          autoFocus
          placeholder="AIza…"
          value={key}
          onChange={(e) => setKey(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !result && validate()}
        />
        <div style={{ display: "flex", gap: 8, marginTop: 14, justifyContent: "flex-end" }}>
          {!result && (
            <button className="primary" disabled={busy || !key} onClick={validate}>
              VALIDATE API KEY
            </button>
          )}
          {result?.ok && (
            <button className="primary" disabled={busy} onClick={apply}>
              CONTINUE
            </button>
          )}
        </div>
        {progress.length > 0 && (
          <div style={{ marginTop: 18, fontSize: 12, color: "var(--fg-2)", maxHeight: 240, overflowY: "auto" }}>
            {progress.map((p, i) => (
              <div key={i} style={{ padding: "2px 0" }}>{p}</div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}