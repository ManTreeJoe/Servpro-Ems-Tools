"""Catch stale/misspelled exclusions instead of silently reducing CI coverage."""
import ast
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SkipPolicyTests(unittest.TestCase):
    def test_exclusions_reference_existing_tests_and_have_reasons(self):
        policy = json.loads((ROOT / '.github/ci-skips.json').read_text())
        for filename, reason in policy['node_scripts'].items():
            self.assertEqual(Path(filename).name, filename)
            self.assertTrue((ROOT / 'tests' / filename).is_file(), filename)
            self.assertTrue(reason.strip(), filename)
        for filename, reason in policy['python_modules'].items():
            self.assertTrue((ROOT / filename).is_file(), filename)
            self.assertTrue(reason.strip(), filename)
        for nodeid, reason in policy['python_tests'].items():
            filename, name = nodeid.split('::', 1)
            tree = ast.parse((ROOT / filename).read_text(encoding='utf-8'))
            functions = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
            self.assertIn(name.rsplit('::', 1)[-1].split('[')[0], functions, nodeid)
            self.assertTrue(reason.strip(), nodeid)


if __name__ == '__main__':
    unittest.main()
