"""HTTP integration checks for the optional HTTPS portal / loopback worker bridge.

Run with the project's Python environment. Uses only ephemeral loopback servers,
synthetic SRT/comments, and standard-library HTTP; no browser or outside service.
"""
from __future__ import annotations

import http.client
import json
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
from urllib.parse import parse_qs, urlsplit
import uuid


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parents[1]
ARTIFACTS = WORKSPACE / "work" / ("bridge-" + uuid.uuid4().hex[:10])
PORTAL = "https://live-notes-test.vercel.app"
CHECKS: list[dict] = []


def check(condition, description):
    if not condition:
        raise AssertionError(description)
    CHECKS.append({"check": description, "status": "passed"})
    print("PASS: " + description, flush=True)


def request(port, method, path, headers=None, body=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, {k.lower(): v for k, v in response.getheaders()}, response.read()
    finally:
        connection.close()


def unused_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        return server.getsockname()[1]


class Worker:
    def __init__(self, label, portal=None):
        self.directory = ARTIFACTS / label
        self.directory.mkdir(parents=True)
        self.port = unused_port()
        command = [sys.executable, str(ROOT / "tool.py"), "--no-browser", "--port", str(self.port),
                   "--data-dir", str(self.directory)]
        if portal:
            command += ["--portal", portal]
        self.log = (self.directory / "process.log").open("wb")
        self.process = subprocess.Popen(command, stdout=self.log, stderr=subprocess.STDOUT,
                                        cwd=WORKSPACE)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError("Loopback worker exited before listening; inspect process.log")
            try:
                status, _, body = request(self.port, "GET", "/")
                if status == 200:
                    matched = re.search(rb"const TOKEN='([a-f0-9]+)'", body)
                    if not matched:
                        raise AssertionError("Native local page must contain its session token")
                    self.token = matched[1].decode("ascii")
                    return
            except (ConnectionError, OSError):
                pass
            time.sleep(0.1)
        raise TimeoutError("Loopback worker did not start")

    def headers(self, origin=PORTAL, token=True):
        result = {"Origin": origin} if origin else {}
        if token:
            result["X-Session-Token"] = self.token
        return result

    def stop(self):
        if self.process.poll() is None:
            try:
                request(self.port, "POST", "/api/shutdown",
                        headers={"X-Session-Token": self.token, "Content-Type": "application/json"}, body=b"{}")
                self.process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                self.process.terminate()
                self.process.wait(timeout=5)
        self.log.close()


def preflight(worker, origin=PORTAL, method="POST", requested="content-type, x-session-token", pna="true", host=None):
    headers = {"Origin": origin, "Access-Control-Request-Method": method,
               "Access-Control-Request-Headers": requested}
    if pna is not None:
        headers["Access-Control-Request-Private-Network"] = pna
    if host is not None:
        headers["Host"] = host
    return request(worker.port, "OPTIONS", "/api/start", headers)


def check_authorization(worker):
    status, headers, _ = preflight(worker)
    check(status == 204 and headers.get("access-control-allow-origin") == PORTAL,
          "Approved exact HTTPS Origin receives successful CORS preflight")
    check(headers.get("access-control-allow-private-network") == "true",
          "Approved Private Network Access preflight permits loopback access")
    check(set(headers["access-control-allow-methods"].replace(" ", "").split(",")) == {"GET", "POST", "OPTIONS"},
          "Preflight advertises only supported methods")
    check(set(headers["access-control-allow-headers"].lower().replace(" ", "").split(",")) == {"content-type", "x-session-token"},
          "Preflight exposes only content type and session token request headers")
    check(headers.get("vary") == "Origin" and "access-control-allow-credentials" not in headers,
          "CORS varies by Origin and does not enable credential cookies")
    for requested in ("", "X-Session-Token", "CONTENT-TYPE", "x-session-token, Content-Type"):
        status, _, _ = preflight(worker, requested=requested)
        check(status == 204, "Allowed header subset accepted: " + (requested or "empty"))
    for requested in ("authorization", "content-type,x-unapproved", "x-session-token, x-forwarded-host"):
        status, _, _ = preflight(worker, requested=requested)
        check(status == 403, "Unapproved header rejected: " + requested)
    for method in ("PUT", "DELETE", "", "post"):
        status, _, _ = preflight(worker, method=method)
        check(status == 403, "Unsupported preflight method rejected: " + (method or "empty"))
    for pna in (None, "false"):
        status, headers, _ = preflight(worker, pna=pna)
        check(status == 204 and "access-control-allow-private-network" not in headers,
              "PNA permission appears only on explicit true request: " + str(pna))
    hostile_origins = ("https://other.vercel.app", "https://live-notes-test.vercel.app.evil.example",
                       "http://live-notes-test.vercel.app", PORTAL + "/", PORTAL + ":444", "null")
    for origin in hostile_origins:
        status, headers, _ = preflight(worker, origin=origin)
        check(status == 403 and "access-control-allow-origin" not in headers,
              "Unapproved exact Origin preflight rejected: " + origin)
        status, headers, _ = request(worker.port, "GET", "/api/jobs", worker.headers(origin))
        check(status == 403 and "access-control-allow-origin" not in headers,
              "Unapproved Origin rejected even with valid token: " + origin)
    status, headers, _ = preflight(worker, host="attacker.example")
    check(status == 403, "Preflight rejects a forged Host header")
    for path in ("/api/health", "/api/jobs"):
        status, _, _ = request(worker.port, "GET", path, worker.headers(token=False))
        check(status == 403, "Approved Origin still needs session token for " + path)
    status, _, _ = request(worker.port, "POST", "/api/start",
                          {"Origin": PORTAL, "Content-Type": "application/json"}, b"{}")
    check(status == 403, "Approved Origin cannot start a task without session token")
    status, _, _ = request(worker.port, "POST", "/api/upload?ext=.srt",
                          {"Origin": PORTAL, "Content-Type": "application/octet-stream"}, b"example")
    check(status == 403, "Approved Origin cannot upload without session token")
    check(not list((worker.directory / "uploads").iterdir()), "Rejected uploads write no files")
    for with_token in (False, True):
        status, _, body = request(worker.port, "GET", "/", worker.headers(token=with_token))
        check(status == 403 and worker.token.encode("ascii") not in body,
              "Portal cannot discover local page or token via root endpoint; token supplied=" + str(with_token))
    status, headers, body = request(worker.port, "GET", "/api/health", worker.headers())
    info = json.loads(body)
    check(status == 200 and info["portal_origin"] == PORTAL and info["bridge_protocol"] == 1,
          "Paired Origin and token read bridge health protocol")
    check(headers.get("access-control-allow-origin") == PORTAL and headers.get("cache-control") == "no-store",
          "Authorized API response has exact CORS Origin and no-store caching")
    local_origin = "http://127.0.0.1:" + str(worker.port)
    status, _, _ = request(worker.port, "GET", "/api/jobs", worker.headers(origin=local_origin))
    check(status == 200, "Existing same-origin native API remains usable")
    status, _, _ = request(worker.port, "GET", "/api/jobs", worker.headers(origin=None))
    check(status == 200, "Existing local API clients without Origin remain usable with token")
    status, _, _ = request(worker.port, "GET", "/api/jobs", {"Host": "attacker.example", "X-Session-Token": worker.token})
    check(status == 403, "Actual API request rejects a forged Host header")


def check_pairing(worker):
    link_path = worker.directory / "online-workspace-link.txt"
    check(link_path.is_file(), "Portal startup creates an online workspace pairing link")
    parsed = urlsplit(link_path.read_text(encoding="utf-8"))
    fragment = parse_qs(parsed.fragment)
    check(parsed.scheme + "://" + parsed.netloc == PORTAL and parsed.path == "/" and not parsed.query,
          "Pairing URL uses approved HTTPS portal with no query string")
    check(fragment == {"bridge": ["http://127.0.0.1:" + str(worker.port)], "token": [worker.token]},
          "Pairing URL fragment contains exact loopback endpoint and current session token")
    check((worker.directory / "local-address.txt").read_text(encoding="utf-8") == "http://127.0.0.1:" + str(worker.port) + "/",
          "Native local address remains available alongside portal link")


def upload(worker, extension, body):
    headers = worker.headers()
    headers["Content-Type"] = "application/octet-stream"
    status, response_headers, raw = request(worker.port, "POST", "/api/upload?ext=" + extension, headers, body)
    check(status == 200 and response_headers.get("access-control-allow-origin") == PORTAL,
          "Authorized portal upload succeeds for " + extension)
    return json.loads(raw)["file"]


def check_workflow(worker):
    srt = "1\n00:00:00,000 --> 00:00:12,000\n大家好，欢迎来到直播间。今天教大家三个产品使用方法，留言告诉我你的问题。\n\n2\n00:00:12,500 --> 00:00:25,000\n第一步打开开关，第二步调节大小。如果听得清楚请回复一，感谢大家分享。\n\n3\n00:00:25,500 --> 00:00:40,000\n最后总结三个方法。明天晚上我们会示范更多步骤，记得关注。\n"
    comments = "id,timestamp,text,user_id\n1,00:00:05,听得到，想知道怎么调节大小,user-1\n2,00:00:18,谢谢，讲得清楚,user-2\n"
    transcript_file = upload(worker, ".srt", srt.encode("utf-8"))
    comments_file = upload(worker, ".csv", comments.encode("utf-8"))
    config = {"title": "Bridge integration · 中文直播复盘", "transcript": transcript_file,
              "comments": comments_file, "asr_model": "small", "language": "zh", "offset": 0}
    headers = worker.headers()
    headers["Content-Type"] = "application/json"
    status, _, body = request(worker.port, "POST", "/api/start", headers, json.dumps(config).encode("utf-8"))
    check(status == 200, "Authorized portal starts imported transcript analysis")
    job_id = json.loads(body)["id"]
    deadline = time.monotonic() + 15
    job = None
    while time.monotonic() < deadline:
        status, _, body = request(worker.port, "GET", "/api/jobs/" + job_id, worker.headers())
        if status != 200:
            raise AssertionError("Running job lookup failed")
        job = json.loads(body)
        if job["status"] in ("done", "failed", "cancelled"):
            break
        time.sleep(0.05)
    check(job is not None and job["status"] == "done", "SRT and comment analysis finishes without transcription model download")
    report = job["report"]
    check(len(report["transcript"]) == 3 and len(report["comments"]) == 2,
          "Report contains all three transcript segments and both comments")
    check(report["transcript"][0]["text"] == srt.splitlines()[2] and report["transcript"][0]["start"] == 0,
          "Report preserves Chinese transcript text and timing")
    check(all(field in report["analysis"] for field in ("style", "strengths", "weaknesses", "actions", "limitations")),
          "Report includes review dimensions and data limitations")
    for kind in ("txt", "srt", "json", "md", "html"):
        path = "/api/export/" + job_id + "/" + kind
        status, response_headers, body = request(worker.port, "GET", path, worker.headers())
        text = body.decode("utf-8-sig")
        check(status == 200 and bool(body) and ("." + kind + '"') in response_headers.get("content-disposition", ""),
              "Portal token-header export succeeds for " + kind)
        check("大家好" in text and response_headers.get("access-control-allow-origin") == PORTAL,
              "Export preserves Chinese content and CORS for " + kind)
        status, _, _ = request(worker.port, "GET", path, worker.headers(token=False))
        check(status == 403, "Export requires token for " + kind)
    status, _, _ = request(worker.port, "GET", "/api/export/" + job_id + "/txt?token=" + worker.token)
    check(status == 200, "Native local export links using existing query-token mode still work")
    check((worker.directory / "runs" / job_id / "report.html").is_file() and
          (worker.directory / "runs" / job_id / "transcript.srt").is_file(),
          "Completed bridge task persists report and subtitle files locally")
    return job_id


def check_native():
    worker = Worker("native")
    try:
        check(not (worker.directory / "online-workspace-link.txt").exists(), "Native-only startup creates no portal pairing link")
        status, headers, _ = request(worker.port, "GET", "/api/jobs", worker.headers())
        check(status == 403 and "access-control-allow-origin" not in headers,
              "Native-only mode rejects a Vercel Origin even with valid token")
        status, _, _ = preflight(worker)
        check(status == 403, "Native-only mode rejects cross-origin preflight")
        local_origin = "http://127.0.0.1:" + str(worker.port)
        status, _, _ = request(worker.port, "GET", "/api/health", worker.headers(origin=local_origin))
        check(status == 200, "Native-only same-origin authenticated health remains usable")
        status, _, _ = request(worker.port, "GET", "/api/health", worker.headers(origin=None, token=False))
        check(status == 403, "Native-only APIs continue to require a session token")
    finally:
        worker.stop()


def check_invalid_portals():
    invalid = ("http://live-notes-test.vercel.app", PORTAL + "/path", PORTAL + "?token=redacted",
               PORTAL + "#pair", "https://user:pass@live-notes-test.vercel.app", PORTAL + ":444",
               "https://localhost", "https://127.0.0.1", "https://[::1]", "https://bridge.localhost",
               "https://", "not-a-url", "https://live-notes-test.vercel.app:not-a-port")
    for portal in invalid:
        result = subprocess.run([sys.executable, str(ROOT / "tool.py"), "--portal", portal, "--no-browser",
                                 "--data-dir", str(ARTIFACTS / "invalid")], cwd=WORKSPACE,
                                capture_output=True, timeout=5)
        check(result.returncode != 0, "Invalid portal CLI argument rejected: " + portal)
    check(not (ARTIFACTS / "invalid").exists(), "Invalid portal CLI arguments start no worker and create no data directory")


def main():
    ARTIFACTS.mkdir(parents=True)
    worker = None
    try:
        worker = Worker("portal", PORTAL)
        check_pairing(worker)
        check_authorization(worker)
        job_id = check_workflow(worker)
        check_native()
        check_invalid_portals()
        result = {"status": "passed", "checks": len(CHECKS), "job_id": job_id,
                  "scope": "HTTP loopback integration; synthetic imported SRT and comments; no browser or external network",
                  "results": CHECKS}
        (ARTIFACTS / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Completed {len(CHECKS)} HTTP checks. Results: {ARTIFACTS / 'results.json'}", flush=True)
    except Exception as exc:
        (ARTIFACTS / "results.json").write_text(json.dumps({"status": "failed", "error": str(exc),
                                                          "checks": CHECKS}, ensure_ascii=False, indent=2), encoding="utf-8")
        raise
    finally:
        if worker is not None:
            worker.stop()


if __name__ == "__main__":
    main()
