import { useEffect, useState } from "react";
import { useApp } from "./store/app";
import Sidebar from "./components/Sidebar";
import FirstRun from "./components/FirstRun";
import TopBar from "./components/TopBar";
import VoiceBar from "./components/VoiceBar";
import HomePage from "./pages/Home";
import ChatPage from "./pages/Chat";
import TasksPage from "./pages/Tasks";
import LivePCPage from "./pages/LivePC";
import FilesPage from "./pages/Files";
import MemoryPage from "./pages/Memory";
import SkillsPage from "./pages/Skills";
import ActivityPage from "./pages/Activity";
import SettingsPage from "./pages/Settings";
import { api, openEventsWS, openVoiceWS } from "./lib/api";

export default function App() {
  const page = useApp((s) => s.page);
  const setupDone = useApp((s) => s.setupDone);
  const setActivity = useApp((s) => s.setActivity);
  const pushActivity = useApp((s) => s.pushActivity);
  const setVoiceState = useApp((s) => s.setVoiceState);

  // Initial activity load + live WS
  useEffect(() => {
    let ws: WebSocket | undefined;
    api.activity(200).then((r) => setActivity(r.events)).catch(() => {});
    try {
      ws = openEventsWS((msg) => {
        if (msg.type === "event" && msg.event) {
          pushActivity(msg.event);
        }
      });
    } catch {}
    return () => { ws?.close(); };
  }, [setActivity, pushActivity]);

  // Voice WS (open lazily; first connect on demand)
  useEffect(() => {
    let ws: WebSocket | undefined;
    try {
      ws = openVoiceWS((msg) => {
        if (msg.type === "voice_state") {
          const s = msg.state;
          if (s === "listening" || s === "speaking" || s === "ready_text_fallback" || s === "interrupted" || s === "stopped") {
            setVoiceState(s === "ready_text_fallback" ? "idle" : (s as any));
          } else if (s === "tts_error") {
            setVoiceState("error");
          }
        }
      });
      ws.onopen = () => ws?.send(JSON.stringify({ kind: "noop" }));
    } catch {}
    return () => { ws?.close(); };
  }, [setVoiceState]);

  if (!setupDone) return <FirstRun />;

  return (
    <div className="app">
      <TopBar />
      <Sidebar />
      <main className="main">
        {page === "home" && <HomePage />}
        {page === "chat" && <ChatPage />}
        {page === "tasks" && <TasksPage />}
        {page === "livepc" && <LivePCPage />}
        {page === "files" && <FilesPage />}
        {page === "memory" && <MemoryPage />}
        {page === "skills" && <SkillsPage />}
        {page === "activity" && <ActivityPage />}
        {page === "settings" && <SettingsPage />}
      </main>
      <aside className="right-panel">
        <h3>Live Task</h3>
        <TasksPage.Sidebar />
        <h3 style={{ marginTop: 18 }}>Recent Activity</h3>
        <ActivityPage.Sidebar />
      </aside>
      <VoiceBar />
    </div>
  );
}