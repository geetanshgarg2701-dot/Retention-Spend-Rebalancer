import pytest

from src import aiconfig
from src.mapper import gemini_ai_function


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.setattr(aiconfig, "ENV_PATH", tmp_path / "missing.env")
    monkeypatch.setattr(aiconfig, "_secret", lambda name: None)


def write_env(path, text):
    path.write_text(text, encoding="utf-8")
    return path


def test_nothing_configured_means_no_ai():
    assert aiconfig.get_settings() == (None, None)
    assert aiconfig.ai_available() is False and gemini_ai_function() is None


def test_environment_variables_are_read(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "abc123")
    monkeypatch.setenv("GEMINI_MODEL", "some-model")
    assert aiconfig.get_settings() == ("abc123", "some-model") and aiconfig.ai_available()


def test_a_local_env_file_is_read_when_nothing_else_is_set(monkeypatch, tmp_path):
    path = write_env(tmp_path / ".env", "GEMINI_API_KEY=fromfile\nGEMINI_MODEL=file-model\n")
    monkeypatch.setattr(aiconfig, "ENV_PATH", path)
    assert aiconfig.get_settings() == ("fromfile", "file-model")


def test_real_environment_variables_win_over_the_env_file(monkeypatch, tmp_path):
    path = write_env(tmp_path / ".env", "GEMINI_API_KEY=fromfile\nGEMINI_MODEL=file-model\n")
    monkeypatch.setattr(aiconfig, "ENV_PATH", path)
    monkeypatch.setenv("GEMINI_API_KEY", "fromenv")
    assert aiconfig.get_settings() == ("fromenv", "file-model")


def test_the_placeholder_key_counts_as_missing(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "your-key-here")
    monkeypatch.setenv("GEMINI_MODEL", "some-model")
    assert aiconfig.get_settings() == (None, "some-model") and not aiconfig.ai_available()


def test_streamlit_secrets_are_the_last_fallback(monkeypatch):
    monkeypatch.setattr(aiconfig, "_secret", lambda name: {"GEMINI_API_KEY": "fromsecret", "GEMINI_MODEL": "secret-model"}.get(name))
    assert aiconfig.get_settings() == ("fromsecret", "secret-model")


def test_any_setting_is_read_from_the_environment_then_the_env_file_then_secrets(monkeypatch, tmp_path):
    assert aiconfig.get_value("AI_DAILY_LIMIT") is None
    monkeypatch.setattr(aiconfig, "_secret", lambda name: "from-secrets" if name == "AI_DAILY_LIMIT" else None)
    assert aiconfig.get_value("AI_DAILY_LIMIT") == "from-secrets"
    path = write_env(tmp_path / ".env", "AI_DAILY_LIMIT=from-file\n")
    monkeypatch.setattr(aiconfig, "ENV_PATH", path)
    assert aiconfig.get_value("AI_DAILY_LIMIT") == "from-file"
    monkeypatch.setenv("AI_DAILY_LIMIT", "from-env")
    assert aiconfig.get_value("AI_DAILY_LIMIT") == "from-env"
    monkeypatch.delenv("AI_DAILY_LIMIT")
    assert aiconfig.get_value("AI_DAILY_LIMIT") == "from-file"  # dotenv loaded it into the environment above


def test_the_daily_ai_limit_can_come_from_streamlit_secrets(monkeypatch):
    from src.insights import DailyBudget

    monkeypatch.setattr(aiconfig, "_secret", lambda name: "12" if name == "AI_DAILY_LIMIT" else None)
    assert DailyBudget().limit == 12


def test_the_secrets_example_contains_only_placeholders_and_is_not_ignored_by_git():
    from pathlib import Path

    root = Path(__file__).parent.parent
    example = (root / ".streamlit" / "secrets.toml.example").read_text(encoding="utf-8")
    assert 'GEMINI_API_KEY = "your-key-here"' in example and "AIza" not in example
    ignore = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".streamlit/secrets.toml" in ignore and "secrets.toml.example" not in " ".join(ignore)


def test_a_missing_env_file_is_harmless():
    assert aiconfig.load_env() is False


def test_the_settings_never_appear_in_an_error_or_repr(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "supersecretvalue")
    monkeypatch.setenv("GEMINI_MODEL", "some-model")
    fn = gemini_ai_function()
    assert fn is not None and "supersecretvalue" not in repr(fn)
