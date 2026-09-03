"""工作区快照工具。

这个模块负责在 agent 按需读文件之前，先给它一份便宜的“仓库第一印象”。
这份快照刻意保持小而稳定：主要包含 Git 事实和少量白名单项目文档。
"""

import subprocess
import textwrap
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

class WorkspaceContext:
    def __init__():
        pass