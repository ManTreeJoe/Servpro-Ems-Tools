"""Pre-flight lint for recurring Tk gotchas in this codebase.

Catches the bugs that have bitten us multiple times during the same
session — each one cost a launcher crash + a round-trip to find. Run
after edits before claiming code is shipped, so the same class of bug
doesn't re-emerge.

Checks (each with a short name shown in output):

    PAD-TUPLE       pad[xy]=(...) tuple on a widget constructor.
                    Tk's `bad screen distance "0 6"` error. Tuples
                    are only legal on .pack() / .grid(), never on
                    construction. (Hit 2026-05-18 + 2026-05-19.)

    SHADOW-TK       Instance attribute name that shadows a method
                    on `tk.Widget` / `tk.Misc`. Most painful one
                    seen was `self._options = {...}` clobbering Tk's
                    internal options builder used by .place() /
                    .pack() / .configure() — produced the cryptic
                    "'dict' object is not callable" crash.

    SCANDIR-LOOSE   Bare `os.scandir(...)` not wrapped in a `with`.
                    Windows holds the directory handle open until
                    the iterator is GC'd; long-lived loops can
                    lock the folder. See feedback_scandir_with_block.

Usage:
    python dev_lint.py                     # whole scripts/ dir
    python dev_lint.py file.py [more.py]   # explicit list

Exit code 0 = clean, 1 = at least one violation. Prints
`<path>:<line>: <CHECK>: <message>` per finding, plus the offending
line. Designed to be easily diff-able across edits — if the count
goes up after a write, something regressed.
"""
from __future__ import annotations

import io
import os
import re
import sys
import tokenize


# ── String/comment stripping ───────────────────────────────────────────────
#
# Every check below scans the source AFTER comments and string literals
# are replaced with whitespace of the same length. Keeps line numbers +
# column offsets identical so error reporting still cites the original
# location, while preventing the linter from flagging the patterns it
# documents inside its own docstrings.

def _strip_strings_and_comments(src: str) -> str:
    """Return `src` with comment and string-literal contents replaced
    by spaces. Preserves total length + newline positions so downstream
    regex matches index into the same line/col as the original.

    Uses the stdlib tokenizer for correctness on f-strings, triple-
    quoted blocks, line continuations inside strings, etc.
    """
    try:
        tokens = list(tokenize.generate_tokens(
            io.StringIO(src).readline))
    except (tokenize.TokenizeError, IndentationError):
        return src  # malformed source — fall back to raw

    line_starts = [0]
    for i, c in enumerate(src):
        if c == "\n":
            line_starts.append(i + 1)

    def _offset(row: int, col: int) -> int:
        if row < 1 or row - 1 >= len(line_starts):
            return -1
        return line_starts[row - 1] + col

    out = list(src)
    for tok in tokens:
        if tok.type not in (tokenize.STRING, tokenize.COMMENT,
                             tokenize.FSTRING_START,
                             tokenize.FSTRING_MIDDLE,
                             tokenize.FSTRING_END):
            continue
        a = _offset(tok.start[0], tok.start[1])
        b = _offset(tok.end[0], tok.end[1])
        if a < 0 or b < 0 or a >= len(out):
            continue
        # Replace contents with spaces, preserving newlines so line
        # numbering stays exact.
        for j in range(a, min(b, len(out))):
            if out[j] != "\n":
                out[j] = " "
    return "".join(out)


# ── Check 1: pad-tuple on widget construction ──────────────────────────────
# Match `tk.Widget(...pad[xy]=(...)...)` OR `ttk.Widget(...)` OR direct
# `tk.Frame(...)`-style calls. We need multiline awareness because
# constructors often span lines:
#   filt = tk.Frame(self, bg=BG, padx=14,
#                   pady=(0, 6))
# Strategy: scan for `tk.\w+\(` (or ttk.) opener, then look for `pad[xy]=`
# *inside* the parenthesized args, with a tuple literal as the value.
_WIDGET_CALL_RE = re.compile(
    r"\b(?:tk|ttk|customtkinter|ctk)\.\w+\s*\(", re.MULTILINE)

# Tuple value after `padx=` or `pady=` — captures up through the
# closing paren of the tuple. The negative lookbehind on `=` skips
# `padx==(...)` (Python doesn't have that operator but defensive).
_PAD_TUPLE_INSIDE_RE = re.compile(
    r"\b(pad[xy])\s*=\s*\(\s*-?\d+\s*,\s*-?\d+\s*\)")


