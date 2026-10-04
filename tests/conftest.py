import pytest


@pytest.fixture(autouse=True)
def isolate_ai(monkeypatch, tmp_path):
    """No test may see a real key or call the model, even when a real .env exists in the project."""
    from src import aiconfig

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.setattr(aiconfig, "ENV_PATH", tmp_path / "no-such.env")
    monkeypatch.setattr(aiconfig, "_secret", lambda name: None)
