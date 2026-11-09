"""Snapshot owned data and stage verified restores; linked external contents are never copied."""
import hashlib
import io
import json
import os
import re
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .database import connect
from .safety import managed_note_path, _reparse_or_link

MAX_ARCHIVE_BYTES = 18_000_000
MAX_EXPANDED_BYTES = 50_000_000
SAFE_NOTE = re.compile(r'^managed/notes/[0-9a-f-]{36}\.md$')
SAFE_LEGACY = re.compile(r'^imports/legacy/[a-f0-9]{64}\.json$')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def make_backup(root: Path, db: Path):
    contents = {}
    with tempfile.TemporaryDirectory() as td:
        snapshot = Path(td) / 'database.sqlite3'
        with connect(db) as live, sqlite3.connect(snapshot) as dest:
            live.backup(dest)
        contents['database.sqlite3'] = snapshot.read_bytes()
    for subdir, pat in [('managed/notes', SAFE_NOTE), ('imports/legacy', SAFE_LEGACY)]:
        directory = root / subdir
        if not directory.exists():
            continue
        if _reparse_or_link(directory):
            raise ValueError('Cannot back up a symlinked managed directory')
        for path in directory.iterdir():
            if _reparse_or_link(path) or not path.is_file():
                raise ValueError(f'Unsafe file in managed archive: {path.name}')
            name = f'{subdir}/{path.name}'
            if not pat.fullmatch(name):
                raise ValueError('Unexpected managed filename in backup')
            contents[name] = path.read_bytes()
    if sum(map(len, contents.values())) > MAX_EXPANDED_BYTES:
        raise ValueError('Backup exceeds 50 MB safety limit')
    manifest = {'format': 'atlas-m1-backup', 'version': 1,
                'created_at': datetime.now(timezone.utc).isoformat(),
                'external_reference_contents_included': False,
                'files': {name: {'bytes': len(value), 'sha256': sha(value)} for name, value in sorted(contents.items())}}
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in contents.items():
            archive.writestr(name, data)
        archive.writestr('manifest.json', json.dumps(manifest, indent=2))
    result = out.getvalue()
    if len(result) > MAX_ARCHIVE_BYTES:
        raise ValueError('Compressed backup exceeds 18 MB upload limit')
    return result


def verify_backup(raw: bytes):
    if len(raw) > MAX_ARCHIVE_BYTES:
        raise ValueError('Archive exceeds 18 MB limit')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            names = [i.filename for i in entries]
            if len(names) != len(set(names)) or len(names) > 4000:
                raise ValueError('Archive has duplicate or excessive entries')
            if 'manifest.json' not in names or 'database.sqlite3' not in names:
                raise ValueError('Missing manifest or database')
            for item in entries:
                name = item.filename
                if name not in ('manifest.json','database.sqlite3') and not (SAFE_NOTE.fullmatch(name) or SAFE_LEGACY.fullmatch(name)):
                    raise ValueError('Invalid archive member name')
                if item.is_dir() or (item.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError('Archive contains symlink or directory member')
            if sum(i.file_size for i in entries) > MAX_EXPANDED_BYTES:
                raise ValueError('Expanded archive too large')
            manifest = json.loads(archive.read('manifest.json'))
            if manifest.get('format') != 'atlas-m1-backup' or manifest.get('version') != 1 or not isinstance(manifest.get('files'), dict):
                raise ValueError('Unknown backup format')
            if set(manifest['files']) != set(names)-{'manifest.json'}:
                raise ValueError('Manifest file list mismatch')
            content = {}
            for name, meta in manifest['files'].items():
                if not isinstance(meta, dict) or not isinstance(meta.get('bytes'), int) or not isinstance(meta.get('sha256'), str):
                    raise ValueError('Malformed manifest entry')
                value = archive.read(name)
                if len(value) != meta['bytes'] or sha(value) != meta['sha256']:
                    raise ValueError('Backup integrity check failed')
                content[name] = value
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as exc:
        raise ValueError('Invalid or corrupted backup archive') from exc
    # Check SQLite integrity before writing anything.
    with tempfile.TemporaryDirectory() as td:
        temp_db = Path(td) / 'verify.db'
        temp_db.write_bytes(content['database.sqlite3'])
        with sqlite3.connect(f'file:{temp_db}?mode=ro', uri=True) as conn:
            if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('SQLite database failed integrity check')
            if conn.execute('PRAGMA user_version').fetchone()[0] != 1:
                raise ValueError('Unsupported Atlas schema in backup')
    return content, manifest


def restore_to_new_directory(raw: bytes, target: Path):
    content, manifest = verify_backup(raw)
    target = Path(target).absolute()
    if target.exists():
        raise ValueError('Restore target must not exist; never overwrite an active Atlas profile')
    if not target.parent.is_dir() or _reparse_or_link(target.parent):
        raise ValueError('Restore parent directory is unsafe')
    tmp = target.parent / ('.atlas-restore-' + str(uuid4()))
    tmp.mkdir(mode=0o700)
    try:
        for name, value in content.items():
            path = tmp.joinpath(*name.split('/'))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(value)
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            import shutil
            shutil.rmtree(tmp)
    with sqlite3.connect(target / 'database.sqlite3') as conn:
        external = conn.execute('SELECT target_path FROM file_references').fetchall()
    missing = [str(p[0]) for p in external if not Path(p[0]).exists()]
    return {'destination': str(target), 'owned_files': len(content), 'missing_external_references': missing,
            'notice': 'Staged only. Current Atlas profile has not been replaced.'}
