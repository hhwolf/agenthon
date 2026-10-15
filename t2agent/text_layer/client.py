"""House model client (docs/TEXT_LAYER.md §3): OpenAI client, budget, deadline, offline mode, cache.

* ``budget.spend()`` is called immediately before every request, including retries and repairs.
* Offline (``QFBENCH_NETWORK=none`` or no ``MODEL_ENDPOINT``) makes zero network attempts.
* ``max_retries=0`` on the SDK so that no hidden retry burns a House slot.
* Responses can be cached on disk (dev only, ``TEXT_LAYER_CACHE_DIR``); a cache hit sends nothing
  and therefore spends nothing.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from ..contracts import CallBudget
from . import constants as C

try:  # the SDK is a runtime dependency; a missing install is a failure, not "offline"
    import openai  # type: ignore
except Exception:  # pragma: no cover - exercised only in broken environments
    openai = None  # type: ignore

_CONTEXT_OVERFLOW_RE = re.compile(
    r"context[_ ]length|maximum context|max(imum)?[_ ]?(input|prompt)?[_ ]?tokens|too many tokens|"
    r"prompt is too long|input (is )?too long|exceeds? the (model'?s )?(maximum|context)|token limit", re.I)
_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class TextLayerError(Exception):
    """Base class; every subclass maps to a neutral signal."""


class OfflineError(TextLayerError):
    pass


class BudgetExhausted(TextLayerError):
    pass


class TimeExhausted(TextLayerError):
    pass


class CallFailed(TextLayerError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class ContextOverflow(CallFailed):
    pass


class Deadline:
    def __init__(self, seconds: float, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self.start = clock()
        self.end = self.start + float(seconds)

    def remaining(self) -> float:
        return self.end - self._clock()

    def elapsed(self) -> float:
        return self._clock() - self.start


def offline_reason(env: Mapping[str, str]) -> str | None:
    """Why no network attempt may be made, or None when the House route is usable."""
    if str(env.get(C.ENV_NETWORK, "")).strip().lower() == "none":
        return f"{C.ENV_NETWORK}=none"
    for var in (C.ENV_ENDPOINT, C.ENV_TOKEN, C.ENV_MODEL):
        if not str(env.get(var, "")).strip():
            return f"{var} unset"
    return None


@dataclass
class ChatResult:
    text: str
    finish_reason: str | None
    usage: dict
    cached: bool
    attempts: int
    purpose: str
    elapsed_s: float
    thinking: bool


_KEY_FIELDS = ("model", "messages", "temperature", "top_p", "seed", "max_tokens", "extra_body")


def request_key(params: Mapping[str, Any]) -> str:
    """sha256 of the request as sent (model, messages, sampling params, chat_template_kwargs).

    The same key is reproducible from the HTTP body (see ``request_key_from_body``), which lets a
    mock House replay cached development responses.
    """
    blob = json.dumps({k: params.get(k) for k in _KEY_FIELDS}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def request_key_from_body(body: Mapping[str, Any]) -> str:
    params = {k: body.get(k) for k in _KEY_FIELDS if k != "extra_body"}
    extra = body.get("extra_body")
    if extra is None and "chat_template_kwargs" in body:
        extra = {"chat_template_kwargs": body["chat_template_kwargs"]}
    params["extra_body"] = extra
    return request_key(params)


@dataclass
class ResponseCache:
    """Flat disk cache: ``<dir>/<request_key>.json`` holding the reply plus unit/purpose metadata."""

    directory: Path
    hits: int = 0
    writes: int = 0

    def path(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def get(self, key: str) -> dict | None:
        p = self.path(key)
        if not p.is_file():
            return None
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return None
        self.hits += 1
        return payload

    def put(self, key: str, payload: dict) -> None:
        p = self.path(key)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(p)
            self.writes += 1
        except OSError:
            pass


def cache_from_env(env: Mapping[str, str]) -> ResponseCache | None:
    value = str(env.get(C.ENV_CACHE_DIR, "")).strip()
    return ResponseCache(Path(value)) if value else None


def replay_only_from_env(env: Mapping[str, str]) -> bool:
    return str(env.get(C.ENV_REPLAY_ONLY, "")).strip().lower() in {"1", "true", "yes", "on"}


def _call_with_wall_timeout(fn: Callable[[], Any], timeout: float) -> Any:
    """Backstop so a stalled socket cannot exceed the unit's time budget."""
    box: "queue.Queue[tuple[str, Any]]" = queue.Queue(maxsize=1)

    def runner() -> None:
        try:
            box.put(("ok", fn()))
        except BaseException as exc:  # noqa: BLE001 - re-raised below
            box.put(("err", exc))

    threading.Thread(target=runner, name="text-layer-http", daemon=True).start()
    try:
        kind, value = box.get(timeout=timeout)
    except queue.Empty:
        raise TimeoutError(f"wall-clock timeout after {timeout:.0f}s")
    if kind == "err":
        raise value
    return value


