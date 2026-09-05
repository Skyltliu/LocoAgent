import argparse

import pytest

from locoagent.cli import (
    DEFAULT_OPENAI_MODEL,
    DEFAULT_PROVIDER,
    _effective_model,
    _effective_providers,
    build_arg_parse,
)


def _args(**overrides):
    """A stand-in for parsed CLI args. Only the attributes a test sets exist."""
    return argparse.Namespace(**overrides)


# --- _effective_providers -------------------------------------------------

def test_effective_providers_defaults_when_nothing_set(monkeypatch):
    monkeypatch.delenv("LLM_OPENAI_PROVIDER", raising=False)
    assert _effective_providers(_args(provider=None)) == DEFAULT_PROVIDER


def test_effective_providers_prefers_cli_arg(monkeypatch):
    monkeypatch.setenv("LLM_OPENAI_PROVIDER", "openai")
    assert _effective_providers(_args(provider="openai")) == "openai"


def test_effective_providers_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("LLM_OPENAI_PROVIDER", "openai")
    assert _effective_providers(_args(provider=None)) == "openai"


def test_effective_providers_rejects_unknown(monkeypatch):
    monkeypatch.delenv("LLM_OPENAI_PROVIDER", raising=False)
    with pytest.raises(ValueError):
        _effective_providers(_args(provider="anthropic"))


# --- _effective_model ----------------------------------------------------

def test_effective_model_cli_arg_wins(monkeypatch):
    monkeypatch.setenv("LLM_OPENAI_MODEL", "from-env")
    assert _effective_model(_args(model="from-cli"), "openai") == "from-cli"


def test_effective_model_uses_env_when_no_arg(monkeypatch):
    monkeypatch.setenv("LLM_OPENAI_MODEL", "gpt-from-env")
    assert _effective_model(_args(model=None), "openai") == "gpt-from-env"


def test_effective_model_defaults_when_nothing_set(monkeypatch):
    monkeypatch.delenv("LLM_OPENAI_MODEL", raising=False)
    assert _effective_model(_args(model=None), "openai") == DEFAULT_OPENAI_MODEL


# --- build_arg_parse ---------------------------------------------------------

def test_parser_defaults():
    args = build_arg_parse().parse_args([])
    assert args.prompt == []
    assert args.provider is None
    assert args.max_steps == 6
    assert args.cwd == "."


def test_parser_collects_prompt_and_options():
    args = build_arg_parse().parse_args(["hello", "world", "--max_steps", "3"])
    assert args.prompt == ["hello", "world"]
    assert args.max_steps == 3


def test_parser_rejects_bad_provider():
    with pytest.raises(SystemExit):
        build_arg_parse().parse_args(["--provider", "nope"])
