"""Isolated M1 acceptance and security regression tests. Run with pytest -q."""
import base64
import hashlib
import io
import json
import os
import sqlite3
import stat
import subprocess
import sys
import zipfile
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from atlas import api, backup, legacy
from atlas.service import WorkspaceService
from atlas.safety import managed_note_path, write_note, read_note, UnsafePath


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    s=WorkspaceService(tmp_path/'profile')
    monkeypatch.setattr(api,'service',s)
    c=TestClient(api.app)
    h={'X-Atlas-Token':api.TOKEN}
    return s,c,h


def put_workspace(c,h,name='Software engineering'):
    r=c.post('/api/v1/workspaces',headers=h,json={'name':name,'kind_label':'Custom'})
    assert r.status_code==201,r.text
    return r.json()['id']


def test_loopback_origin_token_security(ctx):
    s,c,h=ctx
    assert c.get('/api/v1/bootstrap').status_code==200
    assert c.post('/api/v1/workspaces',json={'name':'Unsafe'}).status_code==403
    assert c.post('/api/v1/workspaces',headers={**h,'origin':'https://attacker.example'},json={'name':'Unsafe'}).status_code==403
    assert c.post('/api/v1/workspaces',headers={**h,'host':'evil.example'},json={'name':'Unsafe'}).status_code==403
    assert c.post('/api/v1/workspaces',headers=h,json={'name':'Allowed'}).status_code==201
    assert 'OpenAI' not in str(c.get('/api/v1/bootstrap').json())


def test_generic_workspaces_tasks_resume(ctx):
    s,c,h=ctx
    first=put_workspace(c,h,'Database practice')
    second=put_workspace(c,h,'MBB engineering')
    t=c.post(f'/api/v1/workspaces/{second}/tasks',headers=h,json={
        'title':'Document ownership','status':'doing','priority':1,'next_action':'Write authoritative service contract'})
    assert t.status_code==201
    cp=c.post(f'/api/v1/workspaces/{second}/checkpoints',headers=h,json={
        'summary':'Mapped key boundaries','next_action':'Draft service interface','evidence':'architecture.md'})
    assert cp.status_code==201
    before=c.get(f'/api/v1/workspaces/{second}').json()
    restarted=WorkspaceService(s.root)
    after=restarted.workspace_detail(second)
    assert after['checkpoints'][0]['next_action']=='Draft service interface'
    assert before['tasks'][0]['id']==after['tasks'][0]['id']
    assert c.get('/api/v1/today').json()['tasks'][0]['title']=='Document ownership'
    assert c.patch('/api/v1/tasks/'+t.json()['id'],headers=h,json={'status':'done'}).status_code==200
    assert c.get('/api/v1/today').json()['tasks']==[]
    assert first!=second


def test_managed_markdown_conflict_and_path_safety(ctx,tmp_path):
    s,c,h=ctx
    wid=put_workspace(c,h)
    r=c.post(f'/api/v1/workspaces/{wid}/notes',headers=h,json={'title':'Paper note','content':'# Original\n'})
    assert r.status_code==201,r.text
    nid=r.json()['id']
    path=managed_note_path(s.root,nid)
    assert path.read_text()=='# Original\n'
    assert c.put('/api/v1/notes/'+nid,headers=h,json={'title':'Paper note','content':'# Revised','expected_version':1}).status_code==200
    assert c.put('/api/v1/notes/'+nid,headers=h,json={'title':'Paper note','content':'# Overwrite','expected_version':1}).status_code==409
    assert path.read_text()=='# Revised'
    assert c.put('/api/v1/notes/'+nid,headers=h,json={'title':'Oversized','content':'文'*200000,'expected_version':2}).status_code==400
    assert path.read_text()=='# Revised'
    for bad in ['../outside.md','/tmp/escape.md','00000000-0000-0000-0000-000000000000/../../test.md']:
        with pytest.raises(UnsafePath):managed_note_path(s.root,bad)
    outside=tmp_path/'outside.md';outside.write_text('DO NOT CHANGE')
    path.unlink()
    try:
        path.symlink_to(outside)
    except (NotImplementedError,OSError):
        pytest.skip('Symlinks require elevated privileges on this host')
    assert c.put('/api/v1/notes/'+nid,headers=h,json={'title':'Test','content':'Attack','expected_version':2}).status_code==400
    assert outside.read_text()=='DO NOT CHANGE'


