import { useApp } from "../store/app";

export default function ActivityPage() {
  const activity = useApp((s) => s.activity);
  return (
    <div style={{ padding: 22, overflowY: "auto" }}>
      <h2 style={{ marginTop: 0 }}>Activity log</h2>
      <p className="muted">The live, human-readable record of what CHERYY is doing. The newest events appear at the top.</p>
      {activity.length === 0 && <p className="muted">No activity yet.</p>}
      <div>
        {activity.map((e, i) => (
          <div key={i} className="activity-item">
            <span className="ts">{e.ts?.slice(11, 19) || ""}</span>
            <span style={{ flex: 1 }}>{e.message}</span>
            <span className="tag">{e.source}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

ActivityPage.Sidebar = function Sidebar() {
  const activity = useApp((s) => s.activity);
  const items = activity.slice(0, 8);
  if (items.length === 0) return <div className="muted">No recent activity.</div>;
  return (
    <div>
      {items.map((e, i) => (
        <div key={i} className="activity-item">
          <span className="ts">{e.ts?.slice(11, 19) || ""}</span>
          <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{e.message}</span>
        </div>
      ))}
    </div>
  );
};