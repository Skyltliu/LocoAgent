"""Narrow context passed from runtime into tool functions."""
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

@dataclass
class ToolContext:
    root: Path
    path_resolver: Callable[[str], Path]
    shell_env_provider: Callable[[], dict]
    depth: int

    def path(self, raw_path):
        return self.path_resolver(str(raw_path))

    def shell_env(self):
        return self.shell_env_provider()