# Atlas M2 local bridge

This source copy adds `atlas_bridge.py` to the M1 app. It uses the existing loopback Atlas API. It does not call a paid AI API or automatically expose your linked files to ChatGPT.

## Set up

1. Keep your current Atlas data directory and M1 installation intact. Back up Atlas using **Data & backup**.
2. Use this M2 source folder as a separate installation. Install `requirements.txt` in a virtual environment and run `start_atlas.py` as in the original README. Stop M1 before starting M2 because both use port 8766. The default data home remains `Documents\Atlas-v2`; set `ATLAS_DATA_HOME` if your M1 uses a different one.
3. Save the **Process Management** task in the Linux Programming workspace. The live workspace inspected on 2026-11-09 had no saved tasks or checkpoints, so there was no task ID to use yet.
4. Obtain the workspace and task IDs from the local Atlas JSON endpoint or a future UI. The workspace observed during inspection was `d8003da3-9b5a-4db5-a111-f8bef07dcfb5`.

Run commands from this folder with `python atlas_bridge.py WORKSPACE_ID TASK_ID ...`.

- `context` prints that task, the latest workspace checkpoint, and linked resource names/IDs. It does not read linked contents.
- `read REFERENCE_ID relative\file.md` checks that the exact file belongs to a reference in this workspace, blocks traversal and symlinks, and asks for `READ` before displaying contents. Use `.` for a directly linked file. Supported text files only, maximum 2 MB.
- `propose proposal.json` checks and displays the planned checkpoint and file registrations without writing.
- `apply proposal.json` displays the same proposal and requires `APPROVE`. It then adds a checkpoint and registers paths to existing result files. It does not edit those files or change task status.

Example proposal (replace IDs and file path with real values):

```json
{
  "workspace_id": "WORKSPACE_ID",
  "task_id": "TASK_ID",
  "checkpoint": {
    "summary": "Reviewed process management material; no lesson marked complete",
    "next_action": "Continue the Process Management exercise",
    "blocker": "",
    "evidence": "Review notes drafted"
  },
  "files": [
    {"display_name": "Process Management review draft", "path": "C:\\absolute\\path\\to\\review.md"}
  ]
}
```

## Limits

The current ChatGPT in-app browser exposed no WebMCP tools for the running M1 page. This bridge is an explicit local command workflow, not a site tool that ChatGPT can invoke automatically. The running M1 server was inspected but not replaced or restarted. Live writeback was not attempted because the named task does not yet exist and no session result has been approved. A checkpoint followed by multiple file registrations is not atomic; if a later registration fails, inspect Atlas and reconcile before retrying to avoid duplicate checkpoints.

The existing M1 `/api/v1/bootstrap` provides a session write token to local clients. Keep Atlas bound to loopback and do not expose port 8766 to your network. Linked resource paths are metadata until the exact file is explicitly selected for reading.
