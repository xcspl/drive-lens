"""Descriptions: one vision-model call per image, through image-classify's
prompt and reply parsing (title, description, details, category, tags,
text in the image ...). The HTTP call is our own so that every call's token
use is kept: subscriptions have limits even without a per-token price.

Two wire formats, chosen by DRIVE_LENS_LLM_FORMAT:
  openai     POST {base}/chat/completions  (OpenAI, MiniMax, OpenRouter, vLLM,
             Ollama, LM Studio, most proxies)
  anthropic  POST {base}/messages          (Anthropic, and providers with an
             Anthropic-compatible endpoint)
Usage is normalized to the OpenAI shape before it is logged.

Thinking models (MiniMax M3.x defaults to maximum effort) get the effort
from DRIVE_LENS_LLM_EFFORT when it is set, and max_tokens leaves room for
the thinking."""

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


def _instructions() -> str:
    """image-classify's prompt without its per-file part: identical on every
    call, so it can lead the request and be served from the provider's cache."""
    marker = "File context (use it as a hint, trust the pixels):\n\n\n"
    text = ic.image_prompt(CATEGORIES, {})
    assert marker in text, "image-classify's prompt changed: update describe._instructions"
    return text.replace(marker, "The file's name and folder follow the image: use them as hints, trust the pixels.\n\n")


INSTRUCTIONS = _instructions()


class DescribeError(Exception):
    def __init__(self, message: str, usage: list[dict] | None = None, status: int = 0):
        super().__init__(message)
        self.usage = usage or []
        self.status = status

    @property
    def is_quota(self) -> bool:
        """A rate or usage limit (HTTP 429, or MiniMax's in-body codes 1002
        rate limit / 1039 token limit / 2056 usage limit): wait, don't fail.
        (Anthropic's 529 "overloaded" is a 5xx and is retried in _call.)"""
        text = str(self).lower()
        return self.status == 429 or any(c in text for c in ("error 1002", "error 1039", "error 2056")) or "limit" in text and "exceed" in text


# Waits when a plan's limit is reached (MiniMax's plans meter a 5-hour rolling window).
QUOTA_WAITS = [300, 600, 900, 1800, 1800, 1800, 3600, 3600, 3600, 3600]


ANTHROPIC_VERSION = "2023-06-01"


def _anthropic_usage(u: dict) -> dict:
    """Anthropic usage → the OpenAI shape store.log_usage reads. Anthropic's
    input_tokens leave out the cached part, so it is added back."""
    cached = u.get("cache_read_input_tokens") or 0
    prompt = (u.get("input_tokens") or 0) + cached + (u.get("cache_creation_input_tokens") or 0)
    return {"prompt_tokens": prompt, "completion_tokens": u.get("output_tokens") or 0,
            "prompt_tokens_details": {"cached_tokens": cached}}


@dataclass
class Describer:
    base_url: str
    api_key: str
    model: str
    effort: str = ""
    format: str = "openai"  # openai | anthropic
    max_tokens: int = 8000
    timeout: float = 180.0
    retries: int = 4
    extra: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        return f"{self.model}@{self.effort}" if self.effort else self.model

    def _request(self, system: str, jpeg_b64: str, text: str) -> tuple[str, dict, dict]:
        """(url, headers, body) for one call in this describer's format."""
        base = self.base_url.rstrip("/")
        if self.format == "anthropic":
            body = {
                "model": self.model, "max_tokens": self.max_tokens, "temperature": 0.2,
                # The instructions are the same on every call: marked for the provider's prompt cache.
                "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                "messages": [{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": jpeg_b64}},
                    {"type": "text", "text": text},
                ]}],
                **self.extra,
            }
            if self.effort:
                body["output_config"] = {"effort": self.effort}
            headers = {"Content-Type": "application/json", "anthropic-version": ANTHROPIC_VERSION,
                       **({"x-api-key": self.api_key} if self.api_key else {})}
            return base + "/messages", headers, body
        body = {
            "model": self.model, "max_tokens": self.max_tokens, "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{jpeg_b64}"}},
                    {"type": "text", "text": text},
                ]},
            ],
            **self.extra,
        }
        if self.effort:
            body["reasoning_effort"] = self.effort
        headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {})}
        return base + "/chat/completions", headers, body

    def _parse(self, d: dict) -> tuple[str, str, dict]:
        """A reply → (text, finish reason, usage in the OpenAI shape)."""
        if self.format == "anthropic":
            text = "".join(b.get("text", "") for b in d.get("content") or [] if b.get("type") == "text")
            return text, d.get("stop_reason") or "", _anthropic_usage(d.get("usage") or {})
        choice = (d.get("choices") or [{}])[0]
        text = (choice.get("message") or {}).get("content") or ""
        if isinstance(text, list):
            text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
        base = d.get("base_resp") or {}
        if not text and base.get("status_code"):  # MiniMax reports some failures inside a 200
            raise DescribeError(f"provider error {base.get('status_code')}: {base.get('status_msg')}", [d.get("usage") or {}], 500)
        return text, choice.get("finish_reason") or "", d.get("usage") or {}

    def _call(self, request: tuple[str, dict, dict]) -> tuple[str, str, dict]:
        """One completion → (text, finish_reason, usage). Retries 408/409/429/5xx and network errors."""
        url, headers, body = request
        data = json.dumps(body).encode()
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            wait = None
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    d = json.loads(r.read())
                return self._parse(d)
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

    def _call_waiting(self, request: tuple[str, dict, dict]) -> tuple[str, str, dict]:
        """`_call`, but a rate/usage limit pauses (up to ~6 h in total) instead of failing."""
        for wait in QUOTA_WAITS + [None]:
            try:
                return self._call(request)
            except DescribeError as e:
                if not e.is_quota or wait is None:
                    raise
                import sys
                print(f"  … model limit reached ({str(e)[:120]}); waiting {wait // 60} min", file=sys.stderr, flush=True)
                time.sleep(wait)
        raise AssertionError("unreachable")

    def describe(self, jpeg: bytes, context: dict) -> tuple[dict, list[dict]]:
        """Analyse one image. Returns (clean analysis, usage of every call made).
        A reply without a JSON object (often cut off by thinking) is retried once."""
        b64 = base64.b64encode(jpeg).decode()
        hints = "\n".join(f"- {k}: {v}" for k, v in context.items() if v)
        # Fixed instructions first (the same bytes on every call, so the
        # provider can cache them), then the image, then this file's details.
        request = self._request(INSTRUCTIONS, b64, f"File context (a hint; trust the pixels):\n{hints}" if hints else "Catalog this image.")
        usages: list[dict] = []
        reason = ""
        for _ in range(2):
            text, finish, usage = self._call_waiting(request)
            usages.append(usage)
            try:
                return ic.clean_analysis(ic.extract_json(text), CATEGORIES), usages
            except ValueError:
                reason = f"no JSON in the reply (finish_reason={finish or '?'}, {len(text)} chars)"
        raise DescribeError(reason, usages)
