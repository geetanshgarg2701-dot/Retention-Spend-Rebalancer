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


def test_a_missing_env_file_is_harmless():
    assert aiconfig.load_env() is False


def test_the_settings_never_appear_in_an_error_or_repr(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "supersecretvalue")
    monkeypatch.setenv("GEMINI_MODEL", "some-model")
    fn = gemini_ai_function()
    assert fn is not None and "supersecretvalue" not in repr(fn)
