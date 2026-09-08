"""命令行入口。

这个模块负责把“用户怎么启动 locoagent”翻译成 runtime 能理解的对象：
解析参数、挑模型后端、构建工作区快照、恢复或新建 session，
最后进入 one-shot 或交互式循环。
"""
from .runtime import LocoAgent
from .config import get_env, load_env
import argparse
import os
import sys
import textwrap
import shutil
from pathlib import Path
from .providers.clients import OpenAICompatibleModelClient
PROVIDER_CHOICES = ("openai",)
DEFAULT_PROVIDER = "openai"
DEFAULT_OPENAI_MODEL = "gpt-5.4"
DEFAULT_OPENAI_BASE_URL = "https://www.right.codes/codex/v1"

def _effective_providers(args):
    provider = getattr(args, "provider", None) or get_env("LLM_OPENAI_PROVIDER", DEFAULT_PROVIDER)
    if provider not in PROVIDER_CHOICES:
        raise ValueError("not a valid provider choice bozo")
    return provider

def _effective_model(args, provider):
    model = getattr(args, "model", None)
    if model:
        return model
    if provider == "openai":
        model = get_env("LLM_OPENAI_MODEL")
        if model:
            return model
        return DEFAULT_OPENAI_MODEL
    return DEFAULT_OPENAI_MODEL


def build_arg_parse():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="Minimal coding agent for OpenAI models.",
    )
    parser.add_argument("prompt", nargs="*", help="One-shot prompt")
    parser.add_argument("--model", default=None, help="Model select, defaults to LLM_OPENAI_MODEL")
    parser.add_argument("--provider", default=None, choices=PROVIDER_CHOICES, help="Model backend, defaults to LLM_OPENAI_PROVIDER")
    parser.add_argument("--cwd", default=".", help="Workspace directory")
    parser.add_argument("--base_url", default=None, help="Provide URL for openai")
    parser.add_argument("--secret_envs", dest="secrets", action="append", default=[], help="environment variable names to treat as secrets for trace")
    parser.add_argument("--max_steps", type=int, default=6, help="Maximum tool iterations per request")
    parser.add_argument("--max_new-tokens", type=int, default=4096, help="Maximum model output tokens per step")
    parser.add_argument("--temperature", type=float, default=0.9, help="Model output randomness")
    return parser

def _build_model_client(args):
    provider = _effective_providers(args)
    
    model = _effective_model(args, provider)
    base_url = getattr(args, "base_url", None) or get_env("LLM_OPENAI_API_BASE", DEFAULT_OPENAI_BASE_URL)
    api_key = get_env("LLM_OPENAI_API_KEY")
    return OpenAICompatibleModelClient(model=model, base_url=base_url, api_key=api_key, temperature=args.temperature, timeout=getattr(args, "openai_timeout", 300))

def build_agent(args):
    pass

def main(argv=None):
    load_env(Path.cwd())
    api_key = get_env("LLM_OPENAI_API_KEY")

    print("API key loaded:", bool(api_key))
    print("API key length:", len(api_key))
    parser = build_arg_parse()
    args = parser.parse_args(argv)
    client = _build_model_client(args)
    if not args.prompt:
        prompt = input("locoagent> ").strip()
    else:
        prompt = " ".join(args.prompt).strip()
    if not prompt:
        return 0
    response = client.complete(prompt)
    print(response)
    return 0


