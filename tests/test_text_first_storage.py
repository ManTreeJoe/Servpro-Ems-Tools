"""Guard Linguar Hub's databases as metadata indexes, never file stores."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def _schema_sources():
    yield ROOT / "ems_db_sqlite.py"
    yield from sorted((ROOT / "supabase").glob("*.sql"))


def test_database_schemas_have_no_binary_file_columns():
    # Match a SQL column declaration, not explanatory prose such as
    # "JSON blob" in a Python comment.
    forbidden_types = re.compile(
        r"^\s*[A-Za-z_]\w*\s+(blob|bytea|binary|varbinary)\b", re.I | re.M)
    for path in _schema_sources():
        text = path.read_text(encoding="utf-8")
        assert not forbidden_types.search(text), f"binary storage added in {path.name}"


def test_database_schemas_do_not_name_encoded_file_payloads():
    forbidden_names = re.compile(
        r"\b(file_data|document_data|photo_data|video_data|base64_data)\b", re.I)
    for path in _schema_sources():
        text = path.read_text(encoding="utf-8")
        assert not forbidden_names.search(text), f"encoded file storage added in {path.name}"


def test_policy_explicitly_keeps_documents_out_of_database():
    policy = (ROOT / "DATA_STORAGE_POLICY.md").read_text(encoding="utf-8")
    assert "Never store" in policy
    assert "Base64" in policy
    assert "metadata only" in policy
