import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import atlas_bridge as bridge
from atlas.service import WorkspaceService


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.service = WorkspaceService(self.root / 'atlas')
        self.workspace = self.service.create_workspace('Linux Programming')
        self.task = self.service.create_task(self.workspace['id'], 'Process Management')
        self.files = self.root / 'teacher'
        self.files.mkdir()
        (self.files / 'process.md').write_text('Process notes', encoding='utf-8')
        self.reference = self.service.add_reference(self.workspace['id'], 'Teacher notes', str(self.files))
        self.api_patch = patch.object(bridge, 'api', side_effect=self.fake_api)
        self.api_patch.start()

    def tearDown(self):
        self.api_patch.stop()
        self.tmp.cleanup()

    def fake_api(self, path, method='GET', body=None, token=None):
        if method == 'GET' and path == '/workspaces/' + self.workspace['id']:
            return self.service.workspace_detail(self.workspace['id'])
        if method == 'POST' and path.endswith('/checkpoints'):
            return self.service.add_checkpoint(self.workspace['id'], **body)
        if method == 'POST' and path.endswith('/references'):
            return self.service.add_reference(self.workspace['id'], **body)
        raise AssertionError((path, method))

    def test_context_is_task_scoped_and_does_not_read_files(self):
        context = bridge.task_context(self.workspace['id'], self.task['id'])
        self.assertEqual(context['task']['status'], 'todo')
        self.assertNotIn('target_path', context['resources'][0])
        with self.assertRaisesRegex(ValueError, 'does not belong'):
            bridge.task_context(self.workspace['id'], 'other-task')

    def test_explicit_resource_read_confined_to_reference(self):
        path = bridge.resolve_linked_file(self.workspace['id'], self.reference['id'], 'process.md')
        self.assertEqual(path.read_text(), 'Process notes')
        with self.assertRaises(ValueError):
            bridge.resolve_linked_file(self.workspace['id'], self.reference['id'], '../other.md')
        with self.assertRaises(ValueError):
            bridge.resolve_linked_file(self.workspace['id'], 'other-reference', 'process.md')

    def test_checkpoint_and_result_reference_preserve_todo_status(self):
        result = self.root / 'result.md'
        result.write_text('Review draft', encoding='utf-8')
        proposal = {'workspace_id': self.workspace['id'], 'task_id': self.task['id'],
                    'checkpoint': {'summary': 'Integration test only',
                                   'next_action': 'Continue process management study'},
                    'files': [{'display_name': 'Review draft', 'path': str(result)}]}
        checkpoint, files = bridge.validate_proposal(proposal, self.workspace['id'], self.task['id'])
        self.fake_api('/workspaces/' + self.workspace['id'] + '/checkpoints', 'POST', checkpoint)
        for item in files:
            self.fake_api('/workspaces/' + self.workspace['id'] + '/references', 'POST',
                          {'display_name': item['display_name'], 'target_path': item['path']})
        detail = self.service.workspace_detail(self.workspace['id'])
        self.assertEqual(detail['tasks'][0]['status'], 'todo')
        self.assertEqual(detail['checkpoints'][0]['next_action'], 'Continue process management study')
        self.assertEqual(len(detail['references']), 2)


if __name__ == '__main__':
    unittest.main()
