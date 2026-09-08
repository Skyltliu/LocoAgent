import json
import time
from http.client import RemoteDisconnected
import urllib.error
import urllib.request

from openai import OpenAI

class FakeModelClient:
    def __int__(self, outputs):
        self.outputs = list(outputs)
        self.prompts = []
        self.supports_prompt_cache = False
        self.last_completion_metadata = {}

        def complete(self, prompt, max_new_tokens, **kwargs):
            self.prompts.append(prompt)
            if not getattr(self, "last_completion_metadata", None):
                self.last_completion_metadata = {}
            if not self.outputs:
                raise RuntimeError("fake model ran out of output")
            return self.outputs.pop(0)

class OpenAICompatibleModelClient:
    def __init__(self, model, base_url, api_key, temperature=None, timeout=300):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.temperature = temperature
        self.timeout = timeout
        self.client = OpenAI(
            api_key=api_key,
            base_url=self.base_url,
            timeout=self.timeout,
        )
       
    def complete(self, prompt, max_new_tokens=4096):
        kwargs = {
            "model": self.model,
            "input": prompt,
            "max_output_tokens": max_new_tokens,
        }
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        response = self.client.responses.create(**kwargs)
        return response.output_text


