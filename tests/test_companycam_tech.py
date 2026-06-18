"""CompanyCam import attributes photos to a tech (the export carries no
photographer, so the importer is told). Locks the folder layout:
  tagged   + tech → PICS/<stage>/<Tech date>/<room>
  untagged + tech → PICS/<Tech date>/<room>
  no tech          → unchanged (PICS/<stage>/<room>, PICS/CompanyCam <date>/…)
"""
import zipfile
import companycam_import as cc


def _make_zip(tmp_path, names):
    z = tmp_path / "photos-2026-06-09-aaaa.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for n in names:
            zf.writestr(f"Sayra Mansolino/{n}", b"\xff\xd8\xff\xe0")  # fake jpg
    return str(z)


def test_tech_folder_for_tagged_and_untagged(tmp_path):
    pics = tmp_path / "PICS"
    pics.mkdir()
    z = _make_zip(tmp_path, [
        "Kitchen Demo-1-Jun 9 2026 10_00am-aa.jpg",   # tagged Demo, room Kitchen
        "Master Bath-2-Jun 9 2026 10_01am-bb.jpg",    # untagged, room Master Bath
    ])
    cc.import_zip(z, str(pics), date_label="06-09-2026", tech="Nestor")
    assert (pics / "Demo" / "Nestor 06-09-2026" / "Kitchen").is_dir()
    assert (pics / "Nestor 06-09-2026" / "Master Bath").is_dir()


def test_no_tech_layout_unchanged(tmp_path):
    pics = tmp_path / "PICS"
    pics.mkdir()
    z = _make_zip(tmp_path, [
        "Kitchen Demo-1-Jun 9 2026 10_00am-aa.jpg",
        "Garage-2-Jun 9 2026 10_01am-bb.jpg",
    ])
    cc.import_zip(z, str(pics), date_label="06-09-2026")
    assert (pics / "Demo" / "Kitchen").is_dir()
    assert (pics / "CompanyCam 06-09-2026" / "Garage").is_dir()
