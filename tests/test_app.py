"""app.py 的启动自检：key 检查交给 Settings，缺 key 只提示不拦启动，配置写错才拦。"""

import pytest

import app


@pytest.fixture
def env_file(monkeypatch, tmp_path):
    for name in ["ANTHROPIC_API_KEY", "STEEL_API_KEY", "PAIRER"]:
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / ".env"

    def write(text):
        path.write_text(text, encoding="utf-8")
        return path

    return write


def test_missing_key_is_reported_but_does_not_block_startup(env_file, capsys):
    settings = app.load_settings(env_file("ANTHROPIC_API_KEY=sk-test\n"))
    out = capsys.readouterr().out
    assert settings is not None
    assert "ANTHROPIC_API_KEY 已配置" in out
    assert "缺少 STEEL_API_KEY" in out
    assert "sk-test" not in out


def test_all_keys_present(env_file, capsys):
    assert app.load_settings(env_file("ANTHROPIC_API_KEY=a\nSTEEL_API_KEY=b\n")) is not None
    assert "缺少" not in capsys.readouterr().out


def test_invalid_setting_blocks_startup(env_file, capsys):
    assert app.load_settings(env_file("PAIRER=bogus\n")) is None
    assert "PAIRER=bogus" in capsys.readouterr().out
