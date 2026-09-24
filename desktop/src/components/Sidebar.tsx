import { useApp, Page } from "../store/app";
import {
  Home,
  MessageCircle,
  ListChecks,
  MonitorSmartphone,
  Folder,
  Brain,
  Sparkles,
  Activity,
  Settings as SettingsIcon,
} from "lucide-react";

const NAV: { id: Page; label: string; icon: any }[] = [
  { id: "home", label: "Home", icon: Home },
  { id: "chat", label: "Chat", icon: MessageCircle },
  { id: "tasks", label: "Tasks", icon: ListChecks },
  { id: "livepc", label: "Live PC", icon: MonitorSmartphone },
  { id: "files", label: "Files", icon: Folder },
  { id: "memory", label: "Memory", icon: Brain },
  { id: "skills", label: "Skills", icon: Sparkles },
  { id: "activity", label: "Activity", icon: Activity },
  { id: "settings", label: "Settings", icon: SettingsIcon },
];

export default function Sidebar() {
  const page = useApp((s) => s.page);
  const setPage = useApp((s) => s.setPage);

  return (
    <aside className="sidebar">
      <div style={{ padding: "6px 8px 18px", fontWeight: 700, letterSpacing: 2, color: "var(--fg-2)" }}>
        CHERYY
      </div>
      {NAV.map((n) => {
        const Icon = n.icon;
        return (
          <div
            key={n.id}
            className={`nav-item ${page === n.id ? "active" : ""}`}
            onClick={() => setPage(n.id)}
            data-testid={`nav-${n.id}`}
          >
            <Icon size={18} />
            <span>{n.label}</span>
          </div>
        );
      })}
    </aside>
  );
}