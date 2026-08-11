"""Pure cheat-sheet parsing, split out of `cheat_sheet_gui`.

The web panel needs exactly one thing from the cheat sheet — the parsed
section tree — and importing the Tk panel to get it dragged tkinter,
customtkinter and PIL in behind it (~1.3s on first open of a panel that
renders a markdown file).

This module is the ONLY definition of `parse_markdown`. `cheat_sheet_gui`
imports it from here rather than keeping a copy: two copies of an
extracted function is how the last extraction went wrong — both existed,
one shadowed the other, and no behaviour test could see the difference.
"""
import os


def parse_markdown(path):
    """
    Returns: list of {title, subsections}
    where each subsection is {title, lines}
    Sections split on ## headings; subsections on ###.
    Content above the first ## becomes an 'Overview' section.
    """
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as f:
        raw = f.read()

    sections = []
    cur_sec  = {"title": "Overview", "subsections": [{"title": "", "lines": []}]}

    for line in raw.splitlines():
        if line.startswith("# "):
            # Top-level title — skip; we use window title instead
            continue
        if line.startswith("## "):
            # New section
            if any(sub["lines"] or sub["title"] for sub in cur_sec["subsections"]):
                sections.append(cur_sec)
            cur_sec = {"title": line[3:].strip(),
                       "subsections": [{"title": "", "lines": []}]}
            continue
        if line.startswith("### "):
            cur_sec["subsections"].append({"title": line[4:].strip(), "lines": []})
            continue
        cur_sec["subsections"][-1]["lines"].append(line)

    if any(sub["lines"] or sub["title"] for sub in cur_sec["subsections"]):
        sections.append(cur_sec)
    return sections
