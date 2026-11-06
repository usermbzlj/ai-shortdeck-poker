import pytest

collect_ignore = ["test_api.py"]

@pytest.fixture(autouse=True)
def isolated_history(monkeypatch, tmp_path):
    monkeypatch.setenv("SHORTDECK_DATA_DIR", str(tmp_path / "data"))
