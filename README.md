# Atlas v2 — M1 Local Workspace Foundation

**Status: implemented first milestone / local acceptance candidate; Windows daily-use acceptance still pending.** This is an actual local web application, not a design mockup. It is a **general-purpose** personal work and knowledge workspace; it does **not** embed AI, use a paid API, or require cloud hosting.

## Install and start (Windows / Linux / macOS)

Requires Python **3.11+**. Run commands from the extracted `Atlas_v2_M1` folder:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python start_atlas.py
```

On Linux/macOS, replace `.venv\Scripts\python` with `.venv/bin/python`. Or install dependencies in an existing virtual environment and run `python start_atlas.py`. Windows has `start_atlas.bat`, which assumes `py -3` can find an environment with the dependencies installed; using the explicit virtual environment is more reliable.

Open **http://127.0.0.1:8766/**. The app binds to `127.0.0.1`, and the UI and API operate offline once Python dependencies are installed. Stop the server with Ctrl+C.

**Data location:** by default `~/Documents/Atlas-v2/` (e.g., `C:\Users\<you>\Documents\Atlas-v2`). Change before starting with `ATLAS_DATA_HOME`:

```powershell
$env:ATLAS_DATA_HOME = 'D:\MyAtlasData'
.venv\Scripts\python start_atlas.py
```

The working data path is *not* inside this source repository; distributing or updating code does not automatically copy your personal notes. If a backup needs to be restored, see below. If port 8766 is in use, change `ATLAS_PORT` **before starting**; this is a single-process local app.

## Do one complete work session

1. Open **Workspaces**, create any workspace (e.g. `Software Engineering` or `Writing`). Kind is a label only, not a hard-coded course system.
2. Create a task with a concrete next action and optional deadline and priority.
3. Create a Markdown note or link an existing file/directory/repository. Linked files are never copied, scanned recursively, modified or run.
4. After working, save a **resume checkpoint** stating the result, evidence, blocker, and your next action.
5. Use **ChatGPT handoff** to prepare context. Only selected managed note excerpts are included. Review, copy, and paste the text manually into ChatGPT. No automatic access to your ChatGPT account or reminders is claimed.
6. Restart Atlas. Open **Today** and resume from the saved checkpoint. The task and files remain available.
7. Use **Data & backup** to export a ZIP backup regularly, and after substantial edits.

## What Atlas owns

| Data | Owner | Meaning |
|---|---|---|
| Workspaces, tasks, note metadata, checkpoints, activity history | `database.sqlite3` | SQLite is authoritative |
| Managed notes | `managed/notes/<id>.md` | Normal user-readable Markdown files; SQLite stores reference and revision |
| Linked external files | Your existing computer filesystem | Atlas stores only paths and availability; never the file bytes |
| Imported v1.1 study records | `imports/legacy/<sha256>.json` | Exact original JSON archived; courses/topics mapped to workspaces/tasks |
| Backups | User/downloaded ZIP, or `backups/` | Full owned data and references, **not** linked external file contents |

The server does not execute code from managed notes, automatically perform a Git operation, scan linked directories, call a model, or sync to a calendar.

## Existing v1.1 study data: import carefully

1. Open the *original* Atlas Study Workspace v1.1 in **the same browser and URL you previously used** (usually `http://127.0.0.1:8765/`). Export JSON from **Data > Export**. Do not reset its data.
2. In v2, open **Data & backup > Preview legacy JSON** and choose your **actual exported file**, *not* the starter sample bundled in `legacy/`.
3. Inspect the preview. Each course maps to a workspace, each topic to a task. Other arrays (plan, challenges, attempts, sessions, review history, notes, etc.) remain in an **unchanged, archived JSON** but are *not yet active v2 views*. Status mapping: `todo`→To do; `active`/`covered`→In progress; `review`→Blocked; `verified`→Completed. Original exact status and evidence remain attached in task details/the archive.
4. Confirm import. Atlas saves a **pre-import recovery ZIP** to its local `backups/` folder. Importing the **same byte-identical file** again is idempotent. Importing a *different* legacy export into that profile is refused to prevent accidental duplicate projects; use a new profile until a merge flow exists.
5. Inspect the mapped data before relying on it. The old v1.1 browser history remains unchanged. Never delete the old app or its export until the new profile is verified.

`legacy/v1_1_STARTER_SAMPLE_NOT_USER_DATA.json` is a test fixture generated from the unmodified v1.1 default seed, **not your actual progress**. `legacy/Atlas_v1.1_UNMODIFIED_SOURCE.zip` preserves the original distributed v1.1 source unchanged.

