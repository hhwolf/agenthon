"""Runs inside the solver's internal network; never contacts a real provider."""
import http.client
import json
import os
import socket
import time
from urllib.parse import urlsplit

proxy = urlsplit(os.environ["HTTP_PROXY"])
origin = os.environ["MODEL_ENDPOINT"]
token = os.environ["MODEL_TOKEN"]
mode = os.environ["PROBE_MODE"]
body = {"model": "house", "messages": [{"role": "user", "content": "hello"}], "max_tokens": 9000}


def request(payload=None, path="/v1/chat/completions", credential=token, target=origin, method="POST", timeout=2):
    conn = http.client.HTTPConnection(proxy.hostname, proxy.port, timeout=timeout)
    try:
        conn.request(method, target + path, json.dumps(payload or body), {"Authorization": "Bearer " + credential})
        response = conn.getresponse()
        return response.status, response.read().decode()
    finally:
        conn.close()


result = {"mode": mode, "checks": {}}
checks = result["checks"]
checks["unauthenticated"] = request(credential="")[0] == 401
checks["missing_v1"] = request(path="/chat/completions")[0] == 403
checks["n_refused"] = request(dict(body, n=2))[0] == 400
checks["other_origin_blocked"] = request(target="http://example.com")[0] == 403
checks["connect_blocked"] = request(target="example.com:443", path="", method="CONNECT")[0] == 403
for key, host, port in [("direct_house_blocked", os.environ["HOUSE_IP"], 8000), ("internet_blocked", "1.1.1.1", 80)]:
    try:
        sock = socket.create_connection((host, port), timeout=.25)
        sock.close()
        checks[key] = False
    except OSError:
        checks[key] = True
if mode == "canned":
    result["statuses"] = [request()[0] for _ in range(26)]
    checks["quota"] = result["statuses"] == [200]*25 + [429]
elif mode == "chaos":
    statuses = [request()[0]]
    try:
        request(timeout=.1)
        statuses.append("unexpected_response")
    except TimeoutError:
        statuses.append("timeout")
    start = time.monotonic()
    statuses.append(request()[0])
    result["slow_seconds"] = time.monotonic()-start
    status, raw = request()
    try:
        json.loads(raw)
        checks["malformed_json"] = False
    except ValueError:
        checks["malformed_json"] = status == 200
    statuses += [status, request()[0], request()[0]]
    result["statuses"] = statuses
    checks["chaos"] = statuses == [503, "timeout", 200, 200, 200, 200]
    checks["slow"] = result["slow_seconds"] >= .15
elif mode == "replay":
    payload = dict(body, max_tokens=4000, temperature=0, top_p=1, seed=20261014,
                   chat_template_kwargs={"enable_thinking": False})
    status, raw = request(payload)
    checks["exact_replay"] = status == 200 and json.loads(raw)["choices"][0]["message"]["content"] == "synthetic cached response"
    checks["replay_miss"] = request(dict(payload, temperature=.5))[0] == 503
else:
    raise ValueError(mode)
print(json.dumps(result))
raise SystemExit(0 if all(checks.values()) else 1)
