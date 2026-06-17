"""Registry of spreadsheets the Spreadsheets panel can browse.

Today there's exactly one — the Snapshots workbook (`snapshots_excel`).
This module exists so adding a second/third workbook later is a small,
contained change: write a `WorkbookSpec` and call `register()`.

A `WorkbookSpec` is the integration contract. Each spec answers four
questions the panel needs:
    - Where's the file? (`workbook_path(year)`)
    - What rows are in it? (`read_rows(year)`)
    - How does each row map to columns + a tag? (`columns`, `row_to_values`, `tag_for_row`)
    - What sheet filter values + action buttons does this workbook support?

The panel renders generically off these — no spec-specific branching in
the panel code itself.

Adding a new workbook (skeleton):
    from workbook_registry import WorkbookSpec, register

    def _read_rows(year): return my_module.read_rows(year)
    def _path(year):       return my_module.workbook_path(year)
    register(WorkbookSpec(
        key="invoicing",
        label="Invoicing",
        read_rows=_read_rows,
        workbook_path=_path,
        sheets=("All", "Open", "Paid"),
        columns=(...),
        ...))
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class ColumnSpec:
    """One Treeview column."""
    key: str            # internal column id (stable)
    header: str         # user-visible header
    width: int = 100    # default pixel width
    anchor: str = "w"   # tk anchor — "w" / "center" / "e"


@dataclass(frozen=True)
class ActionSpec:
    """One bottom-row action button.

    `command_factory(app)` is called when the panel binds the button
    so the action can capture `app` (the SpreadsheetApp instance) and
    operate on its current state.

    `attr_name`, when set, makes the panel store the created button
    as `app.<attr_name>` so the action implementation can mutate it
    (disable while running, change text to "Syncing…", etc.)."""
    label: str
    kind: str                                  # "warn"/"send"/"secondary"
    command_factory: Callable[[Any], Callable[[], None]]
    tooltip: str = ""
    attr_name: str = ""


@dataclass(frozen=True)
class WorkbookSpec:
    """All a workbook needs to plug into the Spreadsheets panel."""
    key: str
    label: str
    read_rows: Callable[[int], list[dict]]
    workbook_path: Callable[[int], str]
    sheets: tuple[str, ...]                    # filter dropdown values
    columns: tuple[ColumnSpec, ...]
    row_to_values: Callable[[dict], tuple]     # per-row Treeview tuple
    tag_for_row: Callable[[dict], str | None]  # row color tag, or None
    actions: tuple[ActionSpec, ...] = field(default_factory=tuple)
    # Sheet-tag → color tag mapping. Treeview tags get configured up
    # front (background colors) so per-row tagging is just a key
    # lookup. {"NEW LOSS": WARN_BG, "Completed": SUCCESS_BG, ...}
    tag_colors: dict[str, str] = field(default_factory=dict)
    # Optional: a callable that returns a "pending count" badge string
    # for the status line. Used by Snapshots' backlog count.
    pending_count: Callable[[int], int] | None = None


_REGISTRY: dict[str, WorkbookSpec] = {}
_ORDER: list[str] = []


def register(spec: WorkbookSpec) -> None:
    """Register a workbook. Idempotent — re-registering the same key
    overrides the prior spec (lets dev code reload without restart)."""
    if spec.key not in _REGISTRY:
        _ORDER.append(spec.key)
    _REGISTRY[spec.key] = spec


def get(key: str) -> WorkbookSpec | None:
    return _REGISTRY.get(key)


def all_specs() -> list[WorkbookSpec]:
    return [_REGISTRY[k] for k in _ORDER if k in _REGISTRY]


def default_key() -> str:
    """First-registered spec, or empty when nothing's registered yet
    (which would be a programming error — the panel would render
    empty)."""
    return _ORDER[0] if _ORDER else ""
