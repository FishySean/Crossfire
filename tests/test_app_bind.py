"""默认只监听本机；绑到 0.0.0.0 必须警告。"""

from app import HOST, warn_if_public_bind


def test_mutation_default_host_is_loopback():
    """变异目标：服务默认监听 0.0.0.0。"""
    assert HOST == "127.0.0.1"


def test_public_bind_prints_loud_warning(capsys):
    warn_if_public_bind("0.0.0.0")
    out = capsys.readouterr().out
    assert "警告" in out
    assert "0.0.0.0" in out
    assert "API" in out


def test_loopback_bind_is_silent(capsys):
    warn_if_public_bind("127.0.0.1")
    assert capsys.readouterr().out == ""
