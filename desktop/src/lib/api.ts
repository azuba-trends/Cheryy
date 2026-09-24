// CHERYY API client. Uses fetch against the local backend; falls back to Tauri
// HTTP if available (so it works inside the native webview as well as in dev).

const BASE_HTTP = "/api"; // proxied to http://127.0.0.1:7480 in dev
const TAURI = typeof window !== "undefined" && (window as any).__TAURI__;

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_HTTP}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!res.ok) throw new Error(`HTTP ${res.status} ${res.statusText}`);
  return (await res.json()) as T;
}

export const api = {
  health: () => http<{ ok: boolean }>("/health"),
  validateKey: (api_key: string) =>
    http<{ ok: boolean; preview?: string; models?: number; free_models?: string[]; message?: string; category?: string }>(
      "/setup/validate_key",
      { method: "POST", body: JSON.stringify({ api_key }) },
    ),
  applyKey: (api_key: string) =>
    http<{ ok: boolean; info: any; preview: string }>(
      "/setup/apply_key",
      { method: "POST", body: JSON.stringify({ api_key }) },
    ),
  selfTest: () => http<any>("/setup/self_test"),
  status: () => http<any>("/setup/status"),

  conversations: () => http<any[]>("/chat/conversations"),
  messages: (cid: number) => http<any[]>(`/chat/conversations/${cid}/messages`),
  send: (message: string, conversation_id?: number) =>
    http<{ reply: string; task_id?: number | null; spoken?: string | null }>(
      "/chat/send",
      { method: "POST", body: JSON.stringify({ message, conversation_id }) },
    ),

  tasks: () => http<any[]>("/tasks"),
  task: (id: number) => http<any>(`/tasks/${id}`),
  taskPause: (id: number) => http<{ ok: boolean }>(`/tasks/${id}/pause`, { method: "POST" }),
  taskResume: (id: number) => http<{ ok: boolean }>(`/tasks/${id}/resume`, { method: "POST" }),
  taskCancel: (id: number) => http<{ ok: boolean }>(`/tasks/${id}/cancel`, { method: "POST" }),

  memoryList: (category?: string) =>
    http<any[]>(`/memory${category ? `?category=${encodeURIComponent(category)}` : ""}`),
  memoryAdd: (m: { category: string; content: string; importance?: number; confidence?: number; tags?: string[] }) =>
    http<{ id: number }>("/memory", { method: "POST", body: JSON.stringify(m) }),
  memorySearch: (query: string, categories?: string[]) =>
    http<any[]>("/memory/search", { method: "POST", body: JSON.stringify({ query, categories }) }),
  memoryForget: (id: number) => http<{ ok: boolean }>(`/memory/${id}`, { method: "DELETE" }),

  filesList: (path: string, recursive = false) =>
    http<any>(`/files?path=${encodeURIComponent(path)}&recursive=${recursive}`),
  filesAction: (name: string, args: Record<string, any>) =>
    http<any>("/files/action", { method: "POST", body: JSON.stringify({ name, args }) }),

  monitors: () => http<{ monitors: any[] }>("/monitors"),
  runningApps: () => http<{ apps: any[] }>("/running_apps"),
  activity: (limit = 100) => http<{ events: any[] }>(`/activity?limit=${limit}`),
  providerStatus: () => http<any>("/providers/status"),

  diagHealth: () => http<any>("/diagnostics/health"),
  diagRepair: () => http<any>("/diagnostics/repair", { method: "POST" }),
};

// WebSocket events
export function openEventsWS(onMessage: (data: any) => void): WebSocket {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/events`);
  ws.onmessage = (ev) => {
    try {
      onMessage(JSON.parse(ev.data));
    } catch {
      // ignore
    }
  };
  return ws;
}

export function openVoiceWS(onMessage: (data: any) => void): WebSocket {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/voice`);
  ws.onmessage = (ev) => {
    try {
      onMessage(JSON.parse(ev.data));
    } catch {
      // ignore
    }
  };
  return ws;
}