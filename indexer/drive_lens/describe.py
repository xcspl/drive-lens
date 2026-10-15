"""Descriptions: one vision-model call per image, through image-classify's
prompt and reply parsing (title, description, details, category, tags,
text in the image ...). The HTTP call is our own so that every call's token
use is kept — the M Plan is a subscription with limits, so the totals matter.

OpenAI-compatible chat API (MiniMax, OpenRouter, an llmhub proxy ...).
MiniMax M3.x thinks before answering and defaults to maximum effort; we send
`reasoning_effort` (default medium) and leave room for the thinking."""

from __future__ import annotations

import base64
import json
import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from image_classify import model as ic

CATEGORIES = ic.DEFAULT_CATEGORIES


class DescribeError(Exception):
    def __init__(self, message: str, usage: list[dict] | None = None, status: int = 0):
        super().__init__(message)
        self.usage = usage or []
        self.status = status


@dataclass
class Describer:
    base_url: str
    api_key: str
    model: str
    effort: str = "medium"
    max_tokens: int = 8000
    timeout: float = 180.0
    retries: int = 4
    extra: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        return f"{self.model}@{self.effort}" if self.effort else self.model

    def _call(self, messages: list[dict]) -> tuple[str, str, dict]:
        """One completion → (text, finish_reason, usage). Retries 408/409/429/5xx and network errors."""
        body = {"model": self.model, "messages": messages, "max_tokens": self.max_tokens, "temperature": 0.2, **self.extra}
        if self.effort:
            body["reasoning_effort"] = self.effort
        data = json.dumps(body).encode()
        headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {})}
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            req = urllib.request.Request(self.base_url.rstrip("/") + "/chat/completions", data=data, headers=headers, method="POST")
            wait = None
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    d = json.loads(r.read())
                choice = (d.get("choices") or [{}])[0]
                text = (choice.get("message") or {}).get("content") or ""
                if isinstance(text, list):
                    text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
                base = d.get("base_resp") or {}
                if not text and base.get("status_code"):  # MiniMax reports some failures inside a 200
                    raise DescribeError(f"provider error {base.get('status_code')}: {base.get('status_msg')}", [d.get("usage") or {}], 500)
                return text, choice.get("finish_reason") or "", d.get("usage") or {}
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:300]
                last = DescribeError(f"HTTP {e.code}: {detail}", status=e.code)
                if e.code not in (408, 409, 429) and e.code < 500:
                    raise last
                try:
                    wait = min(60.0, float(e.headers.get("Retry-After") or ""))
                except ValueError:
                    wait = None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                last = DescribeError(f"network: {e}")
            except DescribeError as e:
                last = e
            if attempt < self.retries:
                time.sleep(wait if wait is not None else min(30.0, 2 * 2 ** attempt) * (0.75 + random.random() / 2))
        raise last  # type: ignore[misc]

    def describe(self, jpeg: bytes, context: dict) -> tuple[dict, list[dict]]:
        """Analyse one image. Returns (clean analysis, usage of every call made).
        A reply without a JSON object (often cut off by thinking) is retried once."""
        b64 = base64.b64encode(jpeg).decode()
        messages = [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            {"type": "text", "text": ic.image_prompt(CATEGORIES, context)},
        ]}]
        usages: list[dict] = []
        reason = ""
        for _ in range(2):
            text, finish, usage = self._call(messages)
            usages.append(usage)
            try:
                return ic.clean_analysis(ic.extract_json(text), CATEGORIES), usages
            except ValueError:
                reason = f"no JSON in the reply (finish_reason={finish or '?'}, {len(text)} chars)"
        raise DescribeError(reason, usages)
