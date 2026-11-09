"""Preview and idempotent, non-destructive import of Atlas Study Workspace v1.1 JSON."""
import hashlib
import json
from pathlib import Path
from uuid import uuid4, uuid5, NAMESPACE_URL
from .database import transaction, one
from .safety import UnsafePath, _reparse_or_link

ARR_KEYS = ('courses', 'topics', 'plan', 'exercises', 'attempts', 'sessions', 'reviews', 'weeklySeeds', 'notes')
MAX_IMPORT = 5_000_000


def validate(raw: bytes):
    if len(raw) > MAX_IMPORT:
        raise ValueError('Legacy JSON exceeds 5 MB')
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ValueError('Not valid JSON') from None
    if not isinstance(data, dict) or data.get('version') != 1:
        raise ValueError('Expected an Atlas v1.1 JSON export with version 1')
    for field in ARR_KEYS:
        value = data.get(field, [])
        if not isinstance(value, list) or len(value) > 10_000:
            raise ValueError(f'Invalid {field} records')
    courses = data.get('courses', [])
    topics = data.get('topics', [])
    if not all(isinstance(x, dict) and isinstance(x.get('id'), str) and isinstance(x.get('name'), str) for x in courses):
        raise ValueError('Invalid course records')
    if not all(isinstance(x, dict) and isinstance(x.get('id'), str) and isinstance(x.get('title'), str) and isinstance(x.get('course'), str) for x in topics):
        raise ValueError('Invalid topic records')
    if len({x['id'] for x in courses}) != len(courses) or len({x['id'] for x in topics}) != len(topics):
        raise ValueError('Duplicate legacy record identifiers')
    unknown = set(data) - set(ARR_KEYS) - {'version', 'created', 'lastSaved', 'resumeId'}
    return data, sorted(unknown)


def preview(raw: bytes, db: Path | None = None):
    data, unknown = validate(raw)
    digest = hashlib.sha256(raw).hexdigest()
    course_ids = {x['id'] for x in data.get('courses', [])}
    orphan_topics = [x['id'] for x in data.get('topics', []) if x['course'] not in course_ids]
    if orphan_topics:
        raise ValueError('Topics refer to missing courses')
    existing = one(db, 'SELECT digest FROM legacy_imports ORDER BY imported_at DESC LIMIT 1') if db else None
    return {'digest': digest, 'already_imported': bool(existing and existing['digest'] == digest),
            'different_legacy_export_already_imported': bool(existing and existing['digest'] != digest),
            'map_to_workspaces': len(data.get('courses', [])),
            'map_to_tasks': len(data.get('topics', [])),
            'archived_only': {k: len(data.get(k, [])) for k in ARR_KEYS if k not in ('courses','topics')},
            'additional_fields_preserved': unknown,
            'notice': 'Full original JSON is archived; plan, quizzes, review and session records are preserved but not active v2 features.'}


def apply(root: Path, db: Path, raw: bytes):
    result = preview(raw, db)
    if result['already_imported']:
        return {**result, 'imported': False}
    if result['different_legacy_export_already_imported']:
        raise ValueError('Another v1.1 export was already imported. Importing a different export would duplicate records; use a new profile or a future merge flow.')
    data, _ = validate(raw)
    digest = result['digest']
    archive = root / 'imports' / 'legacy' / (digest + '.json')
    if _reparse_or_link(root) or _reparse_or_link(root / 'imports') or _reparse_or_link(archive.parent):
        raise ValueError('Legacy import folder is a symlink/reparse point')
    archive.parent.mkdir(parents=True, exist_ok=True)
    if _reparse_or_link(archive):
        raise ValueError('Legacy import target is a symlink/reparse point')
    if archive.exists():
        if archive.read_bytes() != raw:
            raise ValueError('Existing legacy archive mismatch')
    else:
        # Exclusive creation preserves all prior exports and avoids silent replacement.
        with archive.open('xb') as stream:
            stream.write(raw)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    ns = uuid5(NAMESPACE_URL, 'atlas-v1-' + digest)
    courses = data.get('courses', [])
    topics = data.get('topics', [])
    by_course = {}
    with transaction(db) as conn:
        if conn.execute('SELECT digest FROM legacy_imports WHERE digest=?', (digest,)).fetchone():
            return {**result, 'imported': False}
        for item in courses:
            wid = str(uuid5(ns, 'course-' + item['id']))
            by_course[item['id']] = wid
            conn.execute('INSERT INTO workspaces(id,name,description,kind_label,created_at,updated_at) VALUES (?,?,?,?,?,?)',
                         (wid, item['name'][:160], str(item.get('description') or '')[:2000], 'Learning (imported)', now, now))
        statuses = {'todo':'todo','active':'doing','covered':'doing','review':'blocked','verified':'done'}
        for item in topics:
            tid = str(uuid5(ns, 'topic-' + item['id']))
            status = statuses.get(item.get('status'), 'todo')
            due = item.get('due')
            if not isinstance(due, str) or len(due) != 10:
                due = None
            evidence = str(item.get('evidence') or '')
            details = f"Imported status: {item.get('status','unknown')}\nEvidence: {evidence}"[:5000]
            conn.execute('''INSERT INTO tasks(id,workspace_id,title,status,priority,due_on,next_action,details,created_at,updated_at)
                            VALUES (?,?,?,?,?,?,?,?,?,?)''', (tid, by_course[item['course']], item['title'][:200], status, 2, due,
                            str(item.get('nextAction') or '')[:2000], details, now, now))
        resume = next((x for x in topics if x['id'] == data.get('resumeId')), None)
        if resume:
            conn.execute('INSERT INTO checkpoints VALUES (?,?,?,?,?,?,?)', (str(uuid4()), by_course[resume['course']],
                         'Imported v1.1 resume topic: '+resume['title'][:200], str(resume.get('nextAction') or 'Resume imported topic')[:2000], '', str(resume.get('evidence') or '')[:5000], now))
        conn.execute('INSERT INTO legacy_imports VALUES (?,?,?,?,?,?)', (digest, now, str(archive.relative_to(root)),
                         len(courses), len(topics), json.dumps(result['archived_only'])))
    return {**result, 'imported': True}
