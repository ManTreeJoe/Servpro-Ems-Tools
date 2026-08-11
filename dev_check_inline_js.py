"""Syntax-check the inline <script> in a panel's index.html.

    python dev_check_inline_js.py photo_folders_web_assets/index.html [...]

`node --check` only takes a .js file, and four panels keep their whole
app inside index.html rather than a sibling app.js — so a syntax error
there sailed past the JS lint step that covers every other panel.
Extracts each inline block to a temp file and checks it.
"""
import os
import re
import subprocess
import sys
import tempfile

_SCRIPT_RE = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>",
                        re.DOTALL | re.IGNORECASE)


def check(path):
    with open(path, encoding="utf-8") as f:
        html = f.read()
    blocks = _SCRIPT_RE.findall(html)
    if not blocks:
        print(f"  {path}: no inline script")
        return True
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        for i, body in enumerate(blocks):
            if not body.strip():
                continue
            js = os.path.join(tmp, f"block{i}.js")
            with open(js, "w", encoding="utf-8") as f:
                f.write(body)
            proc = subprocess.run(["node", "--check", js],
                                  capture_output=True, text=True)
            if proc.returncode != 0:
                ok = False
                print(f"  {path} (block {i}): {proc.stderr.strip()[:400]}")
    print(f"  {path}: {'OK' if ok else 'FAILED'}")
    return ok


def main():
    args = sys.argv[1:]
    if not args:
        import glob
        args = sorted(glob.glob("*_web_assets/index.html"))
    return 0 if all(check(p) for p in args) else 1


if __name__ == "__main__":
    raise SystemExit(main())
