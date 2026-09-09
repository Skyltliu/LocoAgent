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

    def _ensure_session_shape(self):
        pass

    def build_prefix(self):
        pass

    def record(self, item):
        pass