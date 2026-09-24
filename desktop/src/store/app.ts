import { create } from "zustand";
import { api } from "../lib/api";

export type Page = "home" | "chat" | "tasks" | "livepc" | "files" | "memory" | "skills" | "activity" | "settings";

export interface ChatMessage {
  id: number;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  ts: string;
  voice_text?: string | null;
  task_id?: number | null;
}

export interface ActivityEvent {
  ts: string;
  level: string;
  message: string;
  source: string;
}

export interface TaskItem {
  id: number;
  user_request: string;
  status: string;
  progress: number;
  current_step: number;
  observations: string[];
  result?: string | null;
  error?: string | null;
  created_at: string;
  updated_at: string;
}

interface AppState {
  page: Page;
  setPage: (p: Page) => void;

  setupDone: boolean;
  setSetupDone: (v: boolean) => void;

  conversationId: number | null;
  setConversationId: (id: number | null) => void;

  messages: ChatMessage[];
  pushMessage: (m: ChatMessage) => void;
  appendAssistantDelta: (id: number, delta: string) => void;
  resetConversation: () => void;

  tasks: TaskItem[];
  refreshTasks: () => Promise<void>;
  updateTask: (t: TaskItem) => void;

  activity: ActivityEvent[];
  setActivity: (a: ActivityEvent[]) => void;
  pushActivity: (a: ActivityEvent) => void;

  voiceState: "idle" | "listening" | "thinking" | "working" | "speaking" | "verifying" | "error";
  setVoiceState: (s: AppState["voiceState"]) => void;

  toast: string | null;
  setToast: (t: string | null) => void;
}

export const useApp = create<AppState>((set, get) => ({
  page: "chat",
  setPage: (p) => set({ page: p }),

  setupDone: false,
  setSetupDone: (v) => set({ setupDone: v }),

  conversationId: null,
  setConversationId: (id) => set({ conversationId: id }),

  messages: [],
  pushMessage: (m) => set({ messages: [...get().messages, m] }),
  appendAssistantDelta: (id, delta) => {
    const msgs = get().messages.map((m) => (m.id === id ? { ...m, content: m.content + delta } : m));
    set({ messages: msgs });
  },
  resetConversation: () => set({ messages: [], conversationId: null }),

  tasks: [],
  refreshTasks: async () => {
    try {
      const t = await api.tasks();
      set({ tasks: t as TaskItem[] });
    } catch (e) {
      console.error(e);
    }
  },
  updateTask: (t) => set({ tasks: get().tasks.map((x) => (x.id === t.id ? t : x)) }),

  activity: [],
  setActivity: (a) => set({ activity: a }),
  pushActivity: (a) => set({ activity: [a, ...get().activity].slice(0, 300) }),

  voiceState: "idle",
  setVoiceState: (s) => set({ voiceState: s }),

  toast: null,
  setToast: (t) => {
    set({ toast: t });
    if (t) setTimeout(() => set({ toast: null }), 3500);
  },
}));