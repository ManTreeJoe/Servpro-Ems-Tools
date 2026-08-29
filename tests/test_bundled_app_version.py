import json
from pathlib import Path

import paths


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_version_matches_release_manifest():
    manifest = json.loads((ROOT / "version.txt").read_text(encoding="utf-8"))
    assert paths.VERSION == manifest["version"]


def test_release_manifest_is_bundled_by_pyinstaller():
    spec = (ROOT / "Linguar_Hub.spec").read_text(encoding="utf-8")
    assert "datas.append((os.path.join(base, 'version.txt'), '.'))" in spec
