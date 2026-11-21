"""Reproducible repository checks; no application imports at module load."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def tracked_python() -> list[str]:
    return [p for p in subprocess.check_output(
        ['git', 'ls-files', '*.py'], cwd=ROOT, text=True).splitlines()
        if '/' not in p]


def typecheck() -> int:
    # Explicit root list avoids build outputs and duplicate nested module names.
    # Imported modules are skipped, not executed. This checks root Python only;
    # it does not claim coverage of browser JS or Supabase's Deno functions.
    return subprocess.call([sys.executable, '-m', 'mypy',
        '--follow-imports=skip', '--ignore-missing-imports',
        '--check-untyped-defs', *tracked_python()], cwd=ROOT)


def node_tests() -> int:
    policy = json.loads((ROOT / '.github/ci-skips.json').read_text())['node_scripts']
    failed = []
    for test in sorted((ROOT / 'tests').iterdir()):
        if test.suffix not in {'.cjs', '.mjs'}:
            continue
        if test.name in policy:
            print(f'SKIP {test.name}: {policy[test.name]}', flush=True)
            continue
        print(f'RUN {test.name}', flush=True)
        try:
            result = subprocess.run(['node', str(test)], cwd=ROOT, timeout=120)
            if result.returncode:
                failed.append(test.name)
        except subprocess.TimeoutExpired:
            failed.append(test.name + ' (120s timeout)')
    print('Failed Node scripts:', failed)
    return int(bool(failed))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('check', choices=['typecheck', 'node-tests'])
    args = parser.parse_args()
    return typecheck() if args.check == 'typecheck' else node_tests()


if __name__ == '__main__':
    raise SystemExit(main())
