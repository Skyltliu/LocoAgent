import shutil
import subprocess
import textwrap
from functools import partial
from .workspace import IGNORED_PATHS

BASE_TOOL_SPECS = {
    "list_files": {
        "schema": {"path": "str='.'"},
        "risky": False,
        "description": "List files in the workspace.",
    },
    "read_file": {
        "schema": {"path": "str", "start": "int=1", "end": "int=200"},
        "risky": False,
        "description": "Read a UTF-8 file by line range.",
    },
    "search": {
        "schema": {"pattern":"str", "path": "str='.'"},
        "risky": False,
        "description": "Search the workspace with ripgrep or a simple fallback.",
    },
    "run_shell": {
        "schema": {"command": "str", "timeout": "int=20"},
        "risky": True,
        "description": "Run a shell command in the repo root.",
    },
    "write_file": {
        "schema": {"path":"str", "content":"str"},
        "risky": True,
        "description": "Write a text file.",
    },
    "patch_file": {
        "schema": {"path":"str", "old_text":"str", "new_text":"str"},
        "risky": True,
        "description": "Replace one exact text block in a file.",
    },
}

def legal_tool_names():
    return set(BASE_TOOL_SPECS) | {"delegate"}

TOOL_EXAMPLES = {
    "list_files": '<tool>{"name":"list_files", "args":{"path":"."}}</tool>',
    "read_file": '<tool>{"name":"read_file","args":{"path":"README.md","start":1, "end":80}}</tool>',
    "search": '<tool>{"name":"search","args":{"pattern":"binary_search","path":"."}}</tool>',
    "run_shell": '<tool>{"name":"run_shell","args":{"command":"uv run --with pytest python -m pytest -q","timeout":20}}</tool>',
    "write_file": '<tool name="write_file" path="binary_search.py"><content>def binary_search(nums, target):\n    return -1\n</content></tool>',
    "patch_file": '<tool name="patch_file" path="binary_search.py"><old_text>return -1</old_text><new_text>return mid</new_text></tool>',
    "delegate": '<tool>{"name":"delegate","args":{"task":"inspect README.md","max_steps":3}}</tool>',
}

def build_tool_registry(context):
    tools = {
        name: {**spec, "run":partial(_TOOL_RUNNERS[name], context)} for name, spec in BASE_TOOL_SPECS.items()
    }
    return tools

def tool_example(name):
    return TOOL_EXAMPLES.get(name, "")

def validate_tool(context, name, args):
    pass

def tool_list_files(context, args):
    pass

def tool_read_file(context, args):
    pass

def tool_search(context, args):
    pass

def tool_run_shell(context, args):
    pass

def tool_write_file(context, args):
    pass

def tool_patch_file(context, args):
    pass


_TOOL_RUNNERS = {
    "list_files": tool_list_files,
    "read_file": tool_read_file,
    "search": tool_search,
    "run_shell": tool_run_shell,
    "write_file": tool_write_file,
    "patch_file": tool_patch_file,
}