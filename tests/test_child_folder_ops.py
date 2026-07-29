"""Tests for child_folder_ops (safe move / reserve / skeleton / create)
plus the two routing-adjacent audit fixes it underpins:
  #5 — unit-token parser no longer false-matches claim/job '#' numbers
  detection — list_unit_subfolders surfaces off-convention real units
"""
import os
import child_folder_ops as cfo
import multi_unit_gui as mug
import audit_logic as al


# ── safe_move ────────────────────────────────────────────────────────
def test_safe_move_success(tmp_path):
    src = tmp_path / "a.jpg"
    src.write_bytes(b"x")
    dest_dir = tmp_path / "PICS"
    landed = cfo.safe_move(str(src), str(dest_dir))
    assert landed and os.path.isfile(landed)
    assert not src.exists()                     # moved, not copied
    assert os.path.basename(landed) == "a.jpg"


def test_safe_move_collision_suffixes(tmp_path):
    dest_dir = tmp_path / "PICS"
    dest_dir.mkdir()
    (dest_dir / "a.jpg").write_bytes(b"old")    # pre-existing clash
    src = tmp_path / "a.jpg"
    src.write_bytes(b"new")
    landed = cfo.safe_move(str(src), str(dest_dir))
    assert landed.endswith("a (2).jpg")         # never clobbers
    assert (dest_dir / "a.jpg").read_bytes() == b"old"


def test_safe_move_missing_src_returns_none(tmp_path):
    assert cfo.safe_move(str(tmp_path / "nope.jpg"), str(tmp_path)) is None


# ── reserve_child_dir ────────────────────────────────────────────────
def test_reserve_child_dir_bumps_on_collision(tmp_path):
    parent = tmp_path
    a = cfo.reserve_child_dir(str(parent), "Unit 5")
    b = cfo.reserve_child_dir(str(parent), "Unit 5")
    assert os.path.basename(a) == "Unit 5"
    assert os.path.basename(b) == "Unit 5 (2)"
    assert os.path.isdir(a) and os.path.isdir(b)


def test_reserve_child_dir_missing_parent(tmp_path):
    assert cfo.reserve_child_dir(str(tmp_path / "ghost"), "Unit 5") is None


# ── replicate_sibling_skeleton ───────────────────────────────────────
def test_replicate_sibling_skeleton_mirrors_subtree(tmp_path):
    sib = tmp_path / "Unit 1416"
    (sib / "EMS" / "PICS").mkdir(parents=True)
    (sib / "EMS" / "DOCS").mkdir(parents=True)
    (sib / "CONTENTS").mkdir()
    (sib / "EMS" / "PICS" / "photo.jpg").write_bytes(b"x")   # file, not dir
    new = tmp_path / "Unit 1502"
    new.mkdir()
    made = cfo.replicate_sibling_skeleton(str(new), str(sib))
    assert made >= 3
    assert (new / "EMS" / "PICS").is_dir()
    assert (new / "EMS" / "DOCS").is_dir()
    assert (new / "CONTENTS").is_dir()
    assert not (new / "EMS" / "PICS" / "photo.jpg").exists()  # dirs only


def test_replicate_sibling_skeleton_fallback(tmp_path):
    new = tmp_path / "Unit 1502"
    new.mkdir()
    made = cfo.replicate_sibling_skeleton(str(new), None)
    assert made >= 2
    assert (new / "EMS" / "PICS").is_dir()
    assert (new / "EMS" / "DOCS").is_dir()


# ── compose_unit_name (sibling-style inference) ──────────────────────
def test_compose_unit_name_matches_sibling_style():
    assert cfo.compose_unit_name(
        "", 1502, siblings=[{"name": "Unit 1416"}]) == "Unit 1502"
    assert cfo.compose_unit_name(
        "", 216, siblings=[{"name": "UNIT #212"}]) == "UNIT #216"
    assert cfo.compose_unit_name(
        "", 12, siblings=[{"name": "Apt 8"}]) == "Apt 12"


def test_compose_unit_name_fallback_no_unit_sibling():
    assert cfo.compose_unit_name(
        "", 5, siblings=[{"name": "Smith"}]) == "Unit 5"


# ── create_and_route_unit (end-to-end) ───────────────────────────────
def test_create_and_route_unit(tmp_path):
    parent = tmp_path / "Keystone Village"
    parent.mkdir()
    (parent / "Unit 1416" / "EMS" / "PICS").mkdir(parents=True)
    (parent / "Unit 1416" / "EMS" / "DOCS").mkdir(parents=True)
    f1 = tmp_path / "img1.jpg"; f1.write_bytes(b"a")
    f2 = tmp_path / "img2.jpg"; f2.write_bytes(b"b")
    res = cfo.create_and_route_unit(
        str(parent), "Unit 1502", import_files=[str(f1), str(f2)],
        sibling_path=str(parent / "Unit 1416"))
    assert res["ok"]
    assert res["moved"] == 2 and res["failed"] == []
    pics = os.path.join(res["path"], "EMS", "PICS")
    assert os.path.isfile(os.path.join(pics, "img1.jpg"))
    assert os.path.isfile(os.path.join(pics, "img2.jpg"))
    assert not f1.exists() and not f2.exists()


def test_create_and_route_unit_bad_parent(tmp_path):
    res = cfo.create_and_route_unit(str(tmp_path / "ghost"), "Unit 5")
    assert res["ok"] is False


# ── #5 — unit-token parser guards ────────────────────────────────────
def test_parse_unit_token_rejects_claim_and_job_numbers():
    assert mug.parse_unit_token("Smith Claim #12345 Demo") is None
    assert mug.parse_unit_token("Job #2 water") is None
    assert mug.parse_unit_token("ref# 8891 report") is None
    # Real units still parse:
    assert mug.parse_unit_token("Avila Apt 207 Demo") == 207
    assert mug.parse_unit_token("Smith #207 Demo") == 207
    assert mug.parse_unit_token("Unit 1416 kitchen") == 1416
    assert mug.parse_unit_token("Suite 12 mold") == 12


# ── detection widening — off-convention units no longer vanish ───────
def test_list_unit_subfolders_surfaces_off_convention(tmp_path):
    prop = tmp_path
    for n in ("Unit 1416", "1416B", "Smith", "Building A",
              "PICS", "EMS", "Old", "DOCS"):
        (prop / n).mkdir()
    names = {d["name"] for d in al.list_unit_subfolders(str(prop))}
    assert "1416B" in names
    assert "Smith" in names
    assert "Building A" in names
    assert "PICS" not in names and "EMS" not in names   # standard children
    assert "Old" not in names and "DOCS" not in names   # junk / standard


def test_list_unit_subfolders_sorts_numeric_first(tmp_path):
    for n in ("Smith", "Unit 3", "Unit 20", "Building A"):
        (tmp_path / n).mkdir()
    ordered = [d["name"] for d in al.list_unit_subfolders(str(tmp_path))]
    # Numeric units (by number) come before named folders (alpha).
    assert ordered.index("Unit 3") < ordered.index("Unit 20")
    assert ordered.index("Unit 20") < ordered.index("Building A")
    assert ordered.index("Building A") < ordered.index("Smith")
