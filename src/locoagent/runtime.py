import json
import hashlib
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

class LocoAgent:
    def __init__(self, model_client, workspace, session_store, session=None):
        self.workspace = workspace
        self.model_client = model_client
        self.session_store = session_store
        self.session = session #or {
        #}


    #phase 1 functions
    def _ensure_session_shape(self):
        pass


    def build_prompt_prefix(workspace, tools, built_at=None):
        """
        identity + rules + workspace.text()
        """
        pass
    
    def build_prefix(self):
        pass

    
    def prompt(user_message):
        """
        iteral naive concatenation (`self.prefix + "\n\n" + user_message`)
        """
        pass

    def ask(self, user_message):
        """
        At this phase write it as a small self-contained loop with no `kind == "tool"` branch (Phase 2), no
        task_state/trace (Phase 3), no AgentLoop extraction (Phase 3), no
        checkpoint/resume branching (Phase 7), no redaction (Phase 8), and no
        durable-memory promotion (Phase 10).
        """
        pass

    def record(self, item):
        pass

    @staticmethod
    def retry_notice(problem=None):
        pass

    @staticmethod
    def parse(raw):
        """
        only needs the `<final>` and empty/plain-text branches
        returning ("final", ...) / ("retry", ...). Skip the `<tool>`/`<tool ...>`
        branches entirely — there's nothing to call one yet.
        
        """

    @staticmethod
    def extract(text, tag):
        pass



    
