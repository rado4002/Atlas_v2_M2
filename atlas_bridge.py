"""Human-gated, task-scoped bridge for a local Atlas M1 server.

No AI service or background synchronization is used. Only explicit commands read
linked content or change Atlas records.
"""
import argparse
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE = 'http://127.0.0.1:8766'
MAX_READ = 2_000_000
READABLE = {'.txt', '.md', '.py', '.c', '.h', '.cpp', '.java', '.json', '.csv'}


def api(path, method='GET', body=None, token=None):
    headers = {}
    data = None
    if body is not None:
        data = json.dumps(body).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    if token:
        headers['X-Atlas-Token'] = token
    request = Request(BASE + '/api/v1' + path, data=data, method=method, headers=headers)
    try:
        with urlopen(request, timeout=10) as response:
            return json.load(response)
    except HTTPError as exc:
        raise ValueError(f'Atlas returned {exc.code}: {exc.read(300).decode("utf-8", "replace")}') from exc
    except URLError as exc:
        raise ValueError(f'Atlas is unavailable at {BASE}: {exc.reason}') from exc


def task_context(workspace_id, task_id):
    workspace = api('/workspaces/' + workspace_id)
    task = next((t for t in workspace['tasks'] if t['id'] == task_id), None)
    if task is None:
        raise ValueError('Task does not belong to this workspace or is not saved')
    return {'workspace': {k: workspace[k] for k in ('id', 'name', 'description')},
            'task': task, 'latest_checkpoint': workspace['checkpoints'][0] if workspace['checkpoints'] else None,
            'resources': [{k: r[k] for k in ('id', 'display_name', 'kind', 'exists')}
                          for r in workspace['references']]}


def resolve_linked_file(workspace_id, reference_id, relative):
    workspace = api('/workspaces/' + workspace_id)
    reference = next((r for r in workspace['references'] if r['id'] == reference_id), None)
    if reference is None:
        raise ValueError('Reference does not belong to this workspace')
    root = Path(reference['target_path'])
    if root.is_symlink():
        raise ValueError('Linked root is a symlink')
    if root.is_file():
        if relative not in ('', '.'):
            raise ValueError('A file reference cannot have a relative child path')
        target = root
    elif root.is_dir():
        child = Path(relative)
        if child.is_absolute() or not child.parts or any(p in ('..', '') for p in child.parts):
            raise ValueError('Provide a relative file path inside the linked directory')
        target = root / child
        current = root
        for part in child.parts:
            current = current / part
            if current.is_symlink():
                raise ValueError('Symlink traversal is blocked')
        if not target.resolve().is_relative_to(root.resolve()):
            raise ValueError('File leaves the linked directory')
    else:
        raise ValueError('Linked resource is unavailable')
    if not target.is_file() or target.suffix.lower() not in READABLE:
        raise ValueError('Only existing supported text files can be read')
    if target.stat().st_size > MAX_READ:
        raise ValueError('File exceeds 2 MB read limit')
    return target


def validate_proposal(proposal, workspace_id, task_id):
    if proposal.get('workspace_id') != workspace_id or proposal.get('task_id') != task_id:
        raise ValueError('Proposal does not match the selected task')
    checkpoint = proposal.get('checkpoint')
    if not isinstance(checkpoint, dict):
        raise ValueError('Missing checkpoint')
    if not checkpoint.get('summary') or not checkpoint.get('next_action'):
        raise ValueError('Checkpoint requires summary and next_action')
    if set(checkpoint) - {'summary', 'next_action', 'blocker', 'evidence'}:
        raise ValueError('Unexpected checkpoint field')
    files = proposal.get('files', [])
    if not isinstance(files, list) or len(files) > 10:
        raise ValueError('Provide at most 10 files')
    for file in files:
        if not isinstance(file, dict) or set(file) != {'display_name', 'path'}:
            raise ValueError('Each file needs display_name and path')
        path = Path(file['path'])
        if not path.is_absolute() or not path.is_file():
            raise ValueError('Result file must exist at an absolute path')
    return checkpoint, files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace_id')
    parser.add_argument('task_id')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('context')
    read = sub.add_parser('read')
    read.add_argument('reference_id')
    read.add_argument('relative_path', help='Use . for a directly linked file')
    propose = sub.add_parser('propose')
    propose.add_argument('proposal_json')
    apply = sub.add_parser('apply')
    apply.add_argument('proposal_json')
    args = parser.parse_args()
    context = task_context(args.workspace_id, args.task_id)
    if args.command == 'context':
        print(json.dumps(context, indent=2, ensure_ascii=False))
    elif args.command == 'read':
        target = resolve_linked_file(args.workspace_id, args.reference_id, args.relative_path)
        print(f'Read linked file for task {args.task_id}: {target}')
        if input('Type READ to authorize this file: ') != 'READ':
            raise ValueError('Read was not authorized')
        print(target.read_text(encoding='utf-8'))
    else:
        proposal = json.loads(Path(args.proposal_json).read_text(encoding='utf-8'))
        checkpoint, files = validate_proposal(proposal, args.workspace_id, args.task_id)
        print(json.dumps(proposal, indent=2, ensure_ascii=False))
        if args.command == 'propose':
            return
        if input('Type APPROVE to save this checkpoint and register these files: ') != 'APPROVE':
            raise ValueError('Writeback was not approved')
        token = api('/bootstrap')['write_token']
        checkpoint_result = api('/workspaces/' + args.workspace_id + '/checkpoints',
                                'POST', checkpoint, token)
        registered = []
        for file in files:
            registered.append(api('/workspaces/' + args.workspace_id + '/references', 'POST',
                                  {'display_name': file['display_name'], 'target_path': file['path']}, token))
        print(json.dumps({'checkpoint_id': checkpoint_result['id'],
                          'registered_reference_ids': [r['id'] for r in registered]}, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        sys.exit(1)
