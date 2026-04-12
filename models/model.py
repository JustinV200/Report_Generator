"""LLM wrapper that provides JSON and raw-text calling modes via litellm."""

import json
import re
import os
from litellm import completion

class Model:
    """Thin wrapper around litellm.completion with JSON-mode and raw-text helpers."""

    def __init__(self, model_name="gpt-3.5-turbo"):
        self.model_name = model_name
        self._is_ollama = model_name.startswith(("ollama/", "ollama_chat/"))

    def _extract_json(self, text):
        """Extract JSON from LLM output that may contain extra text around it."""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        match = re.search(r'```(?:json)?\s*\n(\{.*?\})\s*\n```', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
        match = re.search(r'(\{.*\})', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
        raise ValueError(f"Could not extract JSON from model output: {text[:200]}...")

    def call(self, prompt):
        """Send *prompt* to the LLM and return the response parsed as JSON."""
        kwargs = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
        }
        if self._is_ollama:
            kwargs["format"] = "json"           # Ollama native JSON mode
        else:
            kwargs["response_format"] = {"type": "json_object"}  # OpenAI JSON mode
        response = completion(**kwargs)
        raw = response.choices[0].message.content
        return self._extract_json(raw)
    
    def call_raw(self, prompt):
        """Send *prompt* to the LLM and return the raw text response."""
        response = completion(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content