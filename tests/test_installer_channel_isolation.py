from pathlib import Path


def test_installer_only_closes_the_current_channel_executable():
    script = (Path(__file__).parents[1] / "Linguar_Hub.iss").read_text(
        encoding="utf-8")
    assert "CloseApplicationsFilter={#MyAppExe}" in script
