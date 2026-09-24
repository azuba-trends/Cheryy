import { useEffect, useState } from "react";
import { useApp } from "../store/app";
import { api } from "../lib/api";
import { Pause, Play, Square, RefreshCw } from "lucide-react";

export default function TasksPage() {
  const tasks = useApp((s) => s.tasks);
  const refreshTasks = useApp((s) => s.refreshTasks);

  useEffect(() => {
    refreshTasks();
    const id = setInterval(refreshTasks, 2000);
    return () => clearInterval(id);
  }, [refreshTasks]);

  return (
    <div style={{ padding: 22, overflowY: "auto" }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2 style={{ margin: 0 }}>Tasks</h2>
        <button onClick={refreshTasks}><RefreshCw size={14} /></button>
      </div>
      {tasks.length === 0 && <p className="muted">No tasks yet. Send a request in Chat to create one.</p>}
      {tasks.map((t) => (
        <div key={t.id} className="card" style={{ marginTop: 10 }}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <div>
              <div style={{ fontWeight: 600 }}>#{t.id} {t.user_request}</div>
              <div className="muted" style={{ fontSize: 12 }}>{t.created_at} • status <b>{t.status}</b></div>
            </div>
            <div className="row" style={{ gap: 6 }}>
              {["PLANNING", "RUNNING", "WAITING", "VERIFYING", "RECOVERING"].includes(t.status) && (
                <button onClick={() => api.taskPause(t.id).then(refreshTasks)} title="Pause"><Pause size={14} /></button>
              )}
              {t.status === "PAUSED" && (
                <button onClick={() => api.taskResume(t.id).then(refreshTasks)} title="Resume"><Play size={14} /></button>
              )}
              {["PLANNING", "RUNNING", "WAITING", "VERIFYING", "RECOVERING", "PAUSED"].includes(t.status) && (
                <button className="danger" onClick={() => api.taskCancel(t.id).then(refreshTasks)} title="Cancel"><Square size={14} /></button>
              )}
            </div>
          </div>
          <div className="progress" style={{ marginTop: 8 }}>
            <div style={{ width: `${Math.round(t.progress * 100)}%` }} />
          </div>
          {t.observations?.length > 0 && (
            <div style={{ marginTop: 10, fontSize: 12, color: "var(--fg-3)" }}>
              {t.observations.slice(-5).map((o: string, i: number) => <div key={i}>· {o}</div>)}
            </div>
          )}
          {t.error && <div style={{ marginTop: 6, color: "var(--err)" }}>{t.error}</div>}
        </div>
      ))}
    </div>
  );
}

TasksPage.Sidebar = function Sidebar() {
  const tasks = useApp((s) => s.tasks);
  const active = tasks.find((t) => ["PLANNING", "RUNNING", "WAITING", "VERIFYING", "RECOVERING"].includes(t.status));
  if (!active) return <div className="muted">No active task.</div>;
  return (
    <div>
      <div className="kv-row"><span className="k">Task</span><span className="v">#{active.id}</span></div>
      <div className="kv-row"><span className="k">Status</span><span className="v">{active.status}</span></div>
      <div className="kv-row"><span className="k">Step</span><span className="v">{active.current_step}</span></div>
      <div className="kv-row"><span className="k">Progress</span><span className="v">{Math.round(active.progress * 100)}%</span></div>
      <div className="kv-row"><span className="k">Request</span><span className="v" style={{ maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{active.user_request}</span></div>
    </div>
  );
};