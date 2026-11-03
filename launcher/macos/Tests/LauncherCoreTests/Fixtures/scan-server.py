import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

mode, directory = sys.argv[1], Path(sys.argv[2])
instance = "0123456789abcdef01234567"
paused_until = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat() if mode == "paused" else None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, code, data, **headers):
        data = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def schedule(self):
        return {"generated_at": datetime.now(timezone.utc).isoformat(), "enabled": True, "plan": {
            "enabled": mode != "schedule-disabled", "paused_until": paused_until,
        }}

    def do_GET(self):
        with (directory / "reads.jsonl").open("a") as log:
            log.write(json.dumps({"path": self.path, "tz": parse_qs(urlsplit(self.path).query).get("tz")}) + "\n")
        if urlsplit(self.path).path == "/api/release-notes":
            identity = {"product": "roleband", "instance": instance, "api_origin": origin, "version": "0.1.0", "format": 1}
            if mode == "notes-mismatch":
                identity["instance"] = "abcdef0123456789abcdef01"
            if mode == "notes-version":
                identity["version"] = "0.2.0"
            if mode == "notes-replacement":
                (directory / "installation.json").write_text("{}")
            if mode == "notes-redirect":
                self.reply(307, {}, Location=origin + "/unexpected")
            else:
                self.reply(200, {"launcher": identity, "version": identity["version"],
                                 "notes": None if mode == "notes-missing" else "First public release.\n\n- **Your Radar.** Open it from the menu bar."})
            return
        if urlsplit(self.path).path == "/api/schedule":
            if mode == "schedule-replacement":
                registration = directory / "installation.json"
                identity = json.loads(registration.read_text())
                identity["instance"] = "abcdef0123456789abcdef01"
                registration.write_text(json.dumps(identity))
            if mode == "schedule-invalid":
                self.reply(200, {"plan": {}})
            else:
                body = self.schedule()
                if mode in {"schedule-large", "schedule-oversized"}:
                    body["bindings"] = [{"company": "example", "ignored": "x" * (300000 if mode == "schedule-large" else 4194304)}]
                self.reply(200, body)
            return
        manual = mode in {"manual", "stop_error", "stop_redirect", "stop_slow"}
        status = {"observed_at": "2026-10-28T12:00:00Z", "activity": "idle", "attention": [], "model": "ready"}
        if mode == "held":
            status["hold"] = {"kind": "attention", "reason": "schema_pending"}
        if mode == "scheduled" or manual:
            status["activity"] = "scanning"
        identity = {"product": "roleband", "instance": instance, "api_origin": origin, "version": "0.1.0", "format": 1}
        if mode == "replacement":
            replacement = {**identity, "instance": "abcdef0123456789abcdef01"}
            (directory / "installation.json").write_text(json.dumps(replacement))
        if mode in {"mismatch", "schedule-mismatch"}:
            identity["instance"] = "abcdef0123456789abcdef01"
        body = {"db": "ok", "launcher": {**identity, "status": status}, "running": mode == "scheduled" or manual,
                "manual_sync_running": manual, "manual_queued": ["example"] if mode == "queued" else []}
        if mode == "legacy":
            del body["manual_sync_running"]
        if mode in {"status-large", "status-oversized"}:
            # The engine's scheduler lists grow with the companies a person follows.
            companies = 6000 if mode == "status-large" else 70000
            body["scheduler"] = {"due": [{"company": f"company-{index:05}", "reason": "stale", "queued": True}
                                         for index in range(companies)]}
        self.reply(200, body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode()
        with (directory / "requests.jsonl").open("a") as log:
            log.write(json.dumps({"path": self.path, "body": body, "origin": self.headers.get("Origin"),
                                  "content_type": self.headers.get("Content-Type")}) + "\n")
        if mode in {"redirect", "stop_redirect"}:
            self.reply(307, {}, Location=origin + "/unexpected")
        elif mode == "refused":
            self.reply(409, {"error": {"code": "scheduling_unavailable"}})
        elif mode == "stop_error":
            self.reply(200, {"status": "error", "pid": None, "dequeued": []})
        elif mode == "invalid":
            self.reply(200, {"status": "unrelated"})
        elif mode == "stop_slow":
            time.sleep(9)
            self.reply(200, {"status": "cancelled"})
        else:
            self.reply(200, {"status": "cancelled" if self.path.endswith("/cancel") else "started"})

    def do_PUT(self):
        global paused_until
        body = self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode()
        with (directory / "requests.jsonl").open("a") as log:
            log.write(json.dumps({"path": self.path, "body": body, "method": "PUT", "origin": self.headers.get("Origin"),
                                  "content_type": self.headers.get("Content-Type")}) + "\n")
        if mode == "schedule-refused":
            self.reply(409, {})
        elif mode == "schedule-redirect":
            self.reply(307, {}, Location=origin + "/unexpected")
        elif mode == "schedule-uncertain":
            self.reply(200, self.schedule())
        else:
            action = json.loads(body)["pause"]
            paused_until = None if action == "resume" else (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
            self.reply(200, self.schedule())


server = HTTPServer(("127.0.0.1", 0), Handler)
origin = f"http://127.0.0.1:{server.server_port}"
print(origin, flush=True)
server.serve_forever()
