"""CompanyCam import attributes photos to a tech (the export carries no
photographer, so the importer is told). Locks the tech-box layout:
  tagged   + tech → PICS/<stage>/<Tech date>/[<room>]
  untagged + tech → PICS/<Tech date>/[<room>]   (when NO stage in the zip)
  no tech          → PICS/<stage>/… or PICS/CompanyCam <date>/…

Each container's room subfoldering follows the per-batch rule (flatten
one/none room, organize 2+). To isolate the tech-box behavior these zips
use 2 distinct rooms per container.
"""
import zipfile
import companycam_import as cc


def _make_zip(tmp_path, names):
    z = tmp_path / "photos-2026-06-09-aaaa.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for n in names:
            zf.writestr(f"Sayra Mansolino/{n}", b"\xff\xd8\xff\xe0")  # fake jpg
    return str(z)


def test_tech_box_under_stage(tmp_path):
    # Tagged photos → PICS/<stage>/<Tech date>/<room>.
    pics = tmp_path / "PICS"
    pics.mkdir()
    z = _make_zip(tmp_path, [
        "Kitchen Demo-1-Jun 9 2026 10_00am-aa.jpg",
        "Garage Demo-2-Jun 9 2026 10_01am-bb.jpg",
    ])
    cc.import_zip(z, str(pics), date_label="06-09-2026", tech="Nestor")
    assert (pics / "Demo" / "Nestor 06-09-2026" / "Kitchen").is_dir()
    assert (pics / "Demo" / "Nestor 06-09-2026" / "Garage").is_dir()


def test_tech_box_as_container_when_no_stage(tmp_path):
    # Zip with NO stage tag at all → the tech box is the container itself.
    pics = tmp_path / "PICS"
    pics.mkdir()
    z = _make_zip(tmp_path, [
        "Master Bath-1-Jun 9 2026 10_00am-aa.jpg",
        "Garage-2-Jun 9 2026 10_01am-bb.jpg",
    ])
    cc.import_zip(z, str(pics), date_label="06-09-2026", tech="Nestor")
    assert (pics / "Nestor 06-09-2026" / "Master Bath").is_dir()
    assert (pics / "Nestor 06-09-2026" / "Garage").is_dir()
    assert not (pics / "Demo").exists()


def test_no_tech_layout(tmp_path):
    pics = tmp_path / "PICS"
    pics.mkdir()
    z = _make_zip(tmp_path, [
        "Kitchen Demo-1-Jun 9 2026 10_00am-aa.jpg",
        "Garage Demo-2-Jun 9 2026 10_01am-bb.jpg",
    ])
    cc.import_zip(z, str(pics), date_label="06-09-2026")
    assert (pics / "Demo" / "Kitchen").is_dir()
    assert (pics / "Demo" / "Garage").is_dir()
