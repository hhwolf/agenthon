import concurrent.futures
import http.client
import json
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from t2eval.mock_house_service import HouseState, atomic_json, house_handler, proxy_handler, request_hash


@contextmanager
def serving(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def call(port, body=None, *, token="token", path="/v1/chat/completions", method="POST", timeout=2):
    body = {"model": "house", "messages": []} if body is None else body
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        connection.request(method, path, json.dumps(body), {"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def state_at(path, mode="canned", **kwargs):
    atomic_json(path / "active.json", {"unit_id": "unit", "token": "token", "expires": time.time()+60})
    return HouseState(path, mode, **kwargs)


def test_routes_auth_and_preadmission_validation(tmp_path):
    state = state_at(tmp_path)
    with serving(house_handler(state)) as port:
        assert call(port, token="")[0] == 401
        assert call(port, path="/chat/completions")[0] == 403
        assert call(port, path="/v1/models", method="GET")[0] == 405
        assert call(port, path="/v1/models")[0] == 404
        for body in [[], {"model": "wrong", "messages": []}, {"model": "house", "messages": [], "n": 2},
                     {"model": "house", "messages": [], "n": True}, {"model": "house", "messages": [], "max_tokens": 0}]:
            assert call(port, body)[0] == 400
        assert state.stats["units"] == {}
        assert call(port)[0] == 200
        assert call(port, {"model": "house", "messages": [], "max_tokens": 9000})[0] == 200
        status, raw = call(port, {"model": "house", "messages": [], "max_tokens": 1})
        assert status == 200
        assert json.loads(raw)["usage"]["completion_tokens"] == 1
        assert [x["max_tokens"] for x in state.stats["events"]] == [4000, 4000, 1]
        atomic_json(tmp_path / "active.json", {"unit_id": "unit", "token": "token", "expires": 0})
        assert call(port)[0] == 401
        assert state.stats["units"] == {"unit": 3}


def test_concurrent_admission_persists_across_service_restart(tmp_path):
    state = state_at(tmp_path)
    with serving(house_handler(state)) as port:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            codes = list(pool.map(lambda _: call(port)[0], range(30)))
    assert codes.count(200) == 25
    assert codes.count(429) == 5
    restored = HouseState(tmp_path)
    with serving(house_handler(restored)) as port:
        assert call(port)[0] == 429
        atomic_json(tmp_path / "active.json", {"unit_id": "next", "token": "next-token", "expires": time.time()+60})
        assert call(port)[0] == 401
        assert call(port, token="next-token")[0] == 200
    assert restored.stats["units"] == {"unit": 25, "next": 1}


def test_chaos_failures_and_timeouts_still_charge(tmp_path):
    state = state_at(tmp_path, "chaos", timeout_delay=.15, slow_delay=.02)
    with serving(house_handler(state)) as port:
        assert call(port)[0] == 503
        with pytest.raises(TimeoutError):
            call(port, timeout=.03)
        assert state.stats["units"]["unit"] == 2
        assert call(port)[0] == 200
        status, raw = call(port)
        assert status == 200
        with pytest.raises(ValueError):
            json.loads(raw)
        assert call(port)[0] == 200
        assert call(port)[0] == 200
        time.sleep(.2)
    assert state.stats["units"]["unit"] == 6
    assert [e["behavior"] for e in state.stats["events"]] == ["5xx", "timeout", "slow", "malformed_json", "malformed_content", "canned"]


def test_replay_uses_teammates_exact_cache_key_and_fails_closed(tmp_path):
    from t2agent.text_layer.client import ResponseCache
    cache = ResponseCache(tmp_path / "cache")
    params = {"model": "dev-model", "messages": [{"role": "user", "content": "hello"}],
              "max_tokens": 4000, "temperature": 0, "top_p": 1, "seed": 20261014,
              "extra_body": {"chat_template_kwargs": {"enable_thinking": False}}}
    key = cache.key("unit", "dev-model", params)
    assert key == request_hash("unit", "dev-model", params)
    cache.put("unit", key, {"model": "dev-model", "text": "cached answer", "finish_reason": "stop"})
    wire = dict(params, model="house")
    wire.update(wire.pop("extra_body"))
    state = state_at(tmp_path, "replay", replay_dir=cache.directory)
    with serving(house_handler(state)) as port:
        status, raw = call(port, wire)
        assert status == 200
        assert json.loads(raw)["choices"][0]["message"]["content"] == "cached answer"
        assert call(port, dict(wire, temperature=.1))[0] == 503
    assert state.stats["units"] == {"unit": 2}
    assert state.stats["events"][0]["cache_hash"] == key
    assert state.stats["events"][1]["replay_hit"] is False


def test_replay_preserves_long_text_finish_reason_and_usage(tmp_path):
    from t2agent.text_layer.client import ResponseCache
    cache = ResponseCache(tmp_path / "cache")
    params = {"model": "dev", "messages": [], "max_tokens": 4000}
    content = "longword " * 2500  # More than the canned four-character estimate.
    usage = {"prompt_tokens": 9, "completion_tokens": 2500, "total_tokens": 2509}
    cache.put("unit", cache.key("unit", "dev", params),
              {"model": "dev", "text": content, "finish_reason": "stop", "usage": usage})
    state = state_at(tmp_path, "replay", replay_dir=cache.directory)
    with serving(house_handler(state)) as port:
        status, raw = call(port)
    result = json.loads(raw)
    assert status == 200
    assert result["choices"][0]["message"]["content"] == content
    assert result["choices"][0]["finish_reason"] == "stop"
    assert result["usage"] == usage


def test_proxy_allows_only_fixed_house_backend(tmp_path):
    state = state_at(tmp_path)
    with serving(house_handler(state)) as house:
        with serving(proxy_handler("127.0.0.1", house)) as proxy:
            assert call(proxy, path="http://house.internal:8000/v1/chat/completions")[0] == 200
            assert call(proxy, path="http://house.internal:8000/chat/completions")[0] == 403
            for path in ["http://example.com/v1/chat/completions", "http://house.internal:8000@evil/v1/chat/completions",
                         "https://house.internal:8000/v1/chat/completions", "/v1/chat/completions"]:
                assert call(proxy, path=path)[0] == 403
            assert call(proxy, path="example.com:443", method="CONNECT")[0] == 403
    assert state.stats["units"] == {"unit": 1}


def test_proxy_bad_framing_and_unavailable_backend():
    import socket
    class BrokenBackend(BaseHTTPRequestHandler):
        def do_POST(self):
            self.close_connection = True  # Upstream drops before sending headers.
    with serving(BrokenBackend) as broken_port:
        with serving(proxy_handler("127.0.0.1", broken_port)) as port:
            assert call(port, path="http://house.internal:8000/v1/chat/completions")[0] == 502
            with socket.create_connection(("127.0.0.1", port), timeout=2) as sock:
                sock.sendall(b"POST http://[broken/v1/chat/completions HTTP/1.0\r\nContent-Length: 2\r\n\r\n{}")
                response = http.client.HTTPResponse(sock)
                response.begin()
                assert response.status == 403
                response.read()
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            try:
                connection.request("POST", "http://house.internal:8000/v1/chat/completions", "{}",
                                   {"Transfer-Encoding": "chunked"})
                response = connection.getresponse()
                assert response.status == 400
                response.read()
            finally:
                connection.close()
