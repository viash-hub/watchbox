import json
import subprocess
import sys
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from urllib.parse import urlparse, parse_qs

# ---------------------------------------------------------------------------
# Fake Seqera API server
# ---------------------------------------------------------------------------
ORGS_RESPONSE = {
    "organizations": [
        {"orgId": 100, "name": "AcmeCorp", "fullName": "Acme Corporation"},
        {"orgId": 200, "name": "BetaLabs", "fullName": "Beta Laboratories"},
    ],
    "totalSize": 2,
}

WORKSPACES_100 = {
    "workspaces": [
        {"id": 1001, "name": "Production", "fullName": "Production workspace", "description": None, "visibility": "PRIVATE"},
        {"id": 1002, "name": "Staging", "fullName": "Staging workspace", "description": None, "visibility": "PRIVATE"},
    ]
}

WORKSPACES_200 = {
    "workspaces": [
        {"id": 2001, "name": "Research", "fullName": "Research workspace", "description": None, "visibility": "SHARED"},
    ]
}


class FakeSeqeraHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        auth = self.headers.get("Authorization", "")
        if auth != "Bearer test-token":
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'{"message":"Unauthorized"}')
            return

        if path == "/orgs":
            body = json.dumps(ORGS_RESPONSE).encode()
        elif path == "/orgs/100/workspaces":
            body = json.dumps(WORKSPACES_100).encode()
        elif path == "/orgs/200/workspaces":
            body = json.dumps(WORKSPACES_200).encode()
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"message":"Not found"}')
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass  # suppress request logs


def start_fake_server():
    server = HTTPServer(("127.0.0.1", 0), FakeSeqeraHandler)
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------
def run_script(base_url, token="test-token", org=None, output="out.md", output_json="out.json"):
    """Run script.py directly with par dict injected via env."""
    env = os.environ.copy()
    env["TOWER_ACCESS_TOKEN"] = token

    cmd = [
        sys.executable, os.path.join(os.path.dirname(__file__), "script.py"),
    ]

    # We run the script by injecting par values via a wrapper
    par = {
        "base_url": base_url,
        "token": token,
        "org": org,
        "output": output,
        "output_json": output_json,
    }

    script_path = os.path.join(os.path.dirname(__file__), "script.py")
    with open(script_path) as f:
        source = f.read()

    # Replace the VIASH START block with our par values
    import re
    par_json = json.dumps(par)
    source = re.sub(
        r"## VIASH START.*?## VIASH END",
        f"par = json.loads('''{par_json}''')",
        source,
        flags=re.DOTALL,
    )
    wrapper = source
    result = subprocess.run(
        [sys.executable, "-c", wrapper],
        capture_output=True,
        text=True,
        env=env,
        cwd=os.path.dirname(__file__) or ".",
    )
    return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_lists_all_orgs_and_workspaces():
    server, port = start_fake_server()
    try:
        base_url = f"http://127.0.0.1:{port}"
        output_md = "/tmp/test_ws_all.md"
        output_json = "/tmp/test_ws_all.json"

        result = run_script(base_url, output=output_md, output_json=output_json)
        assert result.returncode == 0, f"Script failed: {result.stderr}"

        with open(output_json) as f:
            data = json.load(f)

        # Should have both orgs
        org_names = [o["name"] for o in data["organizations"]]
        assert "AcmeCorp" in org_names
        assert "BetaLabs" in org_names

        # AcmeCorp should have 2 workspaces
        acme = next(o for o in data["organizations"] if o["name"] == "AcmeCorp")
        assert len(acme["workspaces"]) == 2
        ws_ids = [ws["id"] for ws in acme["workspaces"]]
        assert 1001 in ws_ids
        assert 1002 in ws_ids

        # BetaLabs should have 1 workspace
        beta = next(o for o in data["organizations"] if o["name"] == "BetaLabs")
        assert len(beta["workspaces"]) == 1
        assert beta["workspaces"][0]["id"] == 2001

        # Markdown should exist and contain workspace IDs
        with open(output_md) as f:
            md = f.read()
        assert "1001" in md
        assert "2001" in md
        assert "AcmeCorp" in md

        print("PASS: test_lists_all_orgs_and_workspaces")
    finally:
        server.shutdown()


def test_filters_by_org_name():
    server, port = start_fake_server()
    try:
        base_url = f"http://127.0.0.1:{port}"
        output_md = "/tmp/test_ws_filtered.md"
        output_json = "/tmp/test_ws_filtered.json"

        result = run_script(base_url, org="BetaLabs", output=output_md, output_json=output_json)
        assert result.returncode == 0, f"Script failed: {result.stderr}"

        with open(output_json) as f:
            data = json.load(f)

        # Should only have BetaLabs
        assert len(data["organizations"]) == 1
        assert data["organizations"][0]["name"] == "BetaLabs"
        assert data["organizations"][0]["workspaces"][0]["id"] == 2001

        print("PASS: test_filters_by_org_name")
    finally:
        server.shutdown()


def test_org_filter_no_match():
    server, port = start_fake_server()
    try:
        base_url = f"http://127.0.0.1:{port}"
        output_md = "/tmp/test_ws_nomatch.md"
        output_json = "/tmp/test_ws_nomatch.json"

        result = run_script(base_url, org="NonExistent", output=output_md, output_json=output_json)
        assert result.returncode == 1, "Should fail when org not found"
        assert "not found" in result.stderr.lower() or "no organization" in result.stderr.lower()

        print("PASS: test_org_filter_no_match")
    finally:
        server.shutdown()


def test_missing_token():
    server, port = start_fake_server()
    try:
        base_url = f"http://127.0.0.1:{port}"
        output_md = "/tmp/test_ws_notoken.md"
        output_json = "/tmp/test_ws_notoken.json"

        # Pass bad token to trigger auth failure
        result = run_script(base_url, token="wrong-token", output=output_md, output_json=output_json)
        assert result.returncode != 0, "Should fail with bad token"

        print("PASS: test_missing_token")
    finally:
        server.shutdown()


if __name__ == "__main__":
    test_lists_all_orgs_and_workspaces()
    test_filters_by_org_name()
    test_org_filter_no_match()
    test_missing_token()
    print("\nAll tests passed.")