def test_external_link_readonly_missing_and_handoff(ctx,tmp_path):
    s,c,h=ctx
    wid=put_workspace(c,h)
    project=tmp_path/'existing-project'
    project.mkdir();(project/'README.md').write_bytes(b'Original project bytes')
    subprocess.run(['git','init','-q',str(project)],check=True)
    before=(project/'README.md').read_bytes()
    r=c.post(f'/api/v1/workspaces/{wid}/references',headers=h,json={'display_name':'Existing repo','target_path':str(project)})
    assert r.status_code==201,r.text
    assert r.json()['exists'] is True
    assert (project/'README.md').read_bytes()==before
    assert c.get('/api/v1/search?q=existing').json()['references'][0]['display_name']=='Existing repo'
    note=c.post(f'/api/v1/workspaces/{wid}/notes',headers=h,json={'title':'Context','content':'Private note: selected only'})
    nid=note.json()['id']
    plain=c.post(f'/api/v1/workspaces/{wid}/handoff',headers=h,json={}).json()['text']
    assert 'Private note:' not in plain
    selected=c.post(f'/api/v1/workspaces/{wid}/handoff',headers=h,json={'selected_note_ids':[nid]}).json()['text']
    assert 'Private note:' in selected
    assert c.post(f'/api/v1/workspaces/{wid}/handoff',headers=h,json={'selected_note_ids':[str(uuid4())]}).status_code==400
    project.rename(tmp_path/'renamed-project')
    assert c.get(f'/api/v1/workspaces/{wid}').json()['references'][0]['exists'] is False


def test_backup_restore_integrity_and_external_reference_missing(ctx,tmp_path):
    s,c,h=ctx
    wid=put_workspace(c,h)
    note=c.post(f'/api/v1/workspaces/{wid}/notes',headers=h,json={'title':'Critical','content':'# Atomic knowledge\nKeep this'})
    c.post(f'/api/v1/workspaces/{wid}/references',headers=h,json={'display_name':'Gone','target_path':str(tmp_path/'missing-file')})
    package=c.get('/api/v1/backup').content
    assert len(package)>100
    restored=backup.restore_to_new_directory(package,tmp_path/'restored-profile')
    assert len(restored['missing_external_references'])==1
    recovery=WorkspaceService(tmp_path/'restored-profile')
    assert recovery.get_note(note.json()['id'])['content']=='# Atomic knowledge\nKeep this'
    assert recovery.workspace_detail(wid)['references'][0]['exists'] is False
    assert c.get(f'/api/v1/workspaces/{wid}').status_code==200
    with pytest.raises(ValueError,match='must not exist'):
        backup.restore_to_new_directory(package,tmp_path/'restored-profile')
    with zipfile.ZipFile(io.BytesIO(package)) as z:
        assert all('missing-file' not in x or x=='database.sqlite3' for x in z.namelist())
    raw=b'bad';assert c.post('/api/v1/backup/stage',headers=h,json={'data_base64':base64.b64encode(raw).decode()}).status_code==400


def test_zip_slip_and_checksum_rejected(ctx,tmp_path):
    s,c,h=ctx
    put_workspace(c,h)
    package=c.get('/api/v1/backup').content
    with zipfile.ZipFile(io.BytesIO(package)) as z:
        original={name:z.read(name) for name in z.namelist()}
    def create(m):
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w') as z:
            for name,v in m.items():z.writestr(name,v)
        return buf.getvalue()
    bad=dict(original);bad['../escape.txt']=b'attack'
    with pytest.raises(ValueError,match='Invalid archive member'):
        backup.verify_backup(create(bad))
    bad=dict(original);bad['database.sqlite3']=bad['database.sqlite3']+b'change'
    with pytest.raises(ValueError,match='integrity'):
        backup.verify_backup(create(bad))
    assert not (tmp_path/'escape.txt').exists()


