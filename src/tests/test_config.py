import pytest
from locoagent.config import _strip_quotes, _parse_env_line, find_env, load_env

def test_strip_quotes():
    assert _strip_quotes('"hi"') == "hi"
    assert _strip_quotes("'hi'") == "hi"
    assert _strip_quotes("hi") == "hi"
    assert _strip_quotes('"mismatched\'') == '"mismatched\''
def test_parse_env_line_basic():
    assert _parse_env_line("FOO=bar") == ("FOO", "bar")

def test_parse_env_line_skips_comments_and_blanks():
    assert _parse_env_line("  # comment") is None
    assert _parse_env_line("") is None

def test_parse_env_line_rejects_bad_name():
    with pytest.raises(ValueError):
        _parse_env_line("1FOO=bar")

def test_parse_env_line_export_prefix():
    assert _parse_env_line("export FOO=bar") == ("FOO", "bar")

def test_load_env_finds_and_sets(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text('FOO="baz"\n# x\nexport BAR=qux\n')
    monkeypatch.delenv("FOO", raising=False)
    out = load_env(tmp_path)
    assert out["FOO"] == "baz"