import json
import hashlib
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from .session_store import SessionStore
from .prompt_prefix import build_prompt_prefix
from .workspace import IGNORED_PATHS, MAX_HISTORY, WorkspaceContext, clip, now
class LocoAgent:
    def __init__(self, model_client, workspace, session_store, session=None, max_new_tokens=512):
        self.workspace = workspace
        self.max_new_tokens = max_new_tokens
        self.model_client = model_client
        self.session_store = session_store
        self.session = session or {
            "id": datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6],
            "created_at": now(),
            "workspace_root": workspace.repo_root,
            "history": [],
        }
        self.session_path = self.session_store.save(self.session)
        self.prefix_state = self.build_prefix()
        self.prefix = self.prefix_state.text
        self._ensure_session_shape()


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
    



    
