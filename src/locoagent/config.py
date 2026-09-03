import os
from pathlib import Path
import re

VALID_ENV_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
def _strip_quotes(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value

def _parse_env_line(line):
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("export "):
        line = line[len(7):].strip()
    if "=" not in line:
        raise ValueError("Invalid .env line")
    name, value = line.split("=", 1)
    name = name.strip()
    if not VALID_ENV_PATTERN.match(name):
        raise ValueError("Invalid .env variable name")
    return name, _strip_quotes(value)


def get_env(name, default=""):
    return os.environ.get(name, default)

def find_env(start):
    current = Path(start).resolve()
    if current.is_file():
        current = current.parent
    for path in (current, *current.parents):
        env_path = path / ".env"
        if env_path.exists():
            return env_path
    return None

def load_env(start, override=True):
    env_path = find_env(start)
    if not env_path:
        return {}
    to_return = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_env_line(line)
        if parsed is None:
            continue
        name, value = parsed
        to_return[name] = value
        if override or name not in os.environ:
            os.environ[name] = value
    return to_return