import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Search, Plus, Trash } from "lucide-react";

const CATEGORIES = ["profile", "preference", "semantic", "episodic", "procedural", "task"];

export default function MemoryPage() {
  const [items, setItems] = useState<any[]>([]);
  const [category, setCategory] = useState<string>("");
  const [query, setQuery] = useState("");
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState({ category: "preference", content: "" });

  const load = async () => {
    const list = query.trim()
      ? await api.memorySearch(query, category ? [category] : undefined)
      : await api.memoryList(category || undefined);
    setItems(list);
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [category]);

  return (
    <div style={{ padding: 22, overflowY: "auto" }}>
      <h2 style={{ marginTop: 0 }}>Memory</h2>
      <p className="muted">CHERYY remembers facts you tell it and retrieves only the relevant ones — it never injects the full database into a prompt.</p>
      <div className="row" style={{ gap: 8, marginBottom: 10 }}>
        <select value={category} onChange={(e) => setCategory(e.target.value)}
                style={{ background: "var(--bg-2)", border: "1px solid var(--line)", color: "var(--fg)", borderRadius: 8, padding: 8 }}>
          <option value="">All categories</option>
          {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <input placeholder="Search memory…" value={query} onChange={(e) => setQuery(e.target.value)} />
        <button onClick={load}><Search size={14} /></button>
        <button className="primary" onClick={() => setAdding(true)}><Plus size={14} /> Add</button>
      </div>

      {adding && (
        <div className="card" style={{ marginBottom: 12 }}>
          <div className="row" style={{ gap: 8, marginBottom: 8 }}>
            <select value={draft.category} onChange={(e) => setDraft({ ...draft, category: e.target.value })}
                    style={{ background: "var(--bg-2)", color: "var(--fg)", border: "1px solid var(--line)", borderRadius: 8, padding: 8 }}>
              {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
          <textarea rows={3} value={draft.content} onChange={(e) => setDraft({ ...draft, content: e.target.value })} />
          <div className="row" style={{ justifyContent: "flex-end", gap: 8, marginTop: 8 }}>
            <button onClick={() => setAdding(false)}>Cancel</button>
            <button className="primary" disabled={!draft.content} onClick={async () => {
              await api.memoryAdd(draft);
              setAdding(false);
              setDraft({ category: "preference", content: "" });
              load();
            }}>Save</button>
          </div>
        </div>
      )}

      {items.length === 0 && <p className="muted">No memory yet.</p>}
      {items.map((it) => (
        <div key={it.id} className="card" style={{ marginBottom: 8 }}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <div>
              <span className="tag">{it.category}</span>{" "}
              <span className="muted" style={{ fontSize: 11 }}>
                importance {it.importance.toFixed(2)} • used {it.use_count}× • {it.updated_at}
              </span>
            </div>
            <button className="danger" onClick={async () => { await api.memoryForget(it.id); load(); }}>
              <Trash size={12} />
            </button>
          </div>
          <div style={{ marginTop: 6, userSelect: "text" }}>{it.content}</div>
        </div>
      ))}
    </div>
  );
}