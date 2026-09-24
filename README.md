# CHERYY

> Your personal AI office assistant. A Windows-native autonomous desktop agent.

CHERYY is a local desktop application that uses **your** Google Gemini API key to perform real, verifiable office work on your Windows computer: chat, voice, document generation, browser automation, file management, publishing, and more — without ever deleting anything on your PC.

## Highlights

- **Voice-first** with deep, calm, professional male voice and barge-in interruption.
- **Chat-also-voice**: every chat response is also spoken aloud.
- **Free-first**: works on Gemini free-tier models with quota/rate-limit awareness.
- **No-delete guarantee** enforced by a programmatic security engine (not just prompts).
- **Event-driven** architecture — minimal idle CPU/RAM.
- **Real verification**: every important action is observed and validated.

## Quick start (developer)

```bash
# Backend
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -e .
cheryy-server          # starts the backend on http://127.0.0.1:7480

# Desktop UI (Vite + React + TS)
cd ..\desktop
npm install
npm run dev             # opens the desktop UI
```

## User quick start (after install)

1. Launch **CHERYY**.
2. Paste your Gemini API key.
3. Click **VALIDATE API KEY**.
4. CHERYY does the rest automatically.
5. Speak or type.

## Architecture

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## License

Proprietary — © CHERYY. All rights reserved.