def _find_matching_paren(src: str, open_idx: int) -> int:
    """Return the index of the `)` that matches the `(` at open_idx.
    Naive but enough — skips chars inside string literals."""
    depth = 0
    i = open_idx
    in_str = None
    while i < len(src):
        c = src[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == in_str:
                in_str = None
        elif c in ("'", '"'):
            in_str = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def check_pad_tuple(path: str, src: str, *,
                     original: str | None = None
                     ) -> list[tuple[int, str, str]]:
    """Return list of (line_number, check_name, line_text) violations.
    `src` is scrubbed of strings/comments; `original` is the raw source
    used for the reported line text."""
    if original is None:
        original = src
    findings: list[tuple[int, str, str]] = []
    line_starts = [0]
    for i, c in enumerate(src):
        if c == "\n":
            line_starts.append(i + 1)

    def _line_for(idx: int) -> int:
        lo, hi = 0, len(line_starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if line_starts[mid] <= idx:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1

    raw_lines = original.splitlines()
    for m in _WIDGET_CALL_RE.finditer(src):
        open_paren = m.end() - 1
        close_paren = _find_matching_paren(src, open_paren)
        if close_paren < 0:
            continue
        body = src[open_paren + 1:close_paren]
        for tm in _PAD_TUPLE_INSIDE_RE.finditer(body):
            absolute_idx = open_paren + 1 + tm.start()
            line_no = _line_for(absolute_idx)
            line_text = (raw_lines[line_no - 1].rstrip()
                          if line_no - 1 < len(raw_lines) else "")
            findings.append((
                line_no, "PAD-TUPLE",
                f"{tm.group(1)}=(...) tuple inside widget constructor "
                f"— Tk requires int here; move the tuple to .pack()/"
                f".grid() instead\n      {line_text}"))
    return findings


# ── Check 2: instance attributes that shadow tk.Widget methods ─────────────

# Pulled from tkinter introspection. These are the names that, if you
# assign `self.<name> = ...` on a Tk widget subclass, will break
# .place()/.pack()/.configure() or similar. Conservative list — only
# the ones that have actually caused bugs OR are dunder-adjacent /
# trampoline methods Tk hits during widget config.
_SHADOW_TK_NAMES = frozenset({
    "_options",      # Misc._options — builds cnf+kw for tk.call
    "_w",            # widget Tcl path string
    "_root",         # tk._root method
    "_subwidget_name",
    "_displayof",
    "_grid_configure",
    "_pack_configure",
    "_place_configure",
    "_configure",
    "_register",
    "_substitute",
    "tk",            # reserved on every widget
    "master",        # the parent reference
    "children",
})

_SHADOW_ASSIGN_RE = re.compile(
    r"^\s*self\.(?P<name>_\w+|tk|master|children)\s*"
    r"(?::\s*[^=]+\s*)?=\s*", re.MULTILINE)

# `class Foo(Bar, Baz):` — capture the base list so we can decide
# whether the enclosing class is a Tk widget subclass. Skipping the
# shadow check on plain helper classes (Debouncer etc.) avoids
# noise where the names don't actually collide with anything.
_CLASS_DEF_RE = re.compile(
    r"^class\s+(\w+)\s*(?:\(([^)]*)\))?\s*:", re.MULTILINE)

_TK_BASE_MARKERS = (
    "tk.", "ttk.", "ctk.", "customtkinter.",
    "Frame", "Toplevel", "Widget", "Misc",
    "ToolPanel", "ScrollableFrame", "ResponsiveActionBar",
    "App", "Canvas", "Text", "Label", "Button", "Menu",
)


def _is_tk_subclass(bases: str) -> bool:
    """Heuristic: does this class's base list look like it descends
    from a tk widget? Substring match against common base markers —
    keeps the check zero-import and works on stringly-typed bases."""
    b = (bases or "").strip()
    if not b or b == "object":
        return False
    return any(m in b for m in _TK_BASE_MARKERS)


def _class_ranges(src: str) -> list[tuple[int, int, str]]:
    """Return [(start_idx, end_idx, base_list_str), ...] for each
    class block in `src`. End_idx is the position of the NEXT
    top-level def/class (or EOF) — close enough for the shadow check
    (we just need to know which class encloses a `self.x = ...` line).
    """
    matches = list(_CLASS_DEF_RE.finditer(src))
    ranges: list[tuple[int, int, str]] = []
    for i, m in enumerate(matches):
        start = m.end()
        end = (matches[i + 1].start()
                if i + 1 < len(matches) else len(src))
        bases = m.group(2) or ""
        ranges.append((start, end, bases))
    return ranges


def check_shadow_tk(path: str, src: str, *,
                     original: str | None = None
                     ) -> list[tuple[int, str, str]]:
    """Flag `self.<name> = ...` only when the enclosing class
    inherits from a tk-related type. Plain helper classes with
    `_w` / `_root` fields aren't actually shadowing anything."""
    if original is None:
        original = src
    raw_lines = original.splitlines()
    class_ranges = _class_ranges(src)
    findings: list[tuple[int, str, str]] = []
    for m in _SHADOW_ASSIGN_RE.finditer(src):
        name = m.group("name")
        if name not in _SHADOW_TK_NAMES:
            continue
        pos = m.start()
        enclosing_bases = None
        for (cs, ce, cbases) in class_ranges:
            if cs <= pos < ce:
                enclosing_bases = cbases
                break
        if enclosing_bases is None:
            continue   # module-level — not on a widget
        if not _is_tk_subclass(enclosing_bases):
            continue   # plain helper class, no shadow risk
        line_no = src.count("\n", 0, pos) + 1
        line_text = (raw_lines[line_no - 1].rstrip()
                      if line_no - 1 < len(raw_lines) else "")
        findings.append((
            line_no, "SHADOW-TK",
            f"`self.{name} = ...` shadows tkinter.Widget — "
            f"rename to `_dropdown_{name.lstrip('_')}` or similar\n"
            f"      {line_text}"))
    return findings


# ── Check 3: bare os.scandir without `with` ────────────────────────────────

# os.scandir without `with` keeps the directory handle open until the
# generator is GC'd, which on Windows can lock the folder. The rule:
# every `os.scandir(...)` call should appear in a `with` statement.
# `with os.scandir(...) as it:` ✓
# `for e in os.scandir(...):` ✗  (handle leaks)
# `it = os.scandir(...); ... ; it.close()` — would pass if we required
# explicit close, but the `with` form is the canonical convention
# already documented in feedback_scandir_with_block.

_SCANDIR_BARE_RE = re.compile(r"(^|[^.\w])os\.scandir\s*\(")


def check_scandir_loose(path: str, src: str, *,
                          original: str | None = None
                          ) -> list[tuple[int, str, str]]:
    if original is None:
        original = src
    findings: list[tuple[int, str, str]] = []
    scrub_lines = src.splitlines()
    raw_lines = original.splitlines()
    for i, line in enumerate(scrub_lines, start=1):
        if not _SCANDIR_BARE_RE.search(line):
            continue
        # Inspect up to 2 prior physical lines (handle the
        # `with os.scandir(\n  path\n) as it:` formatting).
        ctx = "\n".join(scrub_lines[max(0, i - 3):i + 1])
        if re.search(r"\bwith\s+[^\n]*os\.scandir\s*\(", ctx):
            continue
        report_line = (raw_lines[i - 1].rstrip()
                        if i - 1 < len(raw_lines) else "")
        findings.append((
            i, "SCANDIR-LOOSE",
            f"bare os.scandir() — wrap in `with` to release the "
            f"directory handle (Windows folder lock risk)\n"
            f"      {report_line}"))
    return findings


# ── Driver ────────────────────────────────────────────────────────────────

CHECKS = (
    ("pad_tuple",     check_pad_tuple),
    ("shadow_tk",     check_shadow_tk),
    ("scandir_loose", check_scandir_loose),
)


def lint_file(path: str) -> list[tuple[int, str, str]]:
    try:
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
    except (OSError, UnicodeDecodeError) as ex:
        return [(0, "READ-ERR", f"{path}: {ex}")]
    # Strip comments + string-literal contents so the linter doesn't
    # flag patterns it documents inside its own docstrings (or that a
    # tested code block intentionally cites in a triple-quoted demo).
    scrub = _strip_strings_and_comments(src)
    # Keep original `src` available for line-text reporting in the
    # finding messages — the scrub keeps line numbers identical, so
    # the line slice into `src` still hits the right text.
    findings: list[tuple[int, str, str]] = []
    for _name, fn in CHECKS:
        findings.extend(fn(path, scrub, original=src))
    findings.sort(key=lambda f: (f[0], f[1]))
    return findings


def iter_target_files(args: list[str]) -> list[str]:
    if not args:
        # Default: every .py in scripts/ (this file's directory).
        here = os.path.dirname(os.path.abspath(__file__))
        out = []
        for name in os.listdir(here):
            if name.endswith(".py") and not name.startswith("_"):
                out.append(os.path.join(here, name))
        return sorted(out)
    paths: list[str] = []
    for a in args:
        if os.path.isdir(a):
            for root, _dirs, files in os.walk(a):
                for n in files:
                    if n.endswith(".py") and not n.startswith("_"):
                        paths.append(os.path.join(root, n))
        elif os.path.isfile(a):
            paths.append(a)
    return sorted(paths)


def main(argv: list[str]) -> int:
    paths = iter_target_files(argv)
    if not paths:
        print("no Python files to lint", file=sys.stderr)
        return 0
    total = 0
    for p in paths:
        findings = lint_file(p)
        if not findings:
            continue
        rel = p
        # Trim the prefix so output diffs are stable across machines.
        try:
            rel = os.path.relpath(p)
        except ValueError:
            pass
        for line_no, check, msg in findings:
            print(f"{rel}:{line_no}: {check}: {msg}")
        total += len(findings)
    if total:
        print(f"\n{total} violation(s) across {len(paths)} file(s)")
        return 1
    print(f"clean ({len(paths)} files checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