def _content_text(message: Any) -> str:
    content = getattr(message, "content", None) if not isinstance(message, dict) else message.get("content")
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            text = part.get("text") if isinstance(part, dict) else getattr(part, "text", None)
            if text:
                parts.append(str(text))
        return "".join(parts)
    return str(content)


class HouseClient:
    """Budgeted, deadline-aware chat client. One instance per unit."""

    def __init__(self, budget: CallBudget, deadline: Deadline, *, env: Mapping[str, str] | None = None,
                 cache: ResponseCache | None = None, client: Any = None, unit_id: str = "",
                 sleep: Callable[[float], None] = time.sleep, replay_only: bool = False):
        self.env = os.environ if env is None else env
        self.budget = budget
        self.deadline = deadline
        self.cache = cache
        self.replay_only = bool(replay_only)
        self.unit_id = unit_id
        self.sleep = sleep
        self.offline = offline_reason(self.env)
        self.model = str(self.env.get(C.ENV_MODEL, "")).strip()
        self.calls: list[dict] = []
        self.network_attempts = 0
        self._lock = threading.Lock()
        self._client = client

    # -- plumbing -----------------------------------------------------------
    def _sdk(self) -> Any:
        if self._client is not None:
            return self._client
        if openai is None:
            raise CallFailed("openai SDK is not installed")
        with self._lock:
            if self._client is None:
                self._client = openai.OpenAI(
                    base_url=str(self.env[C.ENV_ENDPOINT]).rstrip("/") + "/v1",
                    api_key=str(self.env[C.ENV_TOKEN]),
                    max_retries=0,
                    timeout=C.REQUEST_TIMEOUT_S,
                )
        return self._client

    def _spend(self) -> bool:
        with self._lock:
            return self.budget.spend()

    def _timeout(self, requested: float | None) -> float:
        remaining = self.deadline.remaining() - C.SAFETY_MARGIN_S
        t = min(requested or C.REQUEST_TIMEOUT_S, remaining)
        if t < C.MIN_REQUEST_TIMEOUT_S:
            raise TimeExhausted(f"{remaining:.0f}s left; not starting another request")
        return t

    def _record(self, **entry: Any) -> None:
        with self._lock:
            self.calls.append(entry)

    # -- the one way to talk to the model ----------------------------------------
    def chat(self, messages: list[dict], *, max_tokens: int, thinking: bool, purpose: str,
             timeout: float | None = None, seed: int | None = None) -> ChatResult:
        if self.offline:
            raise OfflineError(self.offline)
        params: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": C.TEMPERATURE,
            "top_p": C.TOP_P,
            "seed": int(C.SEED if seed is None else seed),
            "max_tokens": int(max(1, min(max_tokens, C.MAX_OUTPUT_TOKENS))),
            "extra_body": {"chat_template_kwargs": {"enable_thinking": bool(thinking)}},
        }
        key = request_key(params)
        if self.cache is not None:
            hit = self.cache.get(key)
            if hit is not None:
                self._record(purpose=purpose, cached=True, finish_reason=hit.get("finish_reason"),
                             usage=hit.get("usage", {}), attempts=0, thinking=thinking, status=200, key=key)
                return ChatResult(hit.get("text", ""), hit.get("finish_reason"), hit.get("usage", {}),
                                  True, 0, purpose, 0.0, thinking)
        if self.replay_only:
            self._record(purpose=purpose, cached=False, status=None, attempts=0, thinking=thinking,
                         error="replay-only mode: cache miss", key=key)
            raise CallFailed(f"replay-only mode: no cached response for {purpose} ({key[:12]})")
        attempts = 0
        retries = C.MAX_RETRIES_PER_CALL
        last_error = "request failed"
        t0 = time.monotonic()
        while True:
            t = self._timeout(timeout)
            if not self._spend():
                raise BudgetExhausted(f"request budget exhausted ({self.budget.used}/{self.budget.limit})")
            attempts += 1
            with self._lock:
                self.network_attempts += 1
            sdk = self._sdk()
            status: int | None = None
            retryable = False
            try:
                resp = _call_with_wall_timeout(
                    lambda: sdk.with_options(timeout=t, max_retries=0).chat.completions.create(**params), t + 5.0)
            except TextLayerError:
                raise
            except Exception as exc:  # noqa: BLE001 - classified below
                if openai is not None and isinstance(exc, openai.APIStatusError):
                    status = int(getattr(exc, "status_code", 0) or 0)
                    message = str(getattr(exc, "message", None) or exc)[:300]
                    if status in (401, 403):
                        self._record(purpose=purpose, cached=False, status=status, attempts=attempts, error=message, thinking=thinking)
                        raise CallFailed(f"auth failure HTTP {status}: {message}", status) from exc
                    if status == 400 and _CONTEXT_OVERFLOW_RE.search(message):
                        self._record(purpose=purpose, cached=False, status=status, attempts=attempts, error=message, thinking=thinking)
                        raise ContextOverflow(f"HTTP 400: {message}", status) from exc
                    retryable = status in _RETRYABLE_STATUS
                    last_error = f"HTTP {status}: {message}"
                elif openai is not None and isinstance(exc, openai.APIConnectionError):
                    retryable = True
                    last_error = f"{type(exc).__name__}: {str(exc)[:200]}"
                elif isinstance(exc, TimeoutError):
                    retryable = True
                    last_error = str(exc)
                else:
                    last_error = f"{type(exc).__name__}: {str(exc)[:200]}"
                if not retryable or retries <= 0:
                    self._record(purpose=purpose, cached=False, status=status, attempts=attempts, error=last_error, thinking=thinking)
                    raise CallFailed(last_error, status) from exc
                retries -= 1
                if self.deadline.remaining() - C.SAFETY_MARGIN_S > 2.0:
                    self.sleep(1.0)
                continue
            text, finish, usage = self._unpack(resp)
            self._record(purpose=purpose, cached=False, status=200, attempts=attempts, finish_reason=finish,
                         usage=usage, thinking=thinking, elapsed_s=round(time.monotonic() - t0, 2),
                         prompt_tokens_est=sum(len(m.get("content") or "") for m in messages) // C.CHARS_PER_TOKEN)
            if self.cache is not None:
                self.cache.put(key, {"text": text, "finish_reason": finish, "usage": usage, "model": self.model,
                                     "purpose": purpose, "unit_id": self.unit_id, "thinking": bool(thinking),
                                     "created": time.time()})
            return ChatResult(text, finish, usage, False, attempts, purpose, time.monotonic() - t0, thinking)

    @staticmethod
    def _unpack(resp: Any) -> tuple[str, str | None, dict]:
        choices = getattr(resp, "choices", None)
        if choices is None and isinstance(resp, dict):
            choices = resp.get("choices")
        if not choices:
            raise CallFailed("response has no choices")
        choice = choices[0]
        message = getattr(choice, "message", None) if not isinstance(choice, dict) else choice.get("message")
        text = _content_text(message) if message is not None else ""
        finish = getattr(choice, "finish_reason", None) if not isinstance(choice, dict) else choice.get("finish_reason")
        usage = getattr(resp, "usage", None) if not isinstance(resp, dict) else resp.get("usage")
        if usage is not None and not isinstance(usage, dict):
            try:
                usage = usage.model_dump(exclude_none=True)
            except Exception:  # noqa: BLE001
                usage = {}
        return text, finish, dict(usage or {})