def sample_legacy():
    return {'version':1,'courses':[{'id':'db','name':'Databases'},{'id':'dev','name':'Coding'}],
      'topics':[{'id':'sql','course':'db','title':'SQL joins','status':'review','nextAction':'Run a JOIN','evidence':'Join confusion','due':'2026-11-10'}],
      'plan':[{'id':'w1','date':'2026-11-10','title':'Review','minutes':25}],
      'exercises':[{'id':'ex1','course':'db','prompt':'SQL','title':'SQL practice','rubric':['Check JOIN']}],
      'attempts':[], 'sessions':[], 'reviews':[], 'weeklySeeds':[], 'notes':[],
      'resumeId':'sql','customFutureExtension':{'keep':True}}


def test_legacy_preview_import_idempotent_preserves_full_archive(ctx):
    s,c,h=ctx
    raw=json.dumps(sample_legacy()).encode()
    payload={'data_base64':base64.b64encode(raw).decode()}
    p=c.post('/api/v1/legacy/preview',headers=h,json=payload)
    assert p.status_code==200,p.text
    assert p.json()['map_to_workspaces']==2
    assert p.json()['archived_only']['exercises']==1
    assert 'customFutureExtension' in p.json()['additional_fields_preserved']
    result=c.post('/api/v1/legacy/import',headers=h,json=payload)
    assert result.status_code==200,result.text
    assert result.json()['imported'] is True
    assert len(c.get('/api/v1/workspaces').json())==2
    assert c.post('/api/v1/legacy/import',headers=h,json=payload).json()['imported'] is False
    assert len(c.get('/api/v1/workspaces').json())==2
    assert c.get('/api/v1/workspaces').json()[0]['open_tasks']+c.get('/api/v1/workspaces').json()[1]['open_tasks']==1
    digest=hashlib.sha256(raw).hexdigest()
    assert (s.root/'imports'/'legacy'/f'{digest}.json').read_bytes()==raw
    package=c.get('/api/v1/backup').content
    with zipfile.ZipFile(io.BytesIO(package)) as z:
        assert z.read(f'imports/legacy/{digest}.json')==raw
    bad=dict(sample_legacy());bad['topics'][0]['course']='unknown'
    rr=c.post('/api/v1/legacy/preview',headers=h,json={'data_base64':base64.b64encode(json.dumps(bad).encode()).decode()})
    assert rr.status_code==400


def test_search_archiving_and_schema(ctx):
    s,c,h=ctx
    wid=put_workspace(c,h,'Writing journal')
    c.post(f'/api/v1/workspaces/{wid}/notes',headers=h,json={'title':'Morning note','content':'Research question: recursion and Python'})
    assert c.get('/api/v1/search?q=recursion').json()['notes'][0]['title']=='Morning note'
    r=c.patch(f'/api/v1/workspaces/{wid}',headers=h,json={'archived':True})
    assert r.status_code==200
    assert c.get('/api/v1/today').json()['workspaces']==[]
    assert c.patch(f'/api/v1/workspaces/{wid}',headers=h,json={'archived':False}).status_code==200
    with sqlite3.connect(s.db) as con:
        assert con.execute('PRAGMA foreign_keys').fetchone()[0] in (0,1)
        assert con.execute('PRAGMA user_version').fetchone()[0]==1


def test_canonical_v1_1_seed_preview(ctx):
    s,c,h=ctx
    sample=Path(__file__).resolve().parents[1]/'legacy'/'v1_1_STARTER_SAMPLE_NOT_USER_DATA.json'
    raw=sample.read_bytes()
    p=legacy.preview(raw,s.db)
    assert p['map_to_workspaces']==5
    assert p['map_to_tasks']==23
    result=legacy.apply(s.root,s.db,raw)
    assert result['imported'] is True
    assert len(s.list_workspaces())==5
    assert sum(x['open_tasks'] for x in s.list_workspaces())>=20


def test_security_controls_static_endpoints(ctx):
    s,c,h=ctx
    for url in ('/','/static/styles.css','/static/app.js'):
        r=c.get(url)
        assert r.status_code==200,r.text[:300]
        assert "frame-ancestors 'none'" in r.headers['Content-Security-Policy']
    assert c.get('/api/v1/search?q=anything').status_code==200
    assert c.get('/static/../../etc/passwd').status_code in (404,422)
