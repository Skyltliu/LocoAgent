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
    def __init__(self, model_client, workspace, session_store, session=None, approval_policy="ask", max_new_tokens=512, depth=0, max_depth=0, read_only=False, allowed_tools=None,):
        self.workspace = workspace
        self.max_new_tokens = max_new_tokens
        self.depth = depth
        self.max_depth = max_depth
        self.model_client = model_client
        self.root = Path(workspace.repo_root)
        self.approval_policy = approval_policy
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
        self._last_tool_result_metadata = {}

    #phase 2 functions
    def _normalize_allowed_tools(self, allowed_tools):
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
        if self.allowed_tools is None:
            return tools
        legal_names = toolkit.legal_tool_names()
        unknown = [name for name in self.allowed_tools if name not in legal_names]
        if unknown:
            raise ValueError(f"unknown allowed tool: {', '.join(unknown)}")
        allowed = set(self.allowed_tools)
        return {
            name: tool
            for name, tool in tools.items()
            if name in allowed
        }


    def build_tools(self):
        return toolkit.build_tool_registry(self.tool_context())

    def validate_tool(self, name, args):
        toolkit.validate_tool(self.tool_context(), name, args)

    def tool_context(self):
        return ToolContext(
            root=self.root,
            path_resolver=self.path,
            shell_env_provider=self.shell_env,
            depth=self.depth,
        )

    def path(self, raw_path):
        path = Path(raw_path)
        path = path if path.is_absolute() else self.root / path
        resolved = path.resolve()
        if os.path.commonpath([str(self.root), str(resolved)]) != str(self.root):
            raise ValueError(f"path escapes workspace: {raw_path}")
        return resolved

    def shell_env(self):
        return dict(os.environ)

    def approve(self, name, args):
        if self.read_only:
            return False
        if self.approval_policy == "auto":
            return True
        if self.approval_policy == "never":
            return False
        try:
            answer = input(f"approve {name} {json.dumps(args, ensure_ascii=True)}? [y/N] ")
        except EOFError:
            return False
        return answer.strip().lower() in {"y", "yes"}

    def capture_workspace_snapshot(self):
        pass

    @staticmethod
    def diff_workspace_snapshots(before, after):
        pass

    def repeated_tool_call(self, name, args):
        pass

    def execute_tool(self, name, args):
        result = self.tool_executor.execute(name, args)
        self._last_tool_result_metadata = dict(result.metadata)
        return result

    def run_tool(self, name, args):
        """
        Execute a single tool call with the full set of safeguards applied before and after execution.
        Why this exists:
        In an agent system, the real danger is not "whether the model wants to call a tool," but
        "whether the platform enforces boundaries before execution." This function is the main
        gatekeeper for the tool layer: every tool call must pass through it, and the model must
        never be allowed to call the underlying tool functions directly.

        Input / output:
        - Input: tool name `name`, argument dictionary `args`
        - Output: a string result. Whether the tool succeeds or returns an error, the result is
        normalized into text so the model can consume that feedback on the next iteration.

        Where it sits in the agent flow:
        It comes after `ask()` reaches the point where the model decides to call a tool. This is
        the step in the control loop that actually turns the model's intent into an action in the
        external world. Because of that, it ties together nearly all of the safety and control
        mechanisms: whether the tool exists, whether its arguments are valid, whether the call is
        a duplicate, whether approval is required, whether the output needs to be clipped, and
        whether memory needs to be updated afterward.
        """
        return self.execute_tool(name, args).content

    def tool_example(self, name):
        return toolkit.tool_example(name)
    
    def tool_list_files(self, args):
        return toolkit.tool_list_files(self.tool_context(), args)

    def tool_read_file(self, args):
        return toolkit.tool_read_file(self.tool_context(), args)

    def tool_search(self, args):
        return toolkit.tool_search(self.tool_context(), args)

    def tool_run_shell(self, args):
        return toolkit.tool_run_shell(self.tool_context(), args)

    def tool_write_file(self, args):
        return toolkit.tool_write_file(self.tool_context(), args)

    def tool_patch_file(self, args):
        return toolkit.tool_patch_file(self.tool_context(), args)
    
    @staticmethod
    def parse_xml_tool(raw):
        pass

    @staticmethod
    def parse_attrs(text):
        pass

    @staticmethod
    def extract_raw(text, tag):
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
        return build_prompt_prefix(workspace=self.workspace, tools=self.tools)

    
    def prompt(self, user_message):
        """
        literal naive concatenation (`self.prefix + "\n\n" + user_message`)
        """
        return self.prefix + "\n\n" + self.history_text() + "\n\n" + user_message

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
        if "<tool>" in raw and ("<final>" not in raw or raw.find("<tool>") < raw.find("<final>")):
            body = LocoAgent.extract(raw, "tool")
            try:
                payload = json.loads(body)
            except Exception:
                return "retry", LocoAgent.retry_notice("model returned malformed tool JSON")
            if not isinstance(payload, dict):
                return "retry", LocoAgent.retry_notice("tool payload must be a JSON object")
            if not str(payload.get("name", "")).strip():
                return "retry", LocoAgent.retry_notice("tool payload is missing a tool name")
            args = payload.get("args", {})
            if args is None:
                payload["args"] = {}
            elif not isinstance(args, dict):
                return "retry", LocoAgent.retry_notice()
            return "tool", payload
        if "<tool" in raw and ("<final>" not in raw or raw.find("<tool") < raw.find("<final>")):
            payload = LocoAgent.parse_xml_tool(raw)
            if payload is not None:
                return "tool", payload
            return "retry", LocoAgent.retry_notice()
        if "<final>" in raw:
            final = LocoAgent.extract(raw, "final").strip()
            if final:
                return "final", final
            return "retry", LocoAgent.retry_notice("model returned an empty <final> answer")
        raw = raw.strip()
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
    



    
