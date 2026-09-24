import { Mic, MicOff, Send, Square, Pause, Play } from "lucide-react";
import { useApp } from "../store/app";
import { useState } from "react";
import { api, openVoiceWS } from "../lib/api";

export default function VoiceBar() {
  const voiceState = useApp((s) => s.voiceState);
  const setVoiceState = useApp((s) => s.setVoiceState);
  const messages = useApp((s) => s.messages);
  const pushMessage = useApp((s) => s.pushMessage);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  const send = async () => {
    const msg = text.trim();
    if (!msg) return;
    setText("");
    setBusy(true);
    setVoiceState("thinking");
    const id = Date.now();
    pushMessage({ id, role: "user", content: msg, ts: new Date().toISOString() });
    try {
      const r = await api.send(msg);
      pushMessage({ id: id + 1, role: "assistant", content: r.reply, ts: new Date().toISOString(), task_id: r.task_id ?? null });
      if (r.task_id) setVoiceState("working");
      else setVoiceState("idle");
    } catch (e: any) {
      pushMessage({ id: id + 2, role: "system", content: `Error: ${e?.message || e}`, ts: new Date().toISOString() });
      setVoiceState("error");
    } finally {
      setBusy(false);
    }
  };

  const toggleMic = () => {
    if (voiceState === "listening") {
      setVoiceState("idle");
    } else {
      // Open a new voice WS so the user can speak and hear responses.
      openVoiceWS(() => {});
      setVoiceState("listening");
    }
  };

  return (
    <div className="voice-bar">
      <div className="row" style={{ gap: 12 }}>
        <button className={voiceState === "listening" ? "danger" : ""} onClick={toggleMic}>
          {voiceState === "listening" ? <MicOff size={16} /> : <Mic size={16} />}
          <span style={{ marginLeft: 6 }}>{voiceState === "listening" ? "Mute" : "Push-to-talk"}</span>
        </button>
        <span className="pill">State: <b>{voiceState}</b></span>
      </div>
      <div className="row" style={{ flex: 1, margin: "0 18px", gap: 8 }}>
        <input
          placeholder="Type a message — CHERYY will also speak the answer…"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && send()}
          disabled={busy}
        />
        <button className="primary" disabled={busy || !text.trim()} onClick={send}>
          <Send size={16} />
        </button>
      </div>
      <div className="row" style={{ gap: 6 }}>
        <button title="Stop"><Square size={14} /></button>
        <button title="Pause"><Pause size={14} /></button>
        <button title="Resume"><Play size={14} /></button>
      </div>
    </div>
  );
}