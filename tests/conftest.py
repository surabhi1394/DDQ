import pytest


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Keep saved settings and reviews out of the working tree, and ignore real credentials."""
    monkeypatch.setenv("DDQ_DATA_DIR", str(tmp_path / "ddq_data"))
    for key in ("ANTHROPIC_API_KEY", "FIRST_STREET_API_KEY", "ESPM_USERNAME", "ESPM_PASSWORD",
                "CRREM_PATHWAYS_CSV", "CAMBIUM_CSV", "PHYSRISK_API_URL", "BPD_API_KEY", "AUDETTE_API_KEY", "DDQ_PASSWORD", "DDQ_USERNAME"):
        monkeypatch.delenv(key, raising=False)
