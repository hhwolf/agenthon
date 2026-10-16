"""Local Final admission gate and allowlisted forward proxy (stdlib only).

The canned model responses come from the teammate's tests/mock_house.py. This
module adds Final's admission semantics without changing that test fixture.
Neither service contacts an actual model provider or exposes an admin API.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import http.client
import importlib.util
import json
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ORIGIN = "http://house.internal:8000"
BODY_LIMIT = 8 * 1024**2


def atomic_json(path: Path, value: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, indent=2) + "\n")
    tmp.replace(path)


def valid_bearer(received: str, token: str) -> bool:
    return hmac.compare_digest(received.encode("utf-8"), ("Bearer " + token).encode("utf-8"))


def request_hash(unit_id: str, model: str, params: dict) -> str:
    # Exact format of t2agent.text_layer.client.ResponseCache.key.
    blob = json.dumps({"unit_id": unit_id, "model": model, "params": params},
                      sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


def replay_response(directory: Path, unit_id: str, body: dict) -> tuple[dict | None, str | None]:
    # Phase 3 flat cache, keyed by the exact OpenAI request fields. Keep legacy
    # per-unit caches below so previously published Phase M fixtures still replay.
    for path in sorted(directory.glob("*.json")):
        try:
            record = json.loads(path.read_text())
            if not isinstance(record, dict) or record.get("unit_id") != unit_id:
                continue
            model = record.get("model")
            if not isinstance(model, str) or not isinstance(record.get("text"), str):
                continue
            params = dict(body, model=model)
            if "chat_template_kwargs" in params:
                params["extra_body"] = {"chat_template_kwargs": params.pop("chat_template_kwargs")}
            fields = ("model", "messages", "temperature", "top_p", "seed", "max_tokens", "extra_body")
            blob = json.dumps({k: params.get(k) for k in fields}, sort_keys=True, ensure_ascii=False)
            key = hashlib.sha256(blob.encode("utf-8")).hexdigest()
            if path.name == key + ".json":
                return record, key
        except (OSError, ValueError):
            continue
    folder = directory / (re.sub(r"[^A-Za-z0-9._-]+", "_", unit_id) or "unit")
    models = set()
    for path in folder.glob("*.json"):
        try:
            record = json.loads(path.read_text())
            model = record.get("model") if isinstance(record, dict) else None
            if isinstance(model, str):
                models.add(model)
        except (OSError, ValueError):
            continue
    for model in sorted(models):
        params = dict(body, model=model)
        # The OpenAI SDK merges extra_body into the wire JSON.
        if "chat_template_kwargs" in params:
            params["extra_body"] = {"chat_template_kwargs": params.pop("chat_template_kwargs")}
        key = request_hash(unit_id, model, params)
        path = folder / f"{key}.json"
        if path.is_file():
            payload = json.loads(path.read_text())
            if isinstance(payload, dict) and isinstance(payload.get("text"), str) and payload.get("model") == model:
                return payload, key
    return None, None


def canned_module():
    local = Path(__file__).with_name("mock_house.py")
    source = local if local.exists() else Path(__file__).resolve().parents[1] / "tests/mock_house.py"
    spec = importlib.util.spec_from_file_location("_phase_m_canned", source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Handler(BaseHTTPRequestHandler):
    # Closing connections also bounds clients that send a body on a refused route.
    protocol_version = "HTTP/1.0"

    def log_message(self, *_):
        pass  # Never log bearer credentials or prompt text.

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def send(self, status: int, payload, *, raw=False):
        data = payload if raw else json.dumps(payload).encode()
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass

    def error(self, status, message):
        self.send(status, {"error": {"message": message}})

    def body_bytes(self):
        if self.headers.get("Transfer-Encoding"):
            raise ValueError("chunked request bodies are unsupported")
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 < size <= BODY_LIMIT:
            raise ValueError("invalid request body size")
        data = self.rfile.read(size)
        if len(data) != size:
            raise ValueError("incomplete request body")
        return data

    def do_GET(self):
        self.error(405, "only POST /v1/chat/completions is supported")

    do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = do_GET

    def do_CONNECT(self):
        self.error(403, "CONNECT is disabled; only the local House HTTP origin is allowed")


class HouseState:
    def __init__(self, directory: Path, mode="canned", replay_dir=None,
                 timeout_delay=120.0, slow_delay=1.0):
        self.directory, self.mode, self.replay_dir = directory, mode, replay_dir
        self.timeout_delay, self.slow_delay = timeout_delay, slow_delay
        self.lock = threading.Lock()
        self.canned = canned_module()
        self.stats = {"units": {}, "events": []}
        path = directory / "stats.json"
        if path.exists():
            self.stats = json.loads(path.read_text())

    def admit(self, bearer: str, body: dict):
        with self.lock:
            try:
                active = json.loads((self.directory / "active.json").read_text())
            except (OSError, ValueError):
                return 401, "no active unit", None
            if not valid_bearer(bearer, active["token"]):
                return 401, "missing or invalid bearer", None
            if time.time() >= active["expires"]:
                return 401, "unit credential expired", None
            if not isinstance(body, dict) or not isinstance(body.get("messages"), list):
                return 400, "messages must be an array", None
            if body.get("model") != "house":
                return 400, "model must be house", None
            if type(body.get("n", 1)) is not int or body.get("n", 1) != 1:
                return 400, "only n=1 is supported", None
            if body.get("stream") or body.get("tools") or body.get("functions"):
                return 400, "streaming and tools are not supported by this mock", None
            limit = body.get("max_tokens", 4000)
            if type(limit) is not int or limit <= 0:
                return 400, "max_tokens must be a positive integer", None
            if "max_completion_tokens" in body:
                extra = body["max_completion_tokens"]
                if type(extra) is not int or extra <= 0:
                    return 400, "invalid max_completion_tokens", None
                limit = min(limit, extra)
                body["max_completion_tokens"] = min(4000, extra)
            body["max_tokens"] = min(4000, limit)
            unit = active["unit_id"]
            count = self.stats["units"].get(unit, 0)
            if count >= 25:
                return 429, "25 admitted requests exhausted", None
            count += 1
            self.stats["units"][unit] = count
            event = {"unit_id": unit, "admitted": count, "mode": self.mode,
                     "request_hash": request_hash(unit, "house", body),
                     "max_tokens": body["max_tokens"]}
            self.stats["events"].append(event)
            atomic_json(self.directory / "stats.json", self.stats)
            return 200, "", (unit, count, event)

    def record(self, event, **updates):
        with self.lock:
            event.update(updates)
            atomic_json(self.directory / "stats.json", self.stats)


def house_handler(state: HouseState):
    class HouseHandler(Handler):
        def do_POST(self):
            if not self.path.startswith("/v1/"):
                return self.error(403, "route requires /v1 prefix")
            if self.path != "/v1/chat/completions":
                return self.error(404, "unknown route")
            # Authentication precedes JSON parsing (including missing bearer).
            try:
                active = json.loads((state.directory / "active.json").read_text())
                valid = valid_bearer(self.headers.get("Authorization", ""), active["token"])
            except (OSError, ValueError):
                valid = False
            if not valid:
                return self.error(401, "missing or invalid bearer")
            try:
                body = json.loads(self.body_bytes())
            except (ValueError, TimeoutError):
                return self.error(400, "invalid JSON request")
            status, message, admission = state.admit(self.headers.get("Authorization", ""), body)
            if status != 200:
                return self.error(status, message)
            unit, count, event = admission
            replay = None
            if state.mode == "replay":
                try:
                    replay, key = replay_response(state.replay_dir, unit, body)
                except (OSError, ValueError):
                    replay, key = None, None
                state.record(event, replay_hit=replay is not None, cache_hash=key)
                if replay is None:
                    state.record(event, behavior="replay_miss", status=503)
                    return self.error(503, "no exact cached request; no provider fallback")
                behavior = "replay"
            elif state.mode == "chaos":
                behavior = ("5xx", "timeout", "slow", "malformed_json", "malformed_content", "canned")[(count-1) % 6]
            else:
                behavior = "canned"
            state.record(event, behavior=behavior)
            if behavior == "5xx":
                state.record(event, status=503)
                return self.error(503, "mock upstream failure (admitted request charged)")
            if behavior in {"timeout", "slow"}:
                time.sleep(state.timeout_delay if behavior == "timeout" else state.slow_delay)
            if behavior == "malformed_json":
                state.record(event, status=200)
                return self.send(200, b'{"choices": [invalid', raw=True)
            if replay is not None:
                content, finish = replay["text"], replay.get("finish_reason", "stop")
                usage = replay.get("usage", {})
            else:
                step = state.canned.scenario_step("invalid_json" if behavior == "malformed_content" else "auto", body, count)
                content, finish = step.content, step.finish_reason
                if not isinstance(content, str):
                    content = json.dumps(content)
                # A character estimate for generated fixtures only. Exact replay
                # preserves the cached model's text, finish reason and token usage.
                if len(content) > body["max_tokens"] * 4:
                    content, finish = content[:body["max_tokens"] * 4], "length"
                usage = {"prompt_tokens": 0, "completion_tokens": (len(content)+3)//4,
                         "total_tokens": (len(content)+3)//4}
            state.record(event, status=200)
            self.send(200, {"id": f"mock-{count}", "object": "chat.completion", "created": int(time.time()),
                            "model": "house", "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                                                             "finish_reason": finish}], "usage": usage})
    return HouseHandler


def proxy_handler(backend="house", port=8000):
    class ProxyHandler(Handler):
        def do_POST(self):
            try:
                url = urlsplit(self.path)
            except ValueError:
                return self.error(403, "invalid proxy origin")
            if url.scheme != "http" or url.netloc != "house.internal:8000" or url.fragment:
                return self.error(403, "only the mock House origin is allowed")
            try:
                data = self.body_bytes()
            except (ValueError, TimeoutError):
                return self.error(400, "invalid proxy request")
            connection = http.client.HTTPConnection(backend, port, timeout=1700)
            try:
                # Fixed backend, no user-controlled DNS, redirects or hop-by-hop headers.
                path = url.path + ("?" + url.query if url.query else "")
                connection.request("POST", path, data, {"Authorization": self.headers.get("Authorization", ""),
                                                        "Content-Type": "application/json"})
                response = connection.getresponse()
                self.send(response.status, response.read(BODY_LIMIT), raw=True)
            except (OSError, http.client.HTTPException):
                self.error(502, "mock House connection failed")
            finally:
                connection.close()
    return ProxyHandler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=["house", "proxy"])
    parser.add_argument("--port", type=int)
    parser.add_argument("--state", type=Path, default=Path("/state"))
    parser.add_argument("--mode", choices=["canned", "chaos", "replay"], default="canned")
    parser.add_argument("--replay-dir", type=Path, default=Path("/replay"))
    parser.add_argument("--timeout-delay", type=float, default=120)
    parser.add_argument("--slow-delay", type=float, default=1)
    args = parser.parse_args()
    if args.role == "house":
        handler = house_handler(HouseState(args.state, args.mode, args.replay_dir, args.timeout_delay, args.slow_delay))
    else:
        handler = proxy_handler()
    server = ThreadingHTTPServer(("0.0.0.0", args.port or (8000 if args.role == "house" else 3128)), handler)
    server.daemon_threads = True
    server.serve_forever()


if __name__ == "__main__":
    main()
