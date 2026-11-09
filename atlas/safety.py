"""Path containment and atomic managed-note file I/O."""
import os
import re
import stat
import tempfile
from pathlib import Path
from uuid import UUID

MAX_NOTE_BYTES = 350_000


class UnsafePath(ValueError):
    pass


def _reparse_or_link(path: Path):
    try:
        st = path.lstat()
        return stat.S_ISLNK(st.st_mode) or bool(getattr(st, 'st_file_attributes', 0) & 0x400)
    except FileNotFoundError:
        return False


def managed_note_path(root: Path, note_id: str):
    try:
        canonical = str(UUID(note_id))
    except (ValueError, TypeError, AttributeError):
        raise UnsafePath('Invalid note identifier') from None
    if canonical != note_id:
        raise UnsafePath('Invalid note identifier')
    root = Path(root).absolute()
    folder = root / 'managed' / 'notes'
    target = folder / (canonical + '.md')
    for part in [root, root / 'managed', folder, target]:
        if _reparse_or_link(part):
            raise UnsafePath('Symlink or reparse point blocked in managed path')
    if not target.resolve(strict=False).is_relative_to(root.resolve(strict=False)):
        raise UnsafePath('Managed path leaves data root')
    return target


def write_note(root: Path, note_id: str, content: str):
    encoded = content.encode('utf-8')
    if len(encoded) > MAX_NOTE_BYTES:
        raise ValueError('Note exceeds 350 KB')
    target = managed_note_path(root, note_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    target = managed_note_path(root, note_id)
    fd, tmp_name = tempfile.mkstemp(prefix='.atlas-note-', suffix='.tmp', dir=target.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, 'wb') as file:
            file.write(encoded)
            file.flush()
            os.fsync(file.fileno())
        managed_note_path(root, note_id)  # Repeat validation immediately before replace
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()


def read_note(root: Path, note_id: str):
    target = managed_note_path(root, note_id)
    if not target.exists():
        raise FileNotFoundError('Managed note missing from disk')
    if target.stat().st_size > MAX_NOTE_BYTES:
        raise ValueError('Managed note is larger than safety limit')
    return target.read_text(encoding='utf-8')


def normalize_reference(raw: str):
    if not raw or '\x00' in raw or len(raw) > 2000:
        raise ValueError('Provide a valid existing path or missing-file reference')
    path = Path(raw).expanduser().absolute()
    if not path.is_absolute():
        raise ValueError('External reference must resolve to absolute path')
    # A reference never conveys read/write authority and is not traversed or indexed.
    return str(path)


def reference_info(path: str):
    target = Path(path)
    return {'exists': target.exists(), 'kind_actual': 'directory' if target.is_dir() else 'file' if target.is_file() else 'missing'}
