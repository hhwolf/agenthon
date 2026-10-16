"""OpenAI-compatible mock of the House route for tests, offline dry runs and the mock Final grader.

* ``POST /v1/chat/completions`` and ``GET /v1/models``; a missing/invalid bearer answers 401 like the
  real route, ``/chat/completions`` without ``/v1`` answers 403, ``n > 1`` is refused with 400.
* House accounting: every admitted request counts against a per-token allowance (default 25, incl.
  upstream failures); beyond it the route answers 429. ``max_tokens`` above 4000 is clamped and recorded.
* Scripted steps (``ok``, ``error``, ``delay``, ``drop``) are served first, then the scenario.
* ``auto`` reads the prompt and answers extraction requests with evidence quoting the documents it was
  sent and label requests with a plausible label JSON (one dissenting run in three when the seed
  varies), so quote verification, chunking, voting and clamping run end to end without a network.
* ``replay_dir`` serves responses recorded by the text layer's dev cache, keyed by the request body
  (``t2agent.text_layer.client.request_key_from_body``); a miss answers 404.

Run standalone: ``python tests/mock_house.py --port 8008 --scenario auto [--replay-dir .eval/llm_cache]``.
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import sys
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional, Sequence

SCENARIOS = ("auto", "neutral", "extreme", "invalid_json", "truncated", "server_error", "timeout",
             "auth", "forbidden", "flaky", "think", "empty")
HOUSE_REQUEST_ALLOWANCE = 25
HOUSE_MAX_OUTPUT_TOKENS = 4000

_DOC_RE = re.compile(r'<<<DOC id="([^"]*)" timestamp="([^"]*)" type="([^"]*)"[^>]*>>>\n(.*?)\n<<<END DOC>>>', re.S)
_ASSETS_RE = re.compile(r"^- assets: ([^;]+); value_unit", re.M)
_EVIDENCE_RE = re.compile(r"^\[(\d+)\] \(([EI])\)", re.M)


@dataclass
class Step:
    kind: str = "ok"
    content: Any = None
    status: int = 500
    message: str = "internal error"
    delay_s: float = 0.0
    finish_reason: str = "stop"
    then: Optional["Step"] = None


def ok(content: Any, finish_reason: str = "stop") -> Step:
    return Step("ok", content=content, finish_reason=finish_reason)


def error(status: int, message: str = "internal error") -> Step:
    return Step("status", status=status, message=message)


def delay(seconds: float, then: Optional[Step] = None) -> Step:
    return Step("delay", delay_s=seconds, then=then)


def drop() -> Step:
    return Step("drop")


def _prompt(body: Any) -> str:
    if isinstance(body, dict):
        return "\n".join(str(m.get("content") or "") for m in body.get("messages", []) if isinstance(m, dict))
    return ""


def _first_quote(text: str, min_len: int = 40, max_len: int = 160) -> str | None:
    for line in text.split("\n"):
        line = line.strip()
        if len(line) >= min_len:
            return line[:max_len]
    return None


def _assets(prompt: str) -> list[str]:
    m = _ASSETS_RE.search(prompt)
    return [a.strip() for a in m.group(1).split(",") if a.strip()] if m else ["X"]


def canned_extraction(prompt: str, scenario: str = "auto") -> dict:
    docs = _DOC_RE.findall(prompt)
    assets = _assets(prompt)
    evidence = []
    for i, (doc_id, ts, doc_type, text) in enumerate(docs):
        quote = _first_quote(text)
        kind = {"central_bank_decision": "decision", "fomc_statement": "guidance", "macro_release": "data"}.get(doc_type, "tone")
        if quote:
            evidence.append({"doc_id": doc_id, "timestamp": ts, "claim": f"{doc_id} states: {quote[:70]}", "quote": quote,
                             "assets": assets, "direction": 1 if i % 2 == 0 else -1, "established": True, "kind": kind})
        evidence.append({"doc_id": doc_id, "timestamp": ts, "claim": f"The tone of {doc_id} leans {'hawkish' if i % 2 == 0 else 'dovish'}.",
                         "quote": "", "assets": assets, "direction": 1 if i % 2 == 0 else -1, "established": False, "kind": "tone"})
    if scenario == "extreme":
        first = docs[0][0] if docs else "doc"
        evidence = [
            {"doc_id": "ghost_document_2099", "claim": "An uncited claim.", "quote": "", "assets": assets, "direction": 1, "established": True, "kind": "decision"},
            {"doc_id": first, "timestamp": "", "claim": "Established without a real quote.", "quote": "this sentence appears nowhere", "assets": assets, "direction": -1, "established": True, "kind": "decision"},
            {"doc_id": first, "timestamp": "", "claim": "Pure inference from tone.", "quote": "", "assets": assets, "direction": -1, "established": False, "kind": "tone"},
        ]
    return {"evidence": evidence, "scheduled_events": [], "disagreements": [] if len(docs) < 2 else
            [f"{docs[0][0]} leans one way while {docs[1][0]} leans the other."]}


def canned_labels(prompt: str, scenario: str = "auto", seed: int | None = None) -> dict:
    assets = _assets(prompt)
    marks = _EVIDENCE_RE.findall(prompt)
    n = len(marks)
    established_ids = [int(i) for i, flag in marks if flag == "E"]
    cite = [i for i in (established_ids[:2] or [1, 2]) if 1 <= i <= n]
    binary = bool(re.search(r"\(inside horizon\) (?:referendum|election|vote):", prompt)) or "names a two-outcome event" in prompt
    if scenario == "neutral":
        return {"regime": "calm", "event_in_horizon": "none", "disagreement": False,
                "assets": {a: {"direction": "none", "direction_established": False, "evidence": []} for a in assets},
                "branches": [], "summary": "Nothing in the documents argues for a change."}
    if scenario == "extreme":
        return {"regime": "apocalyptic", "event_in_horizon": "scheduled_binary", "disagreement": "maybe",
                "assets": {a: {"direction": "strong_up", "direction_established": True, "evidence": []} for a in assets},
                "branches": [{"label": "a", "prob": 0.5, "signs": {a: 1 for a in assets}},
                             {"label": "b", "prob": 0.3, "signs": {a: -1 for a in assets}},
                             {"label": "c", "prob": 0.2, "signs": {a: 0 for a in assets}}],
                "summary": "Out-of-schema labels."}
    dissent = seed is not None and seed % 3 == 2
    regime = "calm" if dissent else "elevated"
    first = assets[0]
    per_asset = {}
    for a in assets:
        direction = "none" if (dissent and a == first) else "up"
        per_asset[a] = {"direction": direction, "direction_established": bool(cite) and direction != "none" and bool(established_ids),
                        "evidence": cite if direction != "none" else []}
    out = {"regime": regime, "event_in_horizon": "scheduled_binary" if binary else "none", "disagreement": False,
           "assets": per_asset, "branches": [], "summary": "Decisions lean hawkish; the mixture is split rather than averaged."}
    if binary:
        out["branches"] = [{"label": "outcome A", "prob": 0.55, "signs": {a: 1 for a in assets}},
                           {"label": "outcome B", "prob": 0.45, "signs": {a: -1 for a in assets}}]
    return out


def scenario_step(scenario: str, body: Any, counter: int) -> Step:
    prompt = _prompt(body)
    is_extraction = "DOCUMENTS (part" in prompt
    if scenario == "server_error":
        return error(500, "mock: internal server error")
    if scenario == "auth":
        return error(401, "mock: invalid token")
    if scenario == "forbidden":
        return error(403, "mock: forbidden")
    if scenario == "timeout":
        return delay(120.0, ok("too late"))
    if scenario == "invalid_json":
        return ok("I think the outlook is mildly hawkish but I cannot write JSON today.")
    if scenario == "empty":
        return ok("", finish_reason="length")
    if scenario == "flaky" and counter % 2 == 1:
        return error(503, "mock: temporarily unavailable")
    seed = body.get("seed") if isinstance(body, dict) else None
    obj = canned_extraction(prompt, scenario) if is_extraction else canned_labels(prompt, scenario, seed)
    text = json.dumps(obj, indent=1)
    if scenario == "truncated":
        return ok(text[: int(len(text) * 0.85)], finish_reason="length")
    if scenario == "think":
        return ok("<think>Weighing the documents...</think>\n```json\n" + text + "\n```")
    return ok(text)


class MockHouse:
    def __init__(self, steps: Optional[Sequence[Step]] = None, *, scenario: str = "auto", host: str = "127.0.0.1",
                 port: int = 0, model: str = "house-mock", token: str = "mock-token", require_token: bool = True,
                 verbose: bool = False, allowance: int = HOUSE_REQUEST_ALLOWANCE, replay_dir: Optional[Path] = None):
        if scenario not in SCENARIOS:
            raise ValueError(f"unknown scenario {scenario!r}")
        self.scenario = scenario
        self.host, self._port, self.model, self.token = host, port, model, token
        self.require_token, self.verbose = require_token, verbose
        self.allowance = int(allowance)
        self.replay_dir = Path(replay_dir) if replay_dir else None
        self.steps: list[Step] = list(steps or [])
        self.requests: list[dict] = []
        self.admitted: dict[str, int] = {}
        self.calls = 0
        self._lock = threading.Lock()
        self._httpd = None
        self._thread = None

    def _replay(self, body: Any) -> Optional[Step]:
        if self.replay_dir is None:
            return None
        try:
            from t2agent.text_layer.client import request_key_from_body
        except Exception:  # pragma: no cover
            return error(500, "replay unavailable: t2agent not importable")
        key = request_key_from_body(body if isinstance(body, dict) else {})
        path = self.replay_dir / f"{key}.json"
        if not path.is_file():
            return error(404, f"replay cache miss for request {key[:12]}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            return error(500, f"replay cache unreadable: {exc}")
        return ok(payload.get("text", ""), payload.get("finish_reason") or "stop")

    def start(self) -> "MockHouse":
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt, *args):  # noqa: N802
                if server.verbose:
                    sys.stderr.write("[mock-house] " + fmt % args + "\n")

            def do_GET(self):  # noqa: N802
                if self.path.rstrip("/") == "/v1/models":
                    self._send(200, {"object": "list", "data": [{"id": server.model, "object": "model"}]})
                else:
                    self._send(404, {"error": {"message": "not found"}})

            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    body = json.loads(raw.decode("utf-8")) if raw else {}
                except ValueError:
                    body = {"_raw": raw.decode("utf-8", "replace")}
                auth = self.headers.get("Authorization") or ""
                record = {"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body,
                          "t": time.monotonic(), "admitted": False, "max_tokens_effective": None}
                with server._lock:
                    server.requests.append(record)
                    server.calls += 1
                    counter = server.calls
                if self.path.rstrip("/") == "/chat/completions":
                    self._send(403, {"error": {"message": "route requires /v1 prefix"}})
                    return
                if self.path.rstrip("/") != "/v1/chat/completions":
                    self._send(404, {"error": {"message": f"unknown path {self.path}"}})
                    return
                if server.require_token and auth != f"Bearer {server.token}":
                    self._send(401, {"error": {"message": "missing or invalid bearer token"}})
                    return
                if isinstance(body, dict) and int(body.get("n", 1) or 1) > 1:
                    self._send(400, {"error": {"message": "n > 1 is refused"}})
                    return
                with server._lock:
                    used = server.admitted.get(auth, 0)
                    if used >= server.allowance:
                        step = error(429, f"request allowance of {server.allowance} exhausted for this unit token")
                    else:
                        server.admitted[auth] = used + 1
                        record["admitted"] = True
                        if isinstance(body, dict):
                            requested = body.get("max_tokens")
                            record["max_tokens_effective"] = min(int(requested), HOUSE_MAX_OUTPUT_TOKENS) if requested else HOUSE_MAX_OUTPUT_TOKENS
                        step = server.steps.pop(0) if server.steps else None
                if step is None:
                    step = server._replay(body) or scenario_step(server.scenario, body, counter)
                self._serve(step, body, counter)

            def _serve(self, step: Step, body: Any, counter: int):
                if step.kind == "delay":
                    time.sleep(step.delay_s)
                    step = step.then or server._replay(body) or scenario_step(server.scenario, body, counter)
                if step.kind == "drop":
                    try:
                        self.connection.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    self.close_connection = True
                    return
                if step.kind == "status":
                    self._send(step.status, {"error": {"message": step.message, "type": "mock_error", "code": step.status}})
                    return
                content = step.content if isinstance(step.content, str) else json.dumps(step.content)
                p_tok = len(_prompt(body)) // 4
                c_tok = max(1, len(content) // 4)
                self._send(200, {"id": f"chatcmpl-mock-{counter}", "object": "chat.completion", "created": int(time.time()),
                                 "model": body.get("model", server.model) if isinstance(body, dict) else server.model,
                                 "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                                              "finish_reason": step.finish_reason}],
                                 "usage": {"prompt_tokens": p_tok, "completion_tokens": c_tok, "total_tokens": p_tok + c_tok}})

            def _send(self, status: int, payload: dict):
                data = json.dumps(payload).encode("utf-8")
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass

        class Server(ThreadingHTTPServer):
            daemon_threads = True
            allow_reuse_address = True

            def handle_error(self, request, client_address):
                if server.verbose:
                    super().handle_error(request, client_address)

        self._httpd = Server((self.host, self._port), Handler)
        self._port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, kwargs={"poll_interval": 0.05},
                                        name="mock-house", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def __enter__(self) -> "MockHouse":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    @property
    def endpoint(self) -> str:
        return f"http://{self.host}:{self._port}"

    def env(self, network: str = "restricted") -> dict[str, str]:
        return {"MODEL_ENDPOINT": self.endpoint, "MODEL_TOKEN": self.token, "MODEL_NAME": self.model,
                "QFBENCH_NETWORK": network}

    def push(self, *steps: Step) -> None:
        with self._lock:
            self.steps.extend(steps)

    def bodies(self) -> list[dict]:
        return [r["body"] for r in self.requests]

    def reset_accounting(self) -> None:
        with self._lock:
            self.admitted.clear()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Mock House route")
    p.add_argument("--port", type=int, default=8008)
    p.add_argument("--scenario", choices=SCENARIOS, default="auto")
    p.add_argument("--replay-dir", type=Path)
    p.add_argument("--allowance", type=int, default=HOUSE_REQUEST_ALLOWANCE)
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)
    server = MockHouse(scenario=args.scenario, port=args.port, verbose=not args.quiet, allowance=args.allowance,
                       replay_dir=args.replay_dir).start()
    sys.stderr.write(f"mock House serving scenario={args.scenario!r}"
                     f"{' replay=' + str(args.replay_dir) if args.replay_dir else ''} at {server.endpoint}/v1\n"
                     f"export MODEL_ENDPOINT={server.endpoint} MODEL_TOKEN={server.token} MODEL_NAME={server.model} QFBENCH_NETWORK=restricted\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
