# CHERYY Tool reference

This is the canonical list of tools CHERYY exposes to the agent. Every
tool runs through `cheryy.tools.Tool` and is gated by the security
engine.

## Filesystem (no delete)

| Tool | Notes |
| --- | --- |
| `filesystem.list`    | list folder |
| `filesystem.search`  | glob search |
| `filesystem.read`    | text read (≤64 KB) |
| `filesystem.create`  | write new file (refuses if exists) |
| `filesystem.edit`    | replace text / append |
| `filesystem.copy`    | copy (source preserved) |
| `filesystem.move`    | move (preserves source if dst exists) |
| `filesystem.rename`  | rename in place |
| `filesystem.open`    | open with default app |

## Computer

| Tool | Notes |
| --- | --- |
| `computer.get_screen` | screenshot of monitor (on demand only) |
| `computer.get_windows` | enumerate visible windows |
| `computer.get_active_window` | title + bounds |
| `computer.get_ui_tree` | pywinauto UI tree |
| `computer.move_mouse` | absolute move |
| `computer.click`, `computer.double_click`, `computer.right_click` | |
| `computer.drag` | drag between coordinates |
| `computer.scroll` | scroll wheel |
| `computer.type` | type text |
| `computer.hotkey` | hotkey combination |

## Browser

| Tool | Notes |
| --- | --- |
| `browser.open` | launch persistent Chromium profile |
| `browser.navigate`, `browser.read`, `browser.click`, `browser.type` | DOM-first |
| `browser.select`, `browser.upload`, `browser.download` | |
| `browser.screenshot` | only when DOM is ambiguous |

## Office

| Tool | Notes |
| --- | --- |
| `office.create_docx` | round-trip validated |
| `office.create_pptx` | LibreOffice preview where available |
| `office.create_xlsx` | multi-sheet + chart |
| `office.create_pdf` | pdfplumber page check |

## Content

| Tool | |
| --- | --- |
| `content.blog` | long-form SEO article + JSON metadata |
| `content.seo` | title / meta / slug / keywords |
| `content.write` | short-form copy |
| `content.summarize` | summary in user's chosen style |

## Image

| Tool | |
| --- | --- |
| `image.generate` | placeholder by default (no provider wired) |
| `image.resize` | Pillow resize |
| `image.convert` | format converter |

## Publishing

| Tool | |
| --- | --- |
| `publisher.wordpress_publish` | Application Password auth |
| `publisher.generic_api` | POST JSON to a stored endpoint |

## Conventions

* Result shape: `{success, tool, data?, error?, verification, observed_state?, recovery?, latency_ms}`
* `destructive=True` is FORBIDDEN — the agent never sees such a tool.
* `elevated=True` triggers a user-approval request unless auto-approve is
  enabled in `policy.auto_approve_elevated`.
