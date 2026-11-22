"""Settings：唯一读 .env 和环境变量的地方。用 tmp_path 里的假 .env，不碰仓库里真的那份。"""

import os

import pytest

from crossfire.config import DEFAULT_MODEL, ROOT, Key, Pairer, Settings, SettingsError, load_questions

ALL_NAMES = [
    "ANTHROPIC_API_KEY",
    "STEEL_API_KEY",
    "MODEL_EXTRACT",
    "MODEL_PAIR",
    "MODEL_JUDGE",
    "PAIRER",
    "CROSSFIRE_RUNS_DIR",
    "CROSSFIRE_CACHE_DIR",
    "CROSSFIRE_QUESTIONS_FILE",
    "CROSSFIRE_EVALS_DIR",
    "CROSSFIRE_EVAL_RUNS_DIR",
    "CROSSFIRE_EXTRACT_CONCURRENCY",
]


@pytest.fixture
def env_file(monkeypatch, tmp_path):
    for name in ALL_NAMES:
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / ".env"

    def write(text=""):
        path.write_text(text, encoding="utf-8")
        return path

    return write


def test_defaults(env_file):
    settings = Settings.from_env(env_file())
    assert settings.anthropic_api_key is None and settings.steel_api_key is None
    assert (settings.model_extract, settings.model_pair, settings.model_judge) == (DEFAULT_MODEL,) * 3
    assert DEFAULT_MODEL == "claude-sonnet-4-6"
    assert settings.pairer is Pairer.CLAUDE
    assert settings.runs_dir == ROOT / "out" / "runs"
    assert settings.cache_dir == ROOT / "out" / "cache"
    assert settings.questions_file == ROOT / "questions" / "demo.yaml"


def test_reads_the_env_file_without_touching_os_environ(env_file):
    path = env_file("ANTHROPIC_API_KEY=sk-file\nMODEL_JUDGE=claude-opus-x\nCROSSFIRE_RUNS_DIR=/tmp/elsewhere\n")
    settings = Settings.from_env(path)
    assert settings.anthropic_api_key == "sk-file"
    assert settings.model_judge == "claude-opus-x"
    assert settings.model_extract == DEFAULT_MODEL
    assert str(settings.runs_dir) == "/tmp/elsewhere"
    assert "ANTHROPIC_API_KEY" not in os.environ


def test_environment_variables_win_over_the_file(env_file, monkeypatch):
    path = env_file("STEEL_API_KEY=from-file\n")
    monkeypatch.setenv("STEEL_API_KEY", "from-env")
    assert Settings.from_env(path).steel_api_key == "from-env"


def test_relative_dirs_resolve_against_the_project_root(env_file):
    settings = Settings.from_env(env_file("CROSSFIRE_CACHE_DIR=tmp/cache\n"))
    assert settings.cache_dir == ROOT / "tmp" / "cache"


@pytest.mark.parametrize("value", ["", "   ", "your_anthropic_api_key_here"])
def test_blank_or_placeholder_key_counts_as_missing(env_file, value):
    settings = Settings.from_env(env_file(f"ANTHROPIC_API_KEY={value}\n"))
    assert settings.anthropic_api_key is None
    assert settings.missing(Key.ANTHROPIC) == [Key.ANTHROPIC]


def test_nothing_is_required_by_default(env_file):
    Settings.from_env(env_file())


def test_missing_required_key_fails_inside_from_env_and_says_where_to_set_it(env_file):
    path = env_file("ANTHROPIC_API_KEY=sk-file\n")
    with pytest.raises(SettingsError) as caught:
        Settings.from_env(path, require=[Key.ANTHROPIC, Key.STEEL])
    message = str(caught.value)
    assert "STEEL_API_KEY" in message
    assert "ANTHROPIC_API_KEY" not in message
    assert str(path) in message
    assert ".env.example" in message
    assert "Steel" in message


def test_every_missing_key_is_named(env_file):
    with pytest.raises(SettingsError) as caught:
        Settings.from_env(env_file(), require=[Key.ANTHROPIC, Key.STEEL])
    assert "ANTHROPIC_API_KEY" in str(caught.value) and "STEEL_API_KEY" in str(caught.value)


def test_unknown_pairer_is_rejected_with_the_allowed_values(env_file):
    with pytest.raises(SettingsError, match="bogus.*claude"):
        Settings.from_env(env_file("PAIRER=bogus\n"))


def test_nli_pairer_is_a_valid_setting(env_file):
    settings = Settings.from_env(env_file("PAIRER=nli\nNLI_MODEL=models/crossfire-pairer-v1\n"))
    assert settings.pairer.value == "nli"
    assert settings.nli_model == "models/crossfire-pairer-v1"


def test_settings_are_frozen(env_file):
    settings = Settings.from_env(env_file())
    with pytest.raises(AttributeError):
        settings.model_pair = "other"  # type: ignore[misc]


def test_load_questions(env_file, tmp_path):
    questions = tmp_path / "q.yaml"
    questions.write_text(
        "- id: q1\n  question: 几点了？\n  sources:\n    - {url: 'https://a.example/', tier: primary}\n",
        encoding="utf-8",
    )
    settings = Settings.from_env(env_file(f"CROSSFIRE_QUESTIONS_FILE={questions}\n"))
    [question] = load_questions(settings)
    assert question.id == "q1" and question.sources[0].url == "https://a.example/"


def test_missing_questions_file_gives_no_questions(env_file, tmp_path):
    settings = Settings.from_env(env_file(f"CROSSFIRE_QUESTIONS_FILE={tmp_path / 'nope.yaml'}\n"))
    assert load_questions(settings) == []


def test_extract_concurrency_defaults_to_4_and_must_be_a_positive_integer(env_file):
    assert Settings.from_env(env_file()).extract_concurrency == 4
    assert Settings.from_env(env_file("CROSSFIRE_EXTRACT_CONCURRENCY=8\n")).extract_concurrency == 8
    for bad in ["0", "-1", "many"]:
        with pytest.raises(SettingsError, match="CROSSFIRE_EXTRACT_CONCURRENCY"):
            Settings.from_env(env_file(f"CROSSFIRE_EXTRACT_CONCURRENCY={bad}\n"))
