import pytest


@pytest.fixture(autouse=True)
def isolate_ai(monkeypatch, tmp_path):
    """No test may see a real key or call the model, even when a real .env exists in the project."""
    from src import aiconfig

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    # python-dotenv writes loaded values straight into the environment, so clear every setting we read before each test.
    monkeypatch.delenv("AI_DAILY_LIMIT", raising=False)
    monkeypatch.setattr(aiconfig, "ENV_PATH", tmp_path / "no-such.env")
    monkeypatch.setattr(aiconfig, "_secret", lambda name: None)
    # A fresh shared daily cap for each test, and errors in the app are raised so tests cannot miss them.
    from src import insights

    monkeypatch.setattr(insights, "GLOBAL_DAILY", insights.DailyBudget(limit=100_000))
    monkeypatch.setenv("RSR_RAISE_ERRORS", "1")
