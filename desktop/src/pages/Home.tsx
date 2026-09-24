import { useApp } from "../store/app";
import { useEffect, useState } from "react";
import { api } from "../lib/api";

export default function HomePage() {
  const setPage = useApp((s) => s.setPage);
  const [status, setStatus] = useState<any>(null);

  useEffect(() => {
    api.status().then(setStatus).catch(() => setStatus(null));
  }, []);

  const caps = status?.default_models || {};
  const quota = status?.quota?.gemini;

  return (
    <div style={{ padding: 30, overflowY: "auto" }}>
      <h1 style={{ margin: "0 0 8px", fontSize: 28 }}>Welcome to CHERYY</h1>
      <p className="muted" style={{ maxWidth: 720 }}>
        Your personal autonomous AI office assistant. Speak or type — CHERYY will plan, act,
        verify, and report. It can write documents, control apps, browse the web, manage files,
        and publish, without ever deleting anything on your PC.
      </p>

      <div className="grid-2" style={{ marginTop: 24, maxWidth: 920 }}>
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Try asking CHERYY</h3>
          <ul style={{ paddingLeft: 18, color: "var(--fg-2)" }}>
            <li>"Create a 10-slide PowerPoint about AI in digital marketing."</li>
            <li>"Write a professional blog post about remote work and save it as DOCX."</li>
            <li>"Summarise the PDF in my Downloads folder."</li>
            <li>"Open Chrome and find the top 5 trends in generative AI."</li>
            <li>"Create a weekly Excel report from this CSV."</li>
          </ul>
        </div>
        <div className="card">
          <h3 style={{ marginTop: 0 }}>AI Status</h3>
          {quota && (
            <>
              <div className="kv-row"><span className="k">Provider</span><span className="v">gemini</span></div>
              <div className="kv-row"><span className="k">Requests today</span><span className="v">{quota.requests_today}</span></div>
              <div className="kv-row"><span className="k">Quota</span><span className="v">{quota.quota_exhausted ? "exhausted" : "ok"}</span></div>
              <div className="kv-row"><span className="k">Last success</span><span className="v">{quota.last_success || "—"}</span></div>
            </>
          )}
          <h3 style={{ marginTop: 16 }}>Default Models</h3>
          {Object.entries(caps).map(([k, v]) => (
            <div key={k} className="kv-row"><span className="k">{k}</span><span className="v">{String(v || "—")}</span></div>
          ))}
        </div>
      </div>

      <button className="primary" style={{ marginTop: 24 }} onClick={() => setPage("chat")}>
        Start a conversation →
      </button>
    </div>
  );
}