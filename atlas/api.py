"""Loopback-only Atlas API with same-origin write controls."""
import base64
import os
import re
import secrets
from datetime import date
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, Field, field_validator

from . import backup, legacy
from .service import WorkspaceService, NotFound, Conflict

PORT = int(os.getenv('ATLAS_PORT','8766'))
DEFAULT_ROOT = Path.home() / 'Documents' / 'Atlas-v2'
DATA_ROOT = Path(os.getenv('ATLAS_DATA_HOME', str(DEFAULT_ROOT)))
TOKEN = secrets.token_urlsafe(32)
STATIC = Path(__file__).resolve().parent.parent / 'static'
app = FastAPI(title='Atlas Workspace', version='2.0.0-m1', docs_url=None, redoc_url=None, openapi_url=None)
service = WorkspaceService(DATA_ROOT)


@app.middleware('http')
async def local_gate(request: Request, call_next):
    host = request.headers.get('host','').lower()
    # Host header check blocks DNS rebinding through arbitrary names.
    if host not in {f'127.0.0.1:{PORT}',f'localhost:{PORT}', '127.0.0.1','localhost','testserver'}:
        return Response('Invalid Host',status_code=403)
    origin = request.headers.get('origin')
    if origin:
        parsed = urlparse(origin)
        if parsed.scheme != 'http' or parsed.netloc.lower() not in {f'127.0.0.1:{PORT}',f'localhost:{PORT}','testserver'}:
            return Response('Invalid Origin',status_code=403)
    if request.method in {'POST','PATCH','PUT','DELETE'}:
        if request.headers.get('x-atlas-token') != TOKEN:
            return Response('Missing or invalid local write token',status_code=403)
        length = request.headers.get('content-length')
        if length and (not length.isdecimal() or int(length)>25_000_000):
            return Response('Request too large',status_code=413)
        if 'application/json' not in request.headers.get('content-type',''):
            return Response('JSON content type required',status_code=415)
    result = await call_next(request)
    result.headers['Cache-Control']='no-store'
    result.headers['X-Content-Type-Options']='nosniff'
    result.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"
    return result


@app.exception_handler(NotFound)
async def on_missing(_request, exc):
    return Response(str(exc),status_code=404)


@app.exception_handler(Conflict)
async def on_conflict(_request, exc):
    return Response(str(exc),status_code=409)


@app.exception_handler(ValueError)
async def on_invalid(_request, exc):
    return Response(str(exc),status_code=400)


class WorkspaceIn(BaseModel):
    name: str = Field(min_length=1,max_length=160)
    description: str = Field(default='',max_length=2000)
    kind_label: str = Field(default='',max_length=80)

class WorkspacePatch(BaseModel):
    name: str | None = Field(default=None,min_length=1,max_length=160)
    description: str | None = Field(default=None,max_length=2000)
    kind_label: str | None = Field(default=None,max_length=80)
    archived: bool | None = None

class TaskIn(BaseModel):
    title: str = Field(min_length=1,max_length=200)
    status: Literal['todo','doing','blocked','done'] = 'todo'
    priority: int = Field(default=2,ge=1,le=3)
    due_on: date | None = None
    next_action: str = Field(default='',max_length=2000)
    details: str = Field(default='',max_length=5000)

class TaskPatch(BaseModel):
    title: str | None = Field(default=None,min_length=1,max_length=200)
    status: Literal['todo','doing','blocked','done'] | None = None
    priority: int | None = Field(default=None,ge=1,le=3)
    due_on: date | None = None
    next_action: str | None = Field(default=None,max_length=2000)
    details: str | None = Field(default=None,max_length=5000)

class CheckpointIn(BaseModel):
    summary: str = Field(min_length=1,max_length=2000)
    next_action: str = Field(min_length=1,max_length=2000)
    blocker: str = Field(default='',max_length=2000)
    evidence: str = Field(default='',max_length=5000)

class NoteIn(BaseModel):
    title: str = Field(min_length=1,max_length=160)
    content: str = Field(default='',max_length=350000)

class NoteUpdate(NoteIn):
    expected_version: int = Field(ge=1)

class ReferenceIn(BaseModel):
    display_name: str = Field(min_length=1,max_length=160)
    target_path: str = Field(min_length=1,max_length=2000)

class ArchivePayload(BaseModel):
    data_base64: str = Field(min_length=1,max_length=24_000_000)

class HandoffIn(BaseModel):
    selected_note_ids: list[str] = Field(default_factory=list,max_length=10)


def from_base64(payload: ArchivePayload):
    try:
        return base64.b64decode(payload.data_base64,validate=True)
    except Exception as exc:
        raise ValueError('Invalid base64 payload') from exc


def export_task_model(payload: TaskIn | TaskPatch):
    data=payload.model_dump(exclude_unset=isinstance(payload,TaskPatch))
    if 'due_on' in data and data['due_on'] is not None:
        data['due_on']=data['due_on'].isoformat()
    if isinstance(payload, TaskPatch):
        for key in ('title','status','priority','next_action','details'):
            if key in data and data[key] is None:
                raise ValueError(f'{key} cannot be null')
    return data


