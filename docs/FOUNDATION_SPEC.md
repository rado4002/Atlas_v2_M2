# Atlas v2 — Foundation Specification

**Status:** Proposed / ready for implementation planning (not implemented).  
**Baseline:** Atlas Study Workspace v1.1 — browser application with localStorage, JSON export/import, and a static Python localhost server.  
**Architecture decision:** Hybrid local files; general-purpose workspaces; no embedded AI and no paid AI API.

## 1. Product purpose

Atlas is a **local-first personal work and knowledge workspace**. It reduces the effort required to decide what to do, locate the relevant material, capture outcomes, and resume work. It may complement ChatGPT, calendar applications, text editors, terminals, and other tools without replacing them.

Atlas must support arbitrary user-chosen work (software development, study, writing, research, personal projects, etc.) using the **same core model**. Specialized capabilities—such as spaced reviews, quizzes, and focus sessions—are opt-in.

**Not in scope:** an embedded AI/chatbot, paid model/API calls, autonomous file modification, a Notion/Coda clone, cloud sync, team collaboration, or background monitoring of all computer files.

## 2. Required everyday workflows

1. **Start:** open Today, see a prioritized next action with deadline, state, linked references, and a clear reason for its ranking. User can override order.
2. **Resume:** open any workspace and access the last checkpoint, unfinished task, linked files, and a prepared, copyable ChatGPT handoff context. Handoff is explicit and manual by default.
3. **Capture:** after work, save a concise result, evidence/file links, blockers, and the next physical action. Do not equate elapsed time or checked boxes with verified mastery.
4. **Retrieve:** search and filter by workspace, task, title, tags, or note content inside managed notes. Opening linked external files uses explicit user action.
5. **Recover:** restore metadata, managed notes, and reference mappings from a tested backup; never make a backup falsely claim to contain the bytes of linked external files.

## 3. Functional requirements

| ID | Requirement | Priority | Acceptance condition |
|---|---|---|---|
| F-01 | Create, rename, archive, and navigate generic workspaces. | Must | One learning workspace and one software-project workspace use identical core objects. |
| F-02 | Workspaces contain tasks with status, priority, due date (optional), and next action. | Must | A user can create, edit, close, and reopen tasks without changing unrelated records. |
| F-03 | Persist a single prominent resume checkpoint per workspace (what changed, next action, blocker, last updated). | Must | Checkpoint survives browser and server restarts and is editable. |
| F-04 | Create, edit, and organize Markdown notes inside the Atlas-managed root. | Must | Saving a note changes only its managed file, atomically. |
| F-05 | Register external files and directories as linked references, without copying or altering them. | Must | Linking a Git repository leaves all repository bytes and metadata untouched. |
| F-06 | Clear, opt-in contextual handoff to ChatGPT (copy text; optionally open ChatGPT). | Must | No account/API key or automatic reading of chat history required. |
| F-07 | Local search and filtering for workspaces, tasks, notes, and reference metadata. | Should | A known note can be located by title or term without browsing folders manually. |
| F-08 | Back up and restore database + managed files; report missing linked references separately. | Must | Isolated restore reproduces data and managed note content; no silent overwrite. |
| F-09 | Import v1.1 JSON through preview, validation, and explicit confirmation; preserve original export unchanged. | Must before abandoning v1.1 | Migration can be dry-run, repeated safely, and rolled back to a pre-import snapshot. |
| F-10 | Add calendar integration and review capabilities as optional modules. | Later | Core workspaces operate normally with these modules disabled. |

## 4. Core data model (proposed)

