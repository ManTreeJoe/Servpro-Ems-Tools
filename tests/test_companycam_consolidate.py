"""CompanyCam import — single dominant stage folds untagged stragglers in.

Regression (Munoz Joshua, 2026-06-19): one export had most photos tagged
"...Post" plus a few untagged ("Exterior Kitchen Mitgation", 2 loose). The
Post photos landed in PICS/Post/Mark E 06-19-2026/ while the untagged ones
were dumped in a DUPLICATE PICS/Mark E 06-19-2026/ at the root. When the
whole export shares one stage, untagged photos must join that stage.
"""
import zipfile
import companycam_import as cc


def _make_zip(tmp_path, names, project="Joshua Munoz"):
    z = tmp_path / "photos-2026-06-19-zzzz.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for n in names:
            zf.writestr(f"{project}/{n}", b"\xff\xd8\xff\xe0")  # fake jpg
    return str(z)


def test_untagged_folds_into_single_stage(tmp_path):
    pics = tmp_path / "PICS"
    pics.mkdir()
    z = _make_zip(tmp_path, [
        # Tagged Post (two rooms)
        "Kitchen Mitgation Post-10-Jun 19 2026 11_48am-aa.jpg",
        "Garage Mitgation Post-51-Jun 19 2026 11_50am-bb.jpg",
        # Untagged stragglers (room-only + fully loose)
        "Exterior Kitchen Mitgation-1-Jun 19 2026 11_38am-cc.jpg",
        "8-Jun 19 2026 11_48am-dd.jpg",
    ])
    cc.import_zip(z, str(pics), date_label="06-19-2026", tech="Mark E")
    box = pics / "Post" / "Mark E 06-19-2026"
    assert box.is_dir()
    # Untagged room joined the Post tech box…
    assert (box / "Exterior Kitchen Mitgation").is_dir()
    # …and the fully-loose photo sits directly in it.
    assert (box / "8-Jun 19 2026 11_48am-dd.jpg").exists()
    # No duplicate tech box at the PICS root.
    assert not (pics / "Mark E 06-19-2026").exists()


def test_untagged_stays_separate_when_multiple_stages(tmp_path):
    # 2+ distinct stages in one zip → untagged is ambiguous, stays at root.
    pics = tmp_path / "PICS"
    pics.mkdir()
    z = _make_zip(tmp_path, [
        "Kitchen Demo-1-Jun 19 2026 10_00am-aa.jpg",
        "Garage Post-2-Jun 19 2026 10_01am-bb.jpg",
        "Attic-3-Jun 19 2026 10_02am-cc.jpg",   # untagged
    ])
    cc.import_zip(z, str(pics), date_label="06-19-2026", tech="Mark E")
    # Untagged Attic lands in the root tech box (single room → flat), not
    # folded under Demo or Post (ambiguous with 2+ stages present).
    root_box = pics / "Mark E 06-19-2026"
    attic = "Attic-3-Jun 19 2026 10_02am-cc.jpg"
    assert root_box.is_dir()
    assert (root_box / attic).exists()
    # The stage boxes hold their own tagged photos, but NOT the Attic.
    assert not (pics / "Demo" / "Mark E 06-19-2026" / attic).exists()
    assert not (pics / "Post" / "Mark E 06-19-2026" / attic).exists()
