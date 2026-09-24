import { useEffect, useState } from "react";
import { api } from "../lib/api";

export default function SkillsPage() {
  const [providers, setProviders] = useState<any>(null);

  useEffect(() => {
    api.status().then(setProviders).catch(() => setProviders(null));
  }, []);

  const builtIn = [
    { name: "Office", desc: "DOCX, PPTX, XLSX, PDF with strict quality control.", tools: ["office.create_docx", "office.create_pptx", "office.create_xlsx", "office.create_pdf"] },
    { name: "Browser", desc: "Playwright DOM-first automation.", tools: ["browser.open", "browser.click", "browser.type", "browser.upload", "browser.screenshot"] },
    { name: "Windows", desc: "Mouse, keyboard, UI tree, multi-monitor.", tools: ["computer.*"] },
    { name: "Filesystem", desc: "List, read, create, edit, copy, move, rename — never delete.", tools: ["filesystem.*"] },
    { name: "Content", desc: "Blogs, SEO, emails, summaries.", tools: ["content.*"] },
    { name: "Publishing", desc: "WordPress + generic API.", tools: ["publisher.*"] },
    { name: "Image", desc: "Generate, resize, convert.", tools: ["image.*"] },
    { name: "Voice", desc: "Live voice + TTS + STT + barge-in.", tools: [] },
    { name: "Memory", desc: "Six-category persistent memory with relevance retrieval.", tools: [] },
  ];

  return (
    <div style={{ padding: 22, overflowY: "auto" }}>
      <h2 style={{ marginTop: 0 }}>Skills</h2>
      <p className="muted">Modular bundles of tools. Each skill can be enabled or disabled individually.</p>
      <div className="grid-2">
        {builtIn.map((s) => (
          <div key={s.name} className="card">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <h3 style={{ margin: 0 }}>{s.name}</h3>
              <span className="tag">enabled</span>
            </div>
            <p className="muted" style={{ marginTop: 6 }}>{s.desc}</p>
            <div className="row" style={{ flexWrap: "wrap", gap: 6 }}>
              {s.tools.map((t) => <span key={t} className="kbd">{t}</span>)}
            </div>
          </div>
        ))}
      </div>

      <h3 style={{ marginTop: 24 }}>AI provider capability</h3>
      {providers && (
        <div className="card">
          {Object.entries(providers.default_models || {}).map(([k, v]) => (
            <div key={k} className="kv-row">
              <span className="k">{k}</span>
              <span className="v">{String(v || "—")}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}