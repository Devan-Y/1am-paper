"""Minimal OpenRouter client that asks for JSON and repairs it when the model slips."""
from __future__ import annotations

import json
import re
import time

from . import util

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class BudgetExceeded(Exception):
    pass


class ModelError(Exception):
    pass


def extract_json(text: str):
    """Pull the first complete JSON object out of a reply (handles ```json fences and chatter)."""
    if not text:
        raise ValueError("empty reply")
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidates = [fence.group(1)] if fence else []
    start = text.find("{")
    if start >= 0:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[start:i + 1])
                    break
    last_err = None
    for c in candidates:
        for attempt in (c, re.sub(r",\s*([}\]])", r"\1", c)):  # tolerate trailing commas
            try:
                return json.loads(attempt)
            except json.JSONDecodeError as e:
                last_err = e
    raise ValueError(f"no valid JSON object found ({last_err})")


class OpenRouter:
    def __init__(self, api_key: str, model: str, fallback_models: list[str] | None = None,
                 max_requests: int = 30, timeout: float = 600, max_tokens: int = 16000,
                 temperature: float = 0.4, log=print):
        self.api_key = api_key
        self.model = model
        self.fallbacks = [m for m in (fallback_models or []) if m != model]
        self.max_requests = max_requests
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.requests = 0
        self.models_used: set[str] = set()
        self.log = log

    def _call(self, messages: list[dict], max_tokens: int) -> str:
        if self.requests >= self.max_requests:
            raise BudgetExceeded(f"stopped after {self.requests} model requests (limit {self.max_requests})")
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": max_tokens,
        }
        if self.fallbacks:
            payload["models"] = [self.model] + self.fallbacks  # OpenRouter tries these in order
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://github.com/one-am-paper",
            "X-Title": "The 1 A.M. Paper",
        }
        for attempt in range(4):
            self.requests += 1
            t0 = time.time()
            try:
                data = util.post_json(OPENROUTER_URL, payload, headers=headers,
                                      timeout=self.timeout, retries=2, backoff=20)
            except util.HttpError as e:
                if e.status in (401, 402, 403):
                    raise ModelError(f"OpenRouter refused the request ({e.status}). Check the API key, "
                                     f"credit balance and privacy settings for free models. {e.body[:200]}")
                raise
            if data.get("error"):
                err = data["error"]
                self.log(f"  ! model error: {err}")
                if attempt < 3:
                    time.sleep(30 * (attempt + 1))
                    if self.requests >= self.max_requests:
                        raise BudgetExceeded("model request budget used up while retrying")
                    continue
                raise ModelError(str(err))
            choice = (data.get("choices") or [{}])[0]
            content = ((choice.get("message") or {}).get("content")) or ""
            self.models_used.add(data.get("model", self.model))
            self.log(f"  · model reply in {time.time() - t0:.0f}s "
                     f"({(data.get('usage') or {}).get('completion_tokens', '?')} tokens, "
                     f"finish={choice.get('finish_reason')})")
            if not content.strip() and choice.get("finish_reason") == "length" and attempt < 3:
                max_tokens = int(max_tokens * 1.5)
                payload["max_tokens"] = max_tokens
                self.log("  · reply was cut off while reasoning; retrying with more room")
                continue
            return content
        raise ModelError("no usable reply after retries")

    def ask_json(self, messages: list[dict], validate=None, max_tokens: int | None = None):
        """Send messages, parse a JSON object from the reply, optionally validate it.
        On bad JSON or a failed check, tell the model what was wrong (up to twice)."""
        msgs = list(messages)
        problem = None
        for attempt in range(3):
            reply = self._call(msgs, max_tokens or self.max_tokens)
            try:
                obj = extract_json(reply)
                if validate:
                    problems = validate(obj)
                    if problems:
                        raise ValueError("; ".join(problems))
                return obj, msgs + [{"role": "assistant", "content": reply}]
            except ValueError as e:
                problem = str(e)
                self.log(f"  ! reply rejected: {problem[:300]}")
                msgs = msgs + [
                    {"role": "assistant", "content": reply[-6000:]},
                    {"role": "user", "content": (
                        f"That reply could not be used: {problem}\n"
                        "Fix it and reply with ONLY the corrected JSON object, nothing else.")},
                ]
        raise ModelError(f"model never produced usable JSON: {problem}")
