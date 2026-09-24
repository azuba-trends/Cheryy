# CHERYY — User guide

> A calm, deep-voiced personal AI office assistant for Windows.

This guide is for the **end user** who installed CHERYY.

## Install

1. Double-click the CHERYY installer (MSI or NSIS).
2. Follow the standard Windows installer steps.
3. CHERYY appears in the Start Menu and on the Desktop.
4. Launch it. The first time you do, you'll see the **Welcome** screen.

## First run

1. The CHERYY window opens with one field: **Gemini API Key**.
2. Paste the API key you got from
   <https://aistudio.google.com/apikey> and click **VALIDATE API KEY**.
3. CHERYY calls the real Gemini API to confirm the key works. If anything
   goes wrong, it tells you exactly *what category* (auth / network /
   quota) so you can fix it.
4. On success, CHERYY automatically:
   * stores your key in the Windows Credential Manager (encrypted at rest);
   * discovers the models you can use (free tier preferred);
   * initialises memory, the task engine, the database;
   * runs a self-test to confirm everything is wired up.
5. You're taken to the **Home** page. You're ready.

## Two input modes

* **Voice (default)** — speak naturally, CHERYY interrupts itself
  the moment you speak. The transcript appears in chat too.
* **Chat** — click **Chat** in the sidebar or just type. The keyboard
  shortcut is `Enter`. **Even chat replies are spoken aloud**, so you can
  switch back to voice any time without losing context.

## What you can ask CHERYY

Examples (CHERYY understands these and many more):

* "Create a 12-slide PowerPoint about AI in healthcare and save it to
  Documents."
* "Write a professional blog post about remote work and save it as DOCX."
* "Open Chrome, search for the top 5 generative-AI tools of 2026, and
  summarise them in a Word doc."
* "Make an Excel report from the CSV in Downloads."
* "Summarise the PDFs in my Documents folder."
* "Open WordPress and publish yesterday's draft."

CHERYY always:

1. Confirms it understands.
2. Plans the steps.
3. Performs each step *and verifies the result before moving on*.
4. Reports what it actually did (with file paths, links, etc.).

## Pages in CHERYY

| Page | What it shows |
| --- | --- |
| **Home** | Welcome, examples, AI status |
| **Chat** | The conversation. Voice or text. |
| **Tasks** | List of every task CHERYY has run, with Pause / Resume / Cancel |
| **Live PC** | Multi-monitor layout, running apps, on-demand screenshot |
| **Files** | Browse Documents / Desktop / Downloads. **No delete button.** |
| **Memory** | View / search / edit / forget what CHERYY remembers about you |
| **Skills** | The modules currently enabled (Office, Browser, Windows, …) |
| **Activity** | The human-readable activity log |
| **Settings** | Change API key, run diagnostic repair, view privacy controls |

## What CHERYY will NEVER do

* Delete any file or folder on your computer. This is enforced by code,
  not just by prompts. (See `docs/SECURITY.md`.)
* Send your private data to Gemini unless you asked for help on it.
* Modify your system, registry, or installed applications.
* Continue without asking if you cancel a task.

## Privacy

* Conversations, memory, tasks, and the activity log live **only on your
  machine** (in `%LocalAppData%\CHERYY` by default).
* The screen is captured only when needed for a task. Nothing is recorded
  continuously.
* Your microphone is active only while CHERYY is listening.
* You can review and forget anything in **Memory → click ✕ on a record**.