## Backups, restore, and safety

- **Back up:** use the **Download complete backup** button. Or with a stopped or running app:

  ```powershell
  .venv\Scripts\python atlas_cli.py backup
  ```

- **Check** a backup without changing current work:

  ```powershell
  .venv\Scripts\python atlas_cli.py verify "C:\Backups\atlas-v2-backup.zip"
  ```

- **Restore to a completely new profile** (not a replacement):

  ```powershell
  .venv\Scripts\python atlas_cli.py restore "C:\Backups\atlas-v2-backup.zip" "D:\Atlas-Recovered"
  $env:ATLAS_DATA_HOME = 'D:\Atlas-Recovered'
  .venv\Scripts\python start_atlas.py
  ```

The UI also supports **staging** restore copies under `staged_restores/`; it does not switch the active profile automatically. Backup verification checks filenames, hash manifest, compressed/expanded sizes, SQLite integrity, and schema version. You should periodically test a restore. Missing external paths are reported; their content is **never** backed up.

### Safety boundaries

- APIs require same-origin access, restricted Host, and an in-memory write token. This is **single-user local security**, not a replacement for operating-system disk permissions or user authentication.
- Managed note filenames are generated UUIDs; no user-provided filesystem path is accepted for managed file writes. UUID-based containment, reparse/symlink checks, byte limits, atomic replace and optimistic note versions are enforced.
- **External linked files are read-only.** The “Open folder” action opens only their containing directory in the system file manager after a direct click; it does not execute a linked program.
- Markdown is displayed as literal, escaped text for editing; the app does not run scripts from notes.
- Backups and legacy imports are treated as untrusted; do not import files from untrusted sources. A malicious process with write access to your local profile may still exploit filesystem races. Windows reparse-point hardening and concurrent external editor behavior require an actual Windows security test before wider distribution.
- Notes and DB are not encrypted at rest. Do not store passwords or sensitive credentials. Protect backups and device access.
- Only simple note versions are supported. Atlas has no general conflict resolution for multiple editors, and SQLite metadata plus Markdown files are **not a single atomic transaction across crashes**. Make regular backups.

## Validate

```powershell
.venv\Scripts\python -m pip install pytest httpx
.venv\Scripts\python -m pytest -q tests/test_m1.py
```

Optional **browser acceptance** test needs Playwright, a Chromium installation, and an environment that allows localhost navigation:

```powershell
.venv\Scripts\python -m pip install playwright
.venv\Scripts\python -m playwright install chromium
.venv\Scripts\python tests/browser_acceptance.py
```

This build passed 10 isolated HTTP API/security/backend tests and a real local HTTP smoke test on Linux; direct browser navigation was **blocked by the test environment**, not proven to pass. Before calling the milestone fully accepted, run the browser acceptance test and a hands-on file safety/recovery test on your actual Windows machine. The use of `py -3` in `start_atlas.bat` is not a substitute for creating a virtual environment.

## Directory layout

```text
Atlas_v2_M1/
  atlas/
    api.py           FastAPI endpoints, localhost guards
    service.py       Workspace/task/checkpoint/note operations
    database.py      SQLite v1 schema migration
    safety.py        Managed file path protections and atomic writes
    backup.py        Verified full-owned-data ZIP backups and staging
    legacy.py        v1.1 preview/import, original export archive
  static/
    index.html       Today/Workspaces/Library/Data shell
    styles.css       Responsive user interface
    app.js           Forms, workflow, search, handoff
  tests/
    test_m1.py       API and security acceptance tests
    browser_acceptance.py  Optional browser end-to-end test
  docs/
    FOUNDATION_SPEC.md
  legacy/
    Atlas_v1.1_UNMODIFIED_SOURCE.zip
    v1_1_STARTER_SAMPLE_NOT_USER_DATA.json
  start_atlas.py
  start_atlas.bat
  atlas_cli.py
  requirements.txt
```

## Deliberately postponed

Google Calendar OAuth/sync, automatic ChatGPT/MCP integration, scheduled notifications, full Notion-style editing, semantic search, cross-device collaboration/sync, quizzes, spaced-repetition engine, and an AI assistant. **No paid AI API is required or planned.**

## Next engineering gate

**M1 local codebase completed for API-backed core; local Windows/browser acceptance still open.** After validating the daily workflow and backup/recovery on the user's Windows computer, prioritize convenience of file linking, checkpoint capture friction, accessibility/keyboard testing, and later Calendar integration based on actual use. See `docs/FOUNDATION_SPEC.md` for the acceptance definition and `docs/M1_VALIDATION_REPORT.md` for test results and limitations.
