
import hashlib
import json
import textwrap
from dataclasses import dataclass

from .workspace import now

@dataclass
class PromptPrefix:
    text: str
    hash: str
    workspace_fingerprint: str
    built_at: str

def build_prompt_prefix(workspace, tools=None, built_at=None):
    """
    identity + rules + workspace.text()
    """
    examples = "\n".join(
        [
            "<final>Done.</final>",
        ]
    )
    text = textwrap.dedent(
        f"""\
        You are LocoAgent, a small local coding agent working inside a local repository.

        Rules:
        - Return one <final>...</final>.
        - Final answers must look like:
          <final>your answer</final>
        - Keep answers concise and concrete.
        - Before writing tests for existing code, read the implementation first.
        - When writing tests, match the current implementation unless the user explicitly asked you to change the code.
        - New files should be complete and runnable, including obvious imports.

        Valid response examples:
        {examples}
            
        {workspace.text()}
        """
    ).strip()
    return PromptPrefix(
        text=text,
        hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        workspace_fingerprint=workspace.fingerprint(),
        built_at=built_at or now(),
    )