- **Workspace** (`id`, `name`, `description`, `kind_label`, `archived_at`, timestamps): a container; `kind_label` is descriptive, not a hard-coded workflow switch.
- **Task** (`id`, `workspace_id`, `title`, `status`, `priority`, `due_at?`, `next_action?`, timestamps): a concrete action or deliverable.
- **Checkpoint** (`id`, `workspace_id`, `summary`, `next_action`, `blocker?`, `evidence?`, `created_at`): append-only historical checkpoints; `workspace.current_checkpoint_id` points to the active one.
- **Note** (`id`, `workspace_id`, `relative_path`, `title`, timestamps, `content_version`): metadata in SQLite; the Markdown bytes remain in the managed filesystem.
- **FileReference** (`id`, `workspace_id`, `kind`, `display_name`, `target_path`, `access_mode`, `last_checked_at`, `availability`): a pointer, **not** the file contents. Initial `access_mode` for external references is read-only.
- **ActivityEvent** (`id`, `workspace_id`, `type`, `related_id`, `timestamp`, `summary`): minimal inspectable change history, without secretly recording user activity.
- **ExternalLink** (later; `record_id`, `provider`, `external_id`, `sync_state`): calendar integration IDs and synchronization state.

Use SQLite foreign keys, unique stable IDs, UTC timestamps, schema migrations, and transactions. Model fields should be generic; study-specific fields live in optional modules, not in every task.

## 5. Data ownership and source-of-truth boundaries

| Data | Authoritative owner | Atlas may do | Atlas must not do |
|---|---|---|---|
| Workspace, tasks, checkpoints, note metadata | Atlas SQLite database | Read/write through validated app operations | Keep a second mutable truth in browser localStorage |
| Atlas-managed Markdown files | Files under configured Atlas root | Create/edit/rename via explicit operations | Store the only copy inside opaque DB blobs |
| Existing Git repositories, PDFs, course folders | Original external filesystem/location | Store links and read permitted metadata; open on request | Rewrite, move, import wholesale, delete, or git-commit automatically |
| ChatGPT discussions and ChatGPT reminders | ChatGPT platform | Prepare explicit handoffs; accept user-reviewed pasted/imported summaries | Claim automatic access/synchronization or silently infer completion |
| Calendar appointments (later) | Calendar provider for event scheduling; Atlas for task meaning/status | Create/update only authorized event projections, retain provider IDs | Equate a calendar event with completed work or create duplicates |
| Backup archives | User-selected backup destination | Export/restore complete owned data with manifest | Claim to back up the contents of linked external directories |

**Browser localStorage in v2** may store ephemeral UI preferences, but not the authoritative workspace or learning history. The v1.1 browser data is retained untouched until import has been verified.

## 6. Hybrid file model and safety contract

### Two explicit categories

- **Managed files:** inside a user-chosen Atlas root, e.g. `Documents/Atlas/workspaces/<workspace-id>/notes/`; Atlas can write only here. User owns the normal Markdown and other files.
- **Linked references:** files or folders the user chooses outside Atlas, including code repositories. Atlas stores paths and minimal metadata. **Read-only in the first milestone.** Missing or moved files are shown as broken links, not recreated or deleted.

### Mandatory rules

1. Never scan the entire computer, Documents directory, or repository recursively without explicit scope and consent. Linking a directory does not authorize ingesting its contents.
2. Resolve and validate paths against configured allowed roots on each operation. Reject traversal (`..`), absolute paths in managed relative-path fields, unexpected symlinks/junctions, and paths escaping the managed root. Revalidate at operation time rather than trusting saved paths.
3. Never write into linked external directories. Open linked files only after explicit user action; don't execute commands or interpolate path strings into a shell.
4. For managed writes, validate file type and size, write to a temporary sibling file, flush, and atomically replace where supported; detect conflicting edits through a revision/version field.
5. For deletions, use an explicit confirmation and recoverable trash/soft-delete mechanism. No unattended mass edits or deletes.
6. Serve the app on `127.0.0.1` by default, not `0.0.0.0`. Validate request Origin/Host, protect writes against cross-site requests (e.g. CSRF/session token), and do not enable broad CORS. Localhost alone is not a security boundary.
7. Never expose arbitrary filesystem paths or file contents through a public URL. Restrict allowed extensions/operations initially; avoid following symlinks for writes, including Windows junction/reparse-point edge cases.
8. Treat notes and imported JSON as untrusted input: validate sizes and schemas, escape rendered HTML, sanitize any Markdown rendering, and avoid executing embedded scripts.
9. Backups include the SQLite database, managed-file tree, and a manifest of external paths **only**. Backups are versioned and restore into a separate directory first for inspection.
10. Keep visible error messages for missing files, permissions, broken references, disk-full conditions, and failed atomic writes; do not silently mark operations successful.

