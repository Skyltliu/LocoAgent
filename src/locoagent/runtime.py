import json
import hashlib
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from .session_store import SessionStore
from . import tools as toolkit
from .tool_context import ToolContext
from .tool_executor import ToolExecutor
from .prompt_prefix import build_prompt_prefix
from .workspace import IGNORED_PATHS, MAX_HISTORY, WorkspaceContext, clip, now
class LocoAgent:
    def __init__(self, model_client, workspace, session_store, session=None, max_new_tokens=512, read_only=False, allowed_tools=None,):
        self.workspace = workspace
        self.max_new_tokens = max_new_tokens
        self.model_client = model_client
        
        self.read_only = read_only
        self.session_store = session_store
        self.allowed_tools = self._normalize_allowed_tools(allowed_tools)
        self.session = session or {
            "id": datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6],
            "created_at": now(),
            "workspace_root": workspace.repo_root,
            "history": [],
        }
        self._ensure_session_shape()
        self.tools = self._apply_tool_allowlist(self.build_tools())
        self.tool_executor = ToolExecutor(self)
        self.session_path = self.session_store.save(self.session)
        self.prefix_state = self.build_prefix()
        self.prefix = self.prefix_state.text
        

    #phase 2 functions
    def _normalize_allowed_tools(allowed_tools):
        if allowed_tools is None:
            return None
        normalized = tuple(str(name).strip() for name in allowed_tools)
        if not normalized or any(not name for name in normalized):
            raise ValueError("allowed_tools must be a non-empty sequence of tool names")
        return normalized

    def history_text(self):
        history = self.session["history"]
        if not history:
            return "- empty"
        lines = []
        seen_reads = set()
        recent_start = max(0, len(history)-6)
        for index, item in enumerate(history):
            recent = index >= recent_start
            if item["role"] == "tool" and item["name"] == "read_file" and not recent:
                path = str(item["args"].get("path", ""))
                if path in seen_reads:
                    continue
                seen_reads.add(path)
            if item["role"] == "tool":
                limit = 900 if recent else 180
                lines.append(f"[tool:{item['name']}] {json.dumps(item['args'], sort_keys=True)}")
                lines.append(clip(item["content"], limit))
            else:
                limit = 900 if recent else 220
                lines.append(f"[{item['role']}] {clip(item['content'], limit)}")
        return clip("\n".join(lines), MAX_HISTORY)

    def _apply_tool_allowlist(self, tools):
        pass


    def build_tools(self):
        return toolkit.build_tool_registry(self.tool_context())

    def validate_tool(self, name, args):
        toolkit.validate_tool(self.tool_context(), name, args)

    def tool_context(self):
        return ToolContext(
            root=self.root,
            path_solver=self.path,
            shell_env_provider=self.shell_env,
            depth=self.depth,
            max_depth=self.max_depth,

        )

    def path(self, raw_path):
        pass

    def shell_env(self):
        pass

    def approve(self, name, args):
        pass

    def capture_workspace_snapshot(self):
        pass

    @staticmethod
    def diff_workspace_snapshots(before, after):
        pass

    
    #phase 1 functions
    def _ensure_session_shape(self):
        """
        normalize session dict on load. At this phase
        it's just `self.session.setdefault("history", [])`; the other four
        setdefault/type-check blocks (memory / checkpoints / runtime_identity /
        resume_state) belong to Phase 4 and Phase 7 respectively
        """
        self.session.setdefault("history", [])
    
    def build_prefix(self):
        return build_prompt_prefix(workspace=self.workspace)

    
    def prompt(self, user_message):
        """
        literal naive concatenation (`self.prefix + "\n\n" + user_message`)
        """
        return self.prefix + "\n\n" + user_message

    #mods required
    def ask(self, user_message):
        """
        At this phase write it as a small self-contained loop with no `kind == "tool"` branch (Phase 2), no
        task_state/trace (Phase 3), no AgentLoop extraction (Phase 3), no
        checkpoint/resume branching (Phase 7), no redaction (Phase 8), and no
        durable-memory promotion (Phase 10).
        """
        self.record({"role":"user", "content":user_message, "created_at": now()})
        prompt = self.prompt(user_message)
        for _ in range(3):
            raw = self.model_client.complete(prompt, self.max_new_tokens)
            kind, payload = self.parse(raw)
            if kind == "final":
                self.record({"role":"assistant", "content":payload, "created_at": now()})
                return payload
            #if kind == "retry", payload is the retry_notice text; append it to prompt and ask again
            prompt = prompt + "\n\n" + payload
        return "Stopped after too many malformed responses."
    
    def record(self, item):
        self.session['history'].append(item)
        self.session_path = self.session_store.save(self.session)

    @staticmethod
    def retry_notice(problem=None):
        prefix = "Runtime notice"
        if problem:
            prefix += f": {problem}"
        else:
            prefix += ": model returned malformed tool output"
        return (
            f"{prefix}. Reply with a valid <tool> call or a non-empty <final> answer. "
            'For multi-line files, prefer <tool name="write_file" path="file.py"><content>...</content></tool>.'
        )

    #phase 2 mods required
    @staticmethod
    def parse(raw):
        """
        only needs the `<final>` and empty/plain-text branches
        returning ("final", ...) / ("retry", ...). Skip the `<tool>`/`<tool ...>`
        branches entirely — there's nothing to call one yet.
        
        """
        raw = str(raw)
        if "<final>" in raw:
            final = LocoAgent.extract(raw, "final").strip()
            if final:
                return "final", final
            return "retry", LocoAgent.retry_notice("model returned an empty <final> answer")
        if raw:
            return "final", raw
        return "retry", LocoAgent.retry_notice("model returned an empty response")


    @staticmethod
    def extract(text, tag):
        start_tag = f"<{tag}>"
        end_tag = f"</{tag}>"
        start = text.find(start_tag)
        if start == -1:
            return text
        start += len(start_tag)
        end = text.find(end_tag, start)
        if end == -1:
            return text[start:].strip()
        return text[start:end].strip()
    



    
