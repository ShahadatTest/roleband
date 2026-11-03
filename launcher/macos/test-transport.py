"""Exercise the built launcher's real HTTP client against local boundary fixtures."""
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    args = parser.parse_args()
    cases = json.loads((Path(__file__).resolve().parents[1] / 'contracts/status-cases.json').read_text())
    mode = 'ok'
    trap_hits = []
    release = threading.Event()
    identity = {'product': 'roleband', 'instance': '0123456789abcdef01234567', 'api_origin': '', 'version': '0.1.0', 'format': 1}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == '/trap':
                trap_hits.append(self.path)
            if mode == 'slow':
                release.wait(10)
            if mode == 'redirect':
                self.send_response(302)
                self.send_header('Location', identity['api_origin'] + '/trap')
                self.end_headers()
                return
            body = {'db': 'ok', 'launcher': identity | {'status': cases['cases'][0]['wire']}}
            if mode == 'wrong_product':
                body['launcher']['product'] = 'other-app'
            if mode == 'wrong_instance':
                body['launcher']['instance'] = 'another-checkout'
            if mode == 'legacy':
                body.pop('launcher')
            data = b'x' * 262145 if mode == 'oversized' else json.dumps(body).encode()
            self.send_response(503 if mode == 'http_failure' else 200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    identity['api_origin'] = f'http://127.0.0.1:{server.server_port}'
    results = []
    try:
        with tempfile.TemporaryDirectory(prefix='roleband-launcher-http-') as folder:
            path = Path(folder) / 'installation.json'
            path.write_text(json.dumps(identity))
            path.chmod(0o600)
            for mode in ('ok', 'wrong_product', 'wrong_instance', 'legacy', 'http_failure', 'redirect', 'oversized', 'slow'):
                result = subprocess.run([str(args.binary), '--verify-registration', str(path)], capture_output=True, text=True, timeout=8, check=False)
                expected = mode == 'ok'
                assert (result.returncode == 0) == expected, (mode, result.returncode, result.stdout, result.stderr)
                if expected:
                    assert json.loads(result.stdout)['activity'] == 'idle'
                results.append({'case': mode, 'accepted': result.returncode == 0})
                if mode == 'slow':
                    release.set()
        assert trap_hits == [], 'The client followed a redirect'
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        worker.join()
    print(json.dumps({'cases': results, 'redirect_trap_hits': len(trap_hits)}, indent=2))


if __name__ == '__main__':
    main()
