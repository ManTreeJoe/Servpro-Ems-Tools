"""Workflow contract tests; no application imports or providers."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('agent_checks', ROOT / '.github/agent_checks.py')
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)


class WorkflowTests(unittest.TestCase):
    def test_required_check_is_nonpublishing_and_runs_all_stages(self):
        text = (ROOT / '.github/workflows/ci.yml').read_text()
        for fragment in ['pull_request:', 'branches: [main]', 'name: ci',
                         'python dev_lint.py', 'agent_checks.py typecheck',
                         'python -m pytest tests/', 'agent_checks.py node-tests',
                         'python -m PyInstaller', 'cache: pip', 'cache: npm',
                         "ONELOSS_TRELLO_WRITES_ENABLED: 'false'"]:
            self.assertIn(fragment, text)
        for forbidden in ['secrets.', 'continue-on-error', 'publish_desktop_release',
                          'pull_request_target', 'contents: write']:
            self.assertNotIn(forbidden, text)

    def test_typecheck_failure_propagates(self):
        with patch.object(checks, 'tracked_python', return_value=['example.py']), \
             patch.object(checks.subprocess, 'call', return_value=1) as call:
            self.assertEqual(checks.typecheck(), 1)
            self.assertIn('--check-untyped-defs', call.call_args.args[0])

    def test_node_runner_includes_sql_and_preserves_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'tests').mkdir()
            (root / '.github').mkdir()
            (root / '.github/ci-skips.json').write_text(json.dumps({'node_scripts': {'skip.cjs': 'fixture'}}))
            for name in ['ok.cjs', 'sql.mjs', 'skip.cjs']:
                (root / 'tests' / name).write_text('')
            with patch.object(checks, 'ROOT', root), \
                 patch.object(checks.subprocess, 'run') as run:
                run.return_value.returncode = 1
                self.assertEqual(checks.node_tests(), 1)
                self.assertEqual(run.call_count, 2)
                self.assertTrue(any('sql.mjs' in c.args[0][1] for c in run.call_args_list))
                self.assertTrue(all(c.kwargs['timeout'] == 120 for c in run.call_args_list))

    def test_env_example_is_names_only_and_not_ignored(self):
        import re
        lines = (ROOT / '.env.example').read_text().splitlines()
        names = [line for line in lines if line and not line.startswith('#')]
        self.assertGreater(len(names), 10)
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(re.fullmatch(r'[A-Z_][A-Z0-9_]*', name) for name in names))
        ignore = (ROOT / '.gitignore').read_text()
        self.assertIn('.env.*', ignore)
        self.assertIn('!.env.example', ignore)


if __name__ == '__main__':
    unittest.main()
