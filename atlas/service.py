"""Validated, provider-free workspace operations."""
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from . import database as db
from .safety import read_note, write_note, normalize_reference, reference_info, managed_note_path


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return str(uuid4())


class NotFound(ValueError):
    pass


class Conflict(ValueError):
    pass


class WorkspaceService:
    def __init__(self, data_root):
        self.root = Path(data_root).expanduser().absolute()
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink():
            raise ValueError('Atlas data root may not be a symlink')
        self.db = self.root / 'database.sqlite3'
        db.migrate(self.db)
        self.lock = threading.RLock()

    def workspace(self, wid):
        record = db.one(self.db, 'SELECT * FROM workspaces WHERE id=?', (wid,))
        if not record:
            raise NotFound('Workspace not found')
        return record

    def _record(self, conn, wid, category, related, summary):
        conn.execute('INSERT INTO activity_events VALUES (?,?,?,?,?,?)', (uid(), wid, category, related, summary[:300], now()))

    def create_workspace(self, name, description='', kind_label=''):
        wid, stamp = uid(), now()
        with self.lock, db.transaction(self.db) as conn:
            conn.execute('INSERT INTO workspaces(id,name,description,kind_label,created_at,updated_at) VALUES (?,?,?,?,?,?)',
                         (wid,name,description,kind_label,stamp,stamp))
            self._record(conn, wid, 'workspace.created', wid, name)
        return self.workspace(wid)

    def update_workspace(self, wid, changes):
        with self.lock, db.transaction(self.db) as conn:
            row = conn.execute('SELECT id FROM workspaces WHERE id=?',(wid,)).fetchone()
            if not row: raise NotFound('Workspace not found')
            keys = ['name','description','kind_label']
            values = {k: changes[k] for k in keys if k in changes and changes[k] is not None}
            if 'archived' in changes and changes['archived'] is not None:
                values['archived_at'] = now() if changes['archived'] else None
            if values:
                values['updated_at'] = now()
                conn.execute('UPDATE workspaces SET '+','.join(f'{k}=?' for k in values)+' WHERE id=?', (*values.values(),wid))
                self._record(conn,wid,'workspace.updated',wid,'Workspace updated')
        return self.workspace(wid)

    def list_workspaces(self):
        out = db.rows(self.db, '''SELECT w.*, (SELECT count(*) FROM tasks t WHERE t.workspace_id=w.id AND t.status!='done') open_tasks,
          (SELECT c.next_action FROM checkpoints c WHERE c.workspace_id=w.id ORDER BY c.created_at DESC,c.rowid DESC LIMIT 1) resume_action
          FROM workspaces w ORDER BY archived_at IS NOT NULL, updated_at DESC''')
        return out

    def workspace_detail(self, wid):
        w = self.workspace(wid)
        w['tasks'] = db.rows(self.db, 'SELECT * FROM tasks WHERE workspace_id=? ORDER BY status="done",priority,due_on IS NULL,due_on,created_at', (wid,))
        w['notes'] = db.rows(self.db, 'SELECT * FROM notes WHERE workspace_id=? ORDER BY updated_at DESC', (wid,))
        w['references'] = db.rows(self.db, 'SELECT * FROM file_references WHERE workspace_id=? ORDER BY created_at DESC', (wid,))
        for r in w['references']:
            r.update(reference_info(r['target_path']))
        w['checkpoints'] = db.rows(self.db, 'SELECT * FROM checkpoints WHERE workspace_id=? ORDER BY created_at DESC,rowid DESC LIMIT 25', (wid,))
        w['events'] = db.rows(self.db, 'SELECT * FROM activity_events WHERE workspace_id=? ORDER BY created_at DESC,rowid DESC LIMIT 30', (wid,))
        return w

    def create_task(self, wid, title, status='todo', priority=2, due_on=None, next_action='', details=''):
        self.workspace(wid)
        tid, stamp = uid(), now()
        with self.lock, db.transaction(self.db) as conn:
            conn.execute('''INSERT INTO tasks(id,workspace_id,title,status,priority,due_on,next_action,details,created_at,updated_at)
                         VALUES (?,?,?,?,?,?,?,?,?,?)''',(tid,wid,title,status,priority,due_on,next_action,details,stamp,stamp))
            conn.execute('UPDATE workspaces SET updated_at=? WHERE id=?',(stamp,wid))
            self._record(conn,wid,'task.created',tid,title)
        return db.one(self.db,'SELECT * FROM tasks WHERE id=?',(tid,))

    def update_task(self, tid, changes):
        with self.lock, db.transaction(self.db) as conn:
            row = conn.execute('SELECT * FROM tasks WHERE id=?',(tid,)).fetchone()
            if not row: raise NotFound('Task not found')
            allowed = ['title','status','priority','due_on','next_action','details']
            updates = {k:changes[k] for k in allowed if k in changes}
            # None is meaningful only for due_on; reject for other fields at input validation.
            if updates:
                updates['updated_at']=now()
                conn.execute('UPDATE tasks SET '+','.join(f'{k}=?' for k in updates)+' WHERE id=?',(*updates.values(),tid))
                self._record(conn,row['workspace_id'],'task.updated',tid,'Task updated')
        return db.one(self.db,'SELECT * FROM tasks WHERE id=?',(tid,))

    def add_checkpoint(self,wid,summary,next_action,blocker='',evidence=''):
        self.workspace(wid)
        cid, stamp = uid(), now()
        with self.lock, db.transaction(self.db) as conn:
            conn.execute('INSERT INTO checkpoints VALUES (?,?,?,?,?,?,?)',(cid,wid,summary,next_action,blocker,evidence,stamp))
            conn.execute('UPDATE workspaces SET updated_at=? WHERE id=?',(stamp,wid))
            self._record(conn,wid,'checkpoint.created',cid,summary)
        return db.one(self.db,'SELECT * FROM checkpoints WHERE id=?',(cid,))

    def create_note(self,wid,title,content=''):
        self.workspace(wid)
        nid,stamp = uid(),now()
        with self.lock, db.transaction(self.db) as conn:
            write_note(self.root,nid,content)
            conn.execute('INSERT INTO notes VALUES (?,?,?,?,?,?,?)',
                         (nid,wid,title,f'managed/notes/{nid}.md',1,stamp,stamp))
            self._record(conn,wid,'note.created',nid,title)
        return self.get_note(nid)

    def get_note(self,nid):
        row = db.one(self.db,'SELECT * FROM notes WHERE id=?',(nid,))
        if not row: raise NotFound('Note not found')
        row['content']=read_note(self.root,nid)
        return row

    def update_note(self,nid,title,content,expected_version):
        with self.lock, db.transaction(self.db) as conn:
            row = conn.execute('SELECT * FROM notes WHERE id=?',(nid,)).fetchone()
            if not row: raise NotFound('Note not found')
            if row['content_version'] != expected_version: raise Conflict('Note changed since it was opened; reload before saving')
            write_note(self.root,nid,content)
            stamp=now()
            conn.execute('UPDATE notes SET title=?,content_version=content_version+1,updated_at=? WHERE id=?',(title,stamp,nid))
            self._record(conn,row['workspace_id'],'note.updated',nid,title)
        return self.get_note(nid)

    def add_reference(self,wid,display_name,target_path):
        self.workspace(wid)
        path=normalize_reference(target_path)
        kind=reference_info(path)['kind_actual']
        rid,stamp=uid(),now()
        with self.lock,db.transaction(self.db) as conn:
            conn.execute('INSERT INTO file_references VALUES (?,?,?,?,?,?)',(rid,wid,display_name,path,kind,stamp))
            self._record(conn,wid,'reference.linked',rid,display_name)
        out=db.one(self.db,'SELECT * FROM file_references WHERE id=?',(rid,))
        out.update(reference_info(path))
        return out

    def today(self):
        # Stable and explainable: pinned by status then priority, earliest due.
        tasks=db.rows(self.db, '''SELECT t.*,w.name workspace_name,w.archived_at FROM tasks t JOIN workspaces w ON w.id=t.workspace_id
           WHERE t.status!='done' AND w.archived_at IS NULL ORDER BY
           CASE t.status WHEN 'blocked' THEN 1 WHEN 'doing' THEN 0 ELSE 2 END,
           t.priority, t.due_on IS NULL, t.due_on,t.created_at LIMIT 20''')
        workspaces=self.list_workspaces()
        return {'tasks':tasks,'workspaces':[w for w in workspaces if not w['archived_at']]}

    def search(self,term):
        term=term.strip()
        if not term:return {'workspaces':[],'tasks':[],'notes':[],'references':[]}
        like='%'+term.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        def q(table, cols):
            where=' OR '.join(f'{c} LIKE ? ESCAPE "\\"' for c in cols)
            return db.rows(self.db,f'SELECT * FROM {table} WHERE {where} LIMIT 60',(like,)*len(cols))
        notes=q('notes',['title'])
        # Content search only across small, explicitly managed notes; never external paths.
        noted_ids={n['id'] for n in notes}
        for n in db.rows(self.db,'SELECT * FROM notes LIMIT 300'):
            if n['id'] not in noted_ids:
                try:
                    if term.casefold() in read_note(self.root,n['id']).casefold(): notes.append(n)
                except (ValueError,OSError):pass
        return {'workspaces':q('workspaces',['name','description','kind_label']),
                'tasks':q('tasks',['title','next_action','details']),
                'notes':notes[:60], 'references':q('file_references',['display_name'])}

    def handoff(self,wid,note_ids=()):
        info=self.workspace_detail(wid)
        checkpoint=info['checkpoints'][0] if info['checkpoints'] else None
        lines=[f'Workspace: {info["name"]}',info['description']]
        if checkpoint:
            lines.extend(['Latest checkpoint:', 'Result: '+checkpoint['summary'], 'Next action: '+checkpoint['next_action']])
            if checkpoint['blocker']: lines.append('Blocker: '+checkpoint['blocker'])
            if checkpoint['evidence']: lines.append('Evidence: '+checkpoint['evidence'])
        lines.append('Open tasks:')
        for t in (x for x in info['tasks'] if x['status']!='done'):
            lines.append(f'- [{t["status"]}; P{t["priority"]}] {t["title"]} — {t["next_action"] or "Define next action"}')
        if info['references']:
            lines.append('Linked resources (local paths only; contents not transferred):')
            for r in info['references']: lines.append(f'- {r["display_name"]}: {r["target_path"]}')
        if note_ids:
            lines.append('Explicitly selected managed-note excerpts:')
            allowed={n['id'] for n in info['notes']}
            for nid in note_ids:
                if nid not in allowed: raise ValueError('Selected note does not belong to this workspace')
                note=self.get_note(nid)
                lines.append(f'- {note["title"]}:\n{note["content"][:1800]}')
        lines.append('Help me continue from this checkpoint. Do not assume unfinished work is complete; challenge and verify my reasoning where relevant.')
        return '\n'.join(x for x in lines if x)
