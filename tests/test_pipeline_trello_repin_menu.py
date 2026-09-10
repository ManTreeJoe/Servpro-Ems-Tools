from pathlib import Path


APP_JS = (Path(__file__).resolve().parents[1]
          / "pipeline_web_assets" / "app.js")


def test_job_card_right_click_can_change_the_pinned_trello_card():
    """The Jobs board must not hide the saved-card correction workflow.

    A wrong automatic match is operationally dangerous, so right-clicking a
    board card needs a direct Change pinned Trello card action that reaches
    the division-aware pin flow.
    """
    js = APP_JS.read_text(encoding="utf-8")
    menu_start = js.index("function openCardMenu(")
    menu_end = js.index("\nfunction onCardContext(", menu_start)
    menu = js[menu_start:menu_end]

    assert "Change pinned Trello card" in menu
    assert "openChangePinnedTrelloCard" in menu


def test_change_pinned_card_picker_searches_and_pins_through_the_api():
    js = APP_JS.read_text(encoding="utf-8")
    picker_start = js.index("function openChangePinnedTrelloCard(")
    picker_end = js.index("\nfunction openCardMenu(", picker_start)
    picker = js[picker_start:picker_end]

    assert "global_card_search" in picker
    assert "pin_crm_division_trello" in picker


def test_board_cards_keep_the_correct_division_when_repinning():
    js = APP_JS.read_text(encoding="utf-8")

    assert 'if (boardKey === "contents") return "CONTENTS"' in js
    assert 'if (boardKey === "recon") return "RECON"' in js
    assert 'data-division="${escapeAttr(divisionForBoardKey(board.key))}"' in js


def test_all_board_search_results_also_expose_the_right_click_repin_menu():
    js = APP_JS.read_text(encoding="utf-8")
    render_start = js.index("function renderBoard()")
    render_end = js.index("\nasync function openFocusedJob", render_start)
    render = js[render_start:render_end]

    assert 'card.addEventListener("contextmenu", onCardContext)' in render


def test_search_results_infer_contents_and_recon_divisions_from_their_board():
    js = APP_JS.read_text(encoding="utf-8")
    results_start = js.index("function renderGlobalSearchResults(")
    results_end = js.index("\nfunction activeBoardLook", results_start)
    results = js[results_start:results_end]

    assert "divisionForBoardName(card.board)" in results
    assert 'if (name.includes("CONTENTS")) return "CONTENTS"' in js
    assert 'if (name.includes("RECON")) return "RECON"' in js
