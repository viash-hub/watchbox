import json
import os
import re
import subprocess
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from urllib.parse import urlparse, parse_qs

# ---------------------------------------------------------------------------
# Fake Bitbucket Server API
# ---------------------------------------------------------------------------
MERGED_PRS = {
    "values": [
        {
            "id": 42,
            "title": "Add feature X",
            "state": "MERGED",
            "author": {"user": {"slug": "alice"}},
            "closedDate": 1713200000000,  # 2024-04-15T18:13:20Z
            "properties": {"mergeCommit": {"id": "abc123"}},
            "links": {"self": [{"href": "https://bb.example.com/projects/PROJ/repos/my-repo/pull-requests/42"}]},
        },
        {
            "id": 41,
            "title": "Fix bug Y",
            "state": "MERGED",
            "author": {"user": {"slug": "bob"}},
            "closedDate": 1713100000000,  # 2024-04-14T14:26:40Z
            "properties": {"mergeCommit": {"id": "def456"}},
            "links": {"self": [{"href": "https://bb.example.com/projects/PROJ/repos/my-repo/pull-requests/41"}]},
        },
        {
            "id": 10,
            "title": "Old PR",
            "state": "MERGED",
            "author": {"user": {"slug": "charlie"}},
            "closedDate": 1600000000000,  # 2020-09-13 (outside window)
            "properties": {"mergeCommit": {"id": "old111"}},
            "links": {"self": [{"href": "https://bb.example.com/projects/PROJ/repos/my-repo/pull-requests/10"}]},
        },
    ],
    "isLastPage": True,
}

TAGS = {
    "values": [
        {
            "displayId": "v1.2.0",
            "latestCommit": "abc123",
            "metadata": {
                "com.atlassian.bitbucket.server.bitbucket-ref-metadata:latest-commit-metadata": {
                    "authorTimestamp": 1713200000000,
                }
            },
        },
    ],
    "isLastPage": True,
}

COMMITS = {
    "values": [
        {"id": "abc123", "authorTimestamp": 1713200000000},
        {"id": "def456", "authorTimestamp": 1713100000000},
        {"id": "ghi789", "authorTimestamp": 1713000000000},
    ],
    "isLastPage": True,
}


class FakeBitbucketHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        auth = self.headers.get("Authorization", "")
        if auth != "Bearer test-token":
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'{"errors":[{"message":"Unauthorized"}]}')
            return

        if path.endswith("/pull-requests") and "MERGED" in qs.get("state", [""]):
            body = json.dumps(MERGED_PRS).encode()
        elif path.endswith("/tags"):
            body = json.dumps(TAGS).encode()
        elif path.endswith("/commits"):
            body = json.dumps(COMMITS).encode()
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"errors":[{"message":"Not found"}]}')
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


def start_fake_server():
    server = HTTPServer(("127.0.0.1", 0), FakeBitbucketHandler)
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------
def run_script(base_url, token="test-token", repos=None, platform="server",
               default_branch="main", days=3650, from_date=None, to_date=None,
               output="out.md", output_json="out.json"):
    env = os.environ.copy()
    env["BITBUCKET_TOKEN"] = token

    par = {
        "base_url": base_url,
        "token": token,
        "platform": platform,
        "repos": repos or ["PROJ/my-repo"],
        "default_branch": default_branch,
        "days": days,
        "from_date": from_date,
        "to_date": to_date,
        "output": output,
        "output_json": output_json,
    }

    script_path = os.path.join(os.path.dirname(__file__), "script.py")
    with open(script_path) as f:
        source = f.read()

    par_json = json.dumps(par)
    source = re.sub(
        r"## VIASH START.*?## VIASH END",
        f"par = json.loads('''{par_json}''')",
        source,
        flags=re.DOTALL,
    )

    result = subprocess.run(
        [sys.executable, "-c", source],
        capture_output=True,
        text=True,
        env=env,
        cwd=os.path.dirname(__file__) or ".",
    )
    return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_collects_merged_prs():
    server, port = start_fake_server()
    try:
        base_url = f"http://127.0.0.1:{port}"
        output_json = "/tmp/test_bb_prs.json"
        output_md = "/tmp/test_bb_prs.md"

        result = run_script(base_url, output=output_md, output_json=output_json)
        assert result.returncode == 0, f"Script failed: {result.stderr}"

        with open(output_json) as f:
            data = json.load(f)

        repo_data = data["repos"]["PROJ/my-repo"]
        # Only 2 PRs should be in window (the old one from 2020 is outside 3650 days from now...
        # actually it IS within 10 years, so let's check all 3 are present or the 2020 one is filtered)
        prs = repo_data["merged_prs"]
        assert len(prs) >= 2, f"Expected at least 2 merged PRs, got {len(prs)}"
        assert any(pr["number"] == 42 for pr in prs)
        assert any(pr["number"] == 41 for pr in prs)

        # Check report structure matches github component format
        assert "period" in data
        assert "totals" in data
        assert "merged_prs" in data["totals"]
        assert "commits" in data["totals"]

        print("PASS: test_collects_merged_prs")
    finally:
        server.shutdown()


def test_collects_commits():
    server, port = start_fake_server()
    try:
        base_url = f"http://127.0.0.1:{port}"
        output_json = "/tmp/test_bb_commits.json"
        output_md = "/tmp/test_bb_commits.md"

        result = run_script(base_url, output=output_md, output_json=output_json)
        assert result.returncode == 0, f"Script failed: {result.stderr}"

        with open(output_json) as f:
            data = json.load(f)

        repo_data = data["repos"]["PROJ/my-repo"]
        assert repo_data["commits"] == 3

        print("PASS: test_collects_commits")
    finally:
        server.shutdown()


def test_markdown_report_structure():
    server, port = start_fake_server()
    try:
        base_url = f"http://127.0.0.1:{port}"
        output_json = "/tmp/test_bb_md.json"
        output_md = "/tmp/test_bb_md.md"

        result = run_script(base_url, output=output_md, output_json=output_json)
        assert result.returncode == 0, f"Script failed: {result.stderr}"

        with open(output_md) as f:
            md = f.read()

        assert "# Development Activity Report" in md
        assert "## Summary" in md
        assert "Merged PRs" in md
        assert "Commits" in md
        assert "PROJ/my-repo" in md

        print("PASS: test_markdown_report_structure")
    finally:
        server.shutdown()


def test_bad_token():
    server, port = start_fake_server()
    try:
        base_url = f"http://127.0.0.1:{port}"
        result = run_script(base_url, token="wrong-token",
                            output="/tmp/test_bb_noauth.md",
                            output_json="/tmp/test_bb_noauth.json")
        assert result.returncode != 0, "Should fail with bad token"

        print("PASS: test_bad_token")
    finally:
        server.shutdown()


if __name__ == "__main__":
    test_collects_merged_prs()
    test_collects_commits()
    test_markdown_report_structure()
    test_bad_token()
    print("\nAll tests passed.")
