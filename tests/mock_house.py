"""OpenAI-compatible mock of the House route for tests and offline dry runs.

* ``POST /v1/chat/completions`` and ``GET /v1/models``; a missing/invalid bearer answers 401 like the
  real route, ``/chat/completions`` without ``/v1`` answers 403.
* Scripted steps (``ok``, ``error``, ``delay``, ``drop``) are served first, then the scenario.
* The ``auto`` scenario reads the prompt and answers extraction requests with evidence quoting the
  documents it was sent, and synthesis requests with a plausible scenario JSON, so quote
  verification, chunking and clamping run end to end without a network.
* Every request is recorded in ``server.requests`` (path, headers, parsed body) for assertions.

Run standalone: ``python tests/mock_house.py --port 8008 --scenario auto``.
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
from typing import Any, Optional, Sequence

SCENARIOS = ("auto", "neutral", "extreme", "invalid_json", "truncated", "server_error", "timeout",
             "auth", "forbidden", "flaky", "think", "empty")

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


def canned_synthesis(prompt: str, scenario: str = "auto") -> dict:
    assets = _assets(prompt)
    n = len(_EVIDENCE_RE.findall(prompt))
    cite = lambda *xs: [x for x in xs if 1 <= x <= n]  # noqa: E731
    if scenario == "neutral":
        return {"scenarios": [{"label": "base", "weight": 1.0, "drift_sd": {a: 0.0 for a in assets}, "vol_mult": 1.0, "evidence": cite(1)}],
                "tail_mult": 1.0, "narrowing_support": [], "summary": "No actionable text signal."}
    if scenario == "extreme":
        return {"scenarios": [
                    {"label": "crash", "weight": 80, "drift_sd": {a: -4.0 for a in assets}, "vol_mult": 0.5, "evidence": cite(1)},
                    {"label": "moon", "weight": 15, "drift_sd": {a: 3.0 for a in assets}, "vol_mult": 5.0, "evidence": cite(2)},
                    {"label": "tiny-a", "weight": 3, "drift_sd": {a: 0.0 for a in assets}, "vol_mult": 1.0, "evidence": []},
                    {"label": "tiny-b", "weight": 2, "drift_sd": {a: 0.0 for a in assets}, "vol_mult": 1.0, "evidence": []}],
                "tail_mult": 7.0, "narrowing_support": cite(1), "summary": "Everything is extreme."}
    return {"scenarios": [
                {"label": "hawkish", "weight": 0.4, "drift_sd": {a: 0.6 for a in assets}, "vol_mult": 1.2, "evidence": cite(1, 2)},
                {"label": "base", "weight": 0.45, "drift_sd": {a: 0.1 for a in assets}, "vol_mult": 1.0, "evidence": cite(1)},
                {"label": "dovish", "weight": 0.15, "drift_sd": {a: -0.5 for a in assets}, "vol_mult": 1.3, "evidence": cite(2)}],
            "tail_mult": 1.2, "narrowing_support": [],
            "summary": "Decisions in the corpus lean hawkish; the minutes disagree, so the mixture is split rather than averaged."}


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
    obj = canned_extraction(prompt, scenario) if is_extraction else canned_synthesis(prompt, scenario)
    text = json.dumps(obj, indent=1)
    if scenario == "truncated":
        return ok(text[: int(len(text) * 0.85)], finish_reason="length")
    if scenario == "think":
        return ok("<think>Weighing the documents...</think>\n```json\n" + text + "\n```")
    return ok(text)


class MockHouse:
    def __init__(self, steps: Optional[Sequence[Step]] = None, *, scenario: str = "auto", host: str = "127.0.0.1",
                 port: int = 0, model: str = "house-mock", token: str = "mock-token", require_token: bool = True,
                 verbose: bool = False):
        if scenario not in SCENARIOS:
            raise ValueError(f"unknown scenario {scenario!r}")
        self.scenario = scenario
        self.host, self._port, self.model, self.token = host, port, model, token
        self.require_token, self.verbose = require_token, verbose
        self.steps: list[Step] = list(steps or [])
        self.requests: list[dict] = []
        self.calls = 0
        self._lock = threading.Lock()
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

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
                with server._lock:
                    server.requests.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()},
                                            "body": body, "t": time.monotonic()})
                    server.calls += 1
                    counter = server.calls
                    step = server.steps.pop(0) if server.steps else None
                if self.path.rstrip("/") == "/chat/completions":
                    self._send(403, {"error": {"message": "route requires /v1 prefix"}})
                    return
                if self.path.rstrip("/") != "/v1/chat/completions":
                    self._send(404, {"error": {"message": f"unknown path {self.path}"}})
                    return
                if server.require_token and self.headers.get("Authorization") != f"Bearer {server.token}":
                    self._send(401, {"error": {"message": "missing or invalid bearer token"}})
                    return
                if isinstance(body, dict) and int(body.get("n", 1) or 1) > 1:
                    self._send(400, {"error": {"message": "n > 1 is refused"}})
                    return
                self._serve(step or scenario_step(server.scenario, body, counter), body, counter)

            def _serve(self, step: Step, body: Any, counter: int):
                if step.kind == "delay":
                    time.sleep(step.delay_s)
                    step = step.then or scenario_step(server.scenario, body, counter)
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


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Mock House route")
    p.add_argument("--port", type=int, default=8008)
    p.add_argument("--scenario", choices=SCENARIOS, default="auto")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)
    server = MockHouse(scenario=args.scenario, port=args.port, verbose=not args.quiet).start()
    sys.stderr.write(f"mock House serving scenario={args.scenario!r} at {server.endpoint}/v1\n"
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
