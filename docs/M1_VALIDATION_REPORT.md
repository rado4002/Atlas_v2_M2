# Atlas v2 M1 — Implementation and Validation Report

**Status:** LOCAL API/CORE VALIDATION PASS; **FULL M1 ACCEPTANCE PENDING** on the user's Windows/browser environment.

## Delivered

- FastAPI localhost server and responsive HTML/CSS/JavaScript application (Today, Workspaces, Library, Data & backup).
- SQLite schema v1; generic workspaces with rename/archive, tasks with status/priority/deadline, append-only resume checkpoints, activity history.
- Managed Markdown notes written to UUID-named paths under the Atlas data home, with atomic replace, max-size and symlink/reparse-point checks, and optimistic versioning.
- Read-only external file/directory references with availability reporting and explicit folder reveal, without repository changes.
- Search of record metadata and small managed-note content (current content scan limited to 300 notes; external files not scanned).
- Manual, reviewed ChatGPT context handoff; note content included only when explicitly selected. No embedded AI or paid API.
- Verified ZIP export containing database snapshot, managed notes and archived legacy JSON, but not externally linked file contents.
- Non-destructive ZIP restore into a new profile; integrity checks, allowlisted archive entries and hash verification.
- Atlas v1.1 export preview and one-time deterministic import mapping courses/topics to generic workspaces/tasks; full original JSON archived; repeated identical exports idempotent; different legacy export blocked to avoid duplicate data. Pre-import backup created.
- Original v1.1 source archive retained in the release; a separate default-seed JSON fixture is clearly marked **not user data**.

## Verification evidence

| Check | Result |
|---|---|
| `python -m pytest -q tests/test_m1.py` | PASS — 10 tests |
| `node --check static/app.js` | PASS |
| `python -m compileall -q atlas start_atlas.py atlas_cli.py` | PASS |
| Real loopback HTTP GET/bootstrap and POST/create workspace via subprocess server | PASS — HTTP 201 |
| SQLite restart persistence, backup/restore, original-note-byte verification | PASS in tests |
| Malformed/hostile origin, missing write token, Host header mismatch | Rejected in tests |
| Path traversal, symlinked note target, stale note version, oversized Unicode file | Rejected in tests |
| ZIP-slip and hash tampering, missing external references | Rejected/reported in tests |
| Unmodified v1.1 starter dataset import (5 courses, 23 topics) | PASS |
| Direct Playwright/Chromium browser acceptance | BLOCKED by environment (`ERR_BLOCKED_BY_ADMINISTRATOR`, including `file:` and `data:` navigations) |
| Actual Windows junction/reparse security and daily usability test | NOT RUN |
| Real user v1.1 JSON export (as distinct from starter data) | NOT AVAILABLE — requires user's browser export |

## Acceptance decision

The M1 backend and main operations are delivered and verified. It would be inaccurate to call the complete milestone fully accepted until the optional browser test passes on Windows, a user's actual legacy export is previewed/imported in a disposable profile, and filesystem safety and restore are checked on that machine.

## Known constraints and risks

1. No AI model or paid API. ChatGPT handoff is explicit copy/paste, not automatic ChatGPT memory/task synchronization.
2. No live Google Calendar, reminders or scheduled notifications. These are later modules.
3. SQLite note metadata and Markdown byte writes cannot be made one distributed atomic transaction. A crash in the small window between file replace and database commit may require recovery from backup.
4. Concurrent external editors and malicious processes with filesystem write access are not fully isolated; use the app on a trusted single-user computer.
5. The original v1.1 export's challenges, review history and other non-mapped arrays are retained as original JSON but not active v2 views.
6. The application is a local server, not a packaged desktop executable or hosted site. Python dependencies require initial installation.
7. The UI/browser interactions were not verified in the restricted browser runtime. Run the included `tests/browser_acceptance.py` on a normal Windows workstation.
8. Search content scanning is limited to the first 300 managed notes; title search still runs on all notes. Linked external files are never indexed.
9. Built-in full restore is staged/new-profile only, by design. Atlas does not silently overwrite current data.

## Recommended next milestone after Windows acceptance

M2: Refine the core daily flow from actual usage—context capture friction, note navigation, intentional file reference updates, task prioritization and better search—then introduce Calendar integration separately. Avoid developing an AI chatbot or paid model API inside Atlas.