## 7. Suggested implementation architecture

```text
Browser UI (Today | Workspaces | Library | Review later)
       |
       | localhost HTTP; validated JSON
       v
Python FastAPI local application
       |--- SQLite database (workspaces, tasks, checkpoints, file metadata)
       |--- Managed file service (allowed Atlas root only)
       |--- Read-only external reference registry
       |--- Backup and legacy import service
       `--- Context handoff exporter (no AI inference)

External: ChatGPT via manual, explicit handoff; Google Calendar later via separate OAuth.
```

The initial app must work **fully offline**. No OpenAI key, no paid AI API, no cloud deployment, and no always-on background service are required.

## 8. First implementation milestone — M1: Local Workspace Foundation

**Goal:** From one Atlas screen, create a generic workspace, keep a next action, edit a managed Markdown note, link an existing external folder without modifying it, and resume the same work after restart—with a recoverable backup.

### Included

- Local FastAPI server bound to loopback; versioned `/api/v1` routes, structured validation, SQLite migrations.
- Three core entities in active UI: Workspace, Task, Checkpoint; plus Note and FileReference.
- Minimal views: **Today**, **Workspace detail**, **Library**. Reuse v1.1 styling where practical; study-specific views can remain separately accessible until migrated.
- Create/edit managed Markdown note; register/open read-only linked file or directory; display broken-reference state.
- Copyable ChatGPT context assembled from selected workspace/task/checkpoint and user-selected note excerpts (never silently upload filesystem contents).
- Full backup/restore of M1-owned data; v1.1 JSON import preview and preservation of the original as an immutable archive. Map supported legacy fields deterministically; present unmapped records rather than dropping them.
- Automated tests of API, migrations, path escape/symlink rejection, backup/restore, and v1.1 import dry-run.

### Explicitly excluded from M1

Google Calendar live sync; ChatGPT automatic connector/MCP; notifications; quizzes/spaced repetition redesign; multi-device sync; full-text indexing of external repositories; file editing outside the Atlas-managed root; plugins; AI model/API functionality.

### M1 verification scenarios

1. **General-purpose proof:** Create two different workspaces—`Database practice` and `Software project`—with the same workflow and no hard-coded course model.
2. **File-safety proof:** Link an existing Git repo, save an Atlas note, restart, and verify the repo's tracked/untracked files, timestamps where reliably measurable, and Git status were not changed by Atlas.
3. **Resume proof:** Record a checkpoint, close browser/server, reopen, and reach the next action and relevant resource without consulting old chat history.
4. **Attack/failure proof:** Attempts to write to `../outside.md`, an absolute external path, or symlink/junction escape fail; malformed import, inaccessible link, and simulated write failure leave existing data intact.
5. **Recovery proof:** Export a backup, restore in an isolated target directory, and verify identical owned records and managed file bytes, while missing external files are reported as missing—not restored.
6. **Migration proof:** Import a real v1.1 JSON export in dry-run, inspect counts and unmapped fields, perform approved import without overwriting old browser data, and re-import without duplicating entries.

**Definition of done:** All six scenarios pass on the user's actual Windows machine, tests pass, no writes occur outside the Atlas-managed root or database/backup destinations, and the user can complete one genuine daily work session with the new flow.

## 9. Implementation order within M1

1. Repository baseline, immutable v1.1 JSON backup, configuration, database schema/migrations, and initial automated test harness.
2. Safe managed file service and read-only reference registry with path security tests.
3. Minimal UI/API vertical slice (create → task → note/link → checkpoint → resume) and explicit ChatGPT handoff.
4. Backup/restore, legacy import preview, failure testing, and local Windows acceptance run.

**Do not replace v1.1 until its records have been exported and the new migration has passed a restore test.**

## 10. Open decisions deferred intentionally

- Whether to distribute as a browser localhost app or desktop wrapper after M1 is proven.
- Google Calendar authentication and event reconciliation in a later milestone.
- Optional study-specific review algorithm and its data model.
- Full-text search of large external directories, with separate indexing consent and resource limits.
- Optional ChatGPT connector subject to product support, user authorization and safe tool restrictions.
