import { useEffect, useState } from "react";
import { api } from "../lib/api";

export default function FilesPage() {
  const [path, setPath] = useState<string>(() => {
    // Best-effort default: Documents.
    return localStorage.getItem("cheryy.lastPath") || "";
  });
  const [entries, setEntries] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = async (p: string) => {
    if (!p) {
      setError("Enter a path (e.g. C:\\Users\\<you>\\Documents).");
      setEntries([]);
      return;
    }
    try {
      const r = await api.filesList(p, false);
      setEntries(r.entries || []);
      setError(r.error || null);
      localStorage.setItem("cheryy.lastPath", p);
      setPath(p);
    } catch (e: any) {
      setError(e?.message || String(e));
    }
  };

  useEffect(() => { if (path) load(path); }, []);

  return (
    <div style={{ padding: 22, overflowY: "auto" }}>
      <h2 style={{ marginTop: 0 }}>Files</h2>
      <div className="row" style={{ gap: 8 }}>
        <input value={path} onChange={(e) => setPath(e.target.value)} placeholder="C:\Users\…\Documents" />
        <button className="primary" onClick={() => load(path)}>Open</button>
      </div>
      <p className="muted" style={{ marginTop: 8 }}>
        CHERYY never deletes files. All operations are safe (list, read, create, edit, copy, move, rename).
      </p>
      {error && <div style={{ marginTop: 8, color: "var(--err)" }}>{error}</div>}
      <table style={{ width: "100%", marginTop: 12, borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ textAlign: "left", color: "var(--fg-3)", fontSize: 12 }}>
            <th style={{ padding: 6 }}>Name</th>
            <th style={{ padding: 6 }}>Type</th>
            <th style={{ padding: 6 }}>Size</th>
            <th style={{ padding: 6 }}>Modified</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((e) => (
            <tr key={e.path} style={{ borderTop: "1px solid var(--line)", cursor: e.type === "dir" ? "pointer" : "default" }}
                onDoubleClick={() => e.type === "dir" && load(e.path)}>
              <td style={{ padding: 8 }}>{e.type === "dir" ? "📁 " : "📄 "}{e.name}</td>
              <td style={{ padding: 8, color: "var(--fg-3)" }}>{e.type}</td>
              <td style={{ padding: 8, color: "var(--fg-3)" }}>{e.type === "dir" ? "—" : formatBytes(e.size)}</td>
              <td style={{ padding: 8, color: "var(--fg-3)" }}>{e.modified || ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function formatBytes(n: number): string {
  if (!n) return "0";
  const u = ["B", "KB", "MB", "GB"];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(i === 0 ? 0 : 1)} ${u[i]}`;
}