@app.get('/')
def index():return FileResponse(STATIC/'index.html',media_type='text/html')

@app.get('/static/{filename}')
def static_file(filename: Literal['app.js','styles.css']):
    media = 'text/javascript' if filename=='app.js' else 'text/css'
    return FileResponse(STATIC/filename,media_type=media)

@app.get('/api/v1/bootstrap')
def bootstrap():
    return {'version':'2.0.0-m1','write_token':TOKEN,'data_root':str(service.root),
            'message':'Offline local workspace. No AI API connection.'}

@app.get('/api/v1/today')
def today():return service.today()

@app.get('/api/v1/workspaces')
def workspaces():return service.list_workspaces()

@app.post('/api/v1/workspaces',status_code=201)
def create_workspace(payload: WorkspaceIn):return service.create_workspace(**payload.model_dump())

@app.get('/api/v1/workspaces/{wid}')
def get_workspace(wid: str):return service.workspace_detail(wid)

@app.patch('/api/v1/workspaces/{wid}')
def patch_workspace(wid: str,payload: WorkspacePatch):return service.update_workspace(wid,payload.model_dump(exclude_unset=True))

@app.post('/api/v1/workspaces/{wid}/tasks',status_code=201)
def create_task(wid: str,payload: TaskIn):return service.create_task(wid,**export_task_model(payload))

@app.patch('/api/v1/tasks/{tid}')
def patch_task(tid: str,payload: TaskPatch):return service.update_task(tid,export_task_model(payload))

@app.post('/api/v1/workspaces/{wid}/checkpoints',status_code=201)
def create_checkpoint(wid: str,payload: CheckpointIn):return service.add_checkpoint(wid,**payload.model_dump())

@app.post('/api/v1/workspaces/{wid}/notes',status_code=201)
def create_note(wid: str,payload: NoteIn):return service.create_note(wid,**payload.model_dump())

@app.get('/api/v1/notes/{nid}')
def get_note(nid: str):return service.get_note(nid)

@app.put('/api/v1/notes/{nid}')
def update_note(nid: str,payload: NoteUpdate):return service.update_note(nid,**payload.model_dump())

@app.post('/api/v1/workspaces/{wid}/references',status_code=201)
def add_reference(wid: str,payload: ReferenceIn):return service.add_reference(wid,**payload.model_dump())

@app.get('/api/v1/search')
def search(q: str = ''):return service.search(q[:120])

@app.post('/api/v1/workspaces/{wid}/handoff')
def handoff(wid: str,payload: HandoffIn):return {'text':service.handoff(wid,payload.selected_note_ids)}

@app.get('/api/v1/backup')
def download_backup():
    with service.lock:
        data=backup.make_backup(service.root,service.db)
    return Response(data,media_type='application/zip',headers={'Content-Disposition':'attachment; filename="atlas-v2-backup.zip"'})

@app.post('/api/v1/backup/stage')
def stage_backup(payload: ArchivePayload):
    raw=from_base64(payload)
    dest_folder=service.root/'staged_restores'
    dest_folder.mkdir(parents=True,exist_ok=True)
    return backup.restore_to_new_directory(raw,dest_folder/('restore-'+secrets.token_hex(8)))

@app.post('/api/v1/legacy/preview')
def preview_legacy(payload: ArchivePayload):return legacy.preview(from_base64(payload),service.db)

@app.post('/api/v1/legacy/import')
def import_legacy(payload: ArchivePayload):
    from datetime import datetime, timezone
    from .safety import _reparse_or_link
    raw=from_base64(payload)
    with service.lock:
        p=legacy.preview(raw,service.db)
        if p['already_imported']:
            return {**p,'imported':False}
        if p['different_legacy_export_already_imported']:
            raise ValueError('Different legacy export already imported. Refusing a second import to prevent duplicates.')
        folder=service.root/'backups'
        if _reparse_or_link(folder):
            raise ValueError('Backups folder cannot be a symlink')
        folder.mkdir(parents=True,exist_ok=True)
        archive=backup.make_backup(service.root,service.db)
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        snapshot=folder/f'before-legacy-{stamp}.zip'
        with snapshot.open('xb') as dest:
            dest.write(archive)
        result=legacy.apply(service.root,service.db,raw)
        return {**result,'pre_import_backup':str(snapshot)}


@app.post('/api/v1/references/{rid}/reveal')
def reveal_external(rid: str):
    """Explicitly show the containing folder in the system file manager; never execute the target."""
    import subprocess
    import sys
    from .database import one
    from .safety import reference_info
    record=one(service.db,'SELECT * FROM file_references WHERE id=?',(rid,))
    if not record:
        raise NotFound('Reference not found')
    path=Path(record['target_path'])
    if not path.exists():
        raise NotFound('Linked resource no longer exists; relocate it using your file manager')
    folder=path if path.is_dir() else path.parent
    if sys.platform == 'win32':
        # Opens a directory, never launches a potentially executable linked file.
        os.startfile(str(folder))
    elif sys.platform == 'darwin':
        subprocess.Popen(['open',str(folder)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    else:
        subprocess.Popen(['xdg-open',str(folder)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    return {'opened_directory':str(folder)}
