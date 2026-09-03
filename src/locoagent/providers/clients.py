import json
import time
from http.client import RemoteDisconnected
import urllib.error
import urllib.request

from openai import OpenAI

class OpenAICompatibleModelClient:
    def __init__(self, model, base_url, api_key, temperature=None, timeout=300):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.temperature = temperature
        self.timeout = timeout
        self.client(
            api_key=api_key,
            base_url=self.base_url,
            timeout=timeout,
        )
    def complete(self, prompt, max_new_tokens=4096):
        kwargs = {
            "model": self.model,
            "input": prompt,
            "max_output_tokens": max_new_tokens,
        }
        if self.temperature:
            kwargs["temperature"] = self.temperature
        response = self.client.responses.create(**kwargs)
        return response.output_txt


