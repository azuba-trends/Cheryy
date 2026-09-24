import { useApp, ChatMessage } from "../store/app";
import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";

export default function ChatPage() {
  const messages = useApp((s) => s.messages);
  const conversationId = useApp((s) => s.conversationId);
  const setConversationId = useApp((s) => s.setConversationId);
  const pushMessage = useApp((s) => s.pushMessage);
  const resetConversation = useApp((s) => s.resetConversation);
  const setVoiceState = useApp((s) => s.setVoiceState);
  const setPage = useApp((s) => s.setPage);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);

  // Auto-load most recent conversation
  useEffect(() => {
    if (conversationId) return;
    api.conversations().then((list) => {
      if (list && list.length) {
        const first = list[0];
        setConversationId(first.id);
        api.messages(first.id).then((ms) => {
          // Reset & replay
          resetConversation();
          setConversationId(first.id);
          for (const msg of ms) {
            pushMessage({
              id: msg.id,
              role: msg.role,
              content: msg.content,
              ts: msg.ts,
              voice_text: msg.voice_text,
              task_id: msg.task_id,
            });
          }
        });
      }
    }).catch(() => {});
  }, [conversationId, pushMessage, resetConversation, setConversationId]);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [messages.length]);

  const send = async () => {
    const text = draft.trim();
    if (!text) return;
    setDraft("");
    setBusy(true);
    setVoiceState("thinking");
    const id = Date.now();
    pushMessage({ id, role: "user", content: text, ts: new Date().toISOString() });
    try {
      const r = await api.send(text, conversationId ?? undefined);
      pushMessage({ id: id + 1, role: "assistant", content: r.reply, ts: new Date().toISOString(), task_id: r.task_id ?? null });
      setVoiceState(r.task_id ? "working" : "speaking");
      setTimeout(() => setVoiceState("idle"), 1500);
    } catch (e: any) {
      pushMessage({ id: id + 2, role: "system", content: `Error: ${e?.message || e}`, ts: new Date().toISOString() });
      setVoiceState("error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="chat-list" ref={listRef}>
        {messages.length === 0 && (
          <div className="empty-state">
            <h2>Hello — I am CHERYY.</h2>
            <p>Tell me what you'd like to do. I can speak as well as type my answers.</p>
            <button className="primary" onClick={() => setPage("tasks")}>View recent tasks →</button>
          </div>
        )}
        {messages.map((m) => (
          <div key={m.id} className={`bubble ${m.role}`}>
            <div>{m.content}</div>
            {m.task_id && (
              <div style={{ marginTop: 6 }}>
                <span className="tag">task #{m.task_id}</span>
              </div>
            )}
          </div>
        ))}
        {busy && (
          <div className="bubble assistant">
            <span className="typing"><span /><span /><span /></span>
          </div>
        )}
      </div>
      <div className="chat-input-row">
        <textarea
          placeholder="Ask CHERYY anything… (Enter to send, Shift+Enter for newline)"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          disabled={busy}
        />
        <button className="primary" onClick={send} disabled={busy || !draft.trim()}>Send</button>
      </div>
    </>
  );
}