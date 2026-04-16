import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

## VIASH START
par = {
    "base_url": "https://bitbucket.example.com/rest/api/1.0",
    "token": None,
    "platform": "server",
    "repos": ["PROJ/my-repo"],
    "default_branch": "main",
    "days": 7,
    "from_date": None,
    "to_date": None,
    "output": "development_report.md",
    "output_json": "development_report.json",
}
## VIASH END

# ---------------------------------------------------------------------------
# Resolve token
# ---------------------------------------------------------------------------
token = par["token"] or os.environ.get("BITBUCKET_TOKEN")
if not token:
    print("WARNING: No Bitbucket token provided. Authentication may fail.", file=sys.stderr)

# ---------------------------------------------------------------------------
# Resolve time window
# ---------------------------------------------------------------------------
if par["from_date"]:
    date_from = datetime.fromisoformat(par["from_date"]).replace(tzinfo=timezone.utc)
else:
    date_from = datetime.now(timezone.utc) - timedelta(days=par["days"])

if par["to_date"]:
    date_to = datetime.fromisoformat(par["to_date"]).replace(tzinfo=timezone.utc)
else:
    date_to = datetime.now(timezone.utc)

# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------
base_url = par["base_url"].rstrip("/")
platform = par["platform"]
headers = {"Accept": "application/json"}
if token:
    headers["Authorization"] = f"Bearer {token}"


def api_get(url, params=None):
    resp = requests.get(url, headers=headers, params=params, timeout=30)
    if not resp.ok:
        print(f"ERROR: API returned HTTP {resp.status_code} for {resp.url}", file=sys.stderr)
        try:
            detail = resp.json()
            msg = detail.get("errors", [{}])[0].get("message", resp.text[:500])
        except Exception:
            msg = resp.text[:500]
        print(f"  Detail: {msg}", file=sys.stderr)
        resp.raise_for_status()
    return resp.json()


def paginate_server(path, params=None):
    """Paginate a Bitbucket Server / Data Center API endpoint."""
    params = dict(params or {})
    params.setdefault("limit", 100)
    start = 0
    results = []
    while True:
        params["start"] = start
        data = api_get(f"{base_url}{path}", params)
        values = data.get("values", [])
        results.extend(values)
        if data.get("isLastPage", True):
            break
        start = data.get("nextPageStart", start + len(values))
    return results


def paginate_cloud(path, params=None):
    """Paginate a Bitbucket Cloud API endpoint."""
    params = dict(params or {})
    params.setdefault("pagelen", 100)
    url = f"{base_url}{path}"
    results = []
    while url:
        data = api_get(url, params)
        results.extend(data.get("values", []))
        url = data.get("next")
        params = None  # next URL includes query params
    return results


def paginate(path, params=None):
    if platform == "cloud":
        return paginate_cloud(path, params)
    return paginate_server(path, params)


def ts_to_dt(ms):
    """Convert a millisecond timestamp to a datetime."""
    if not ms:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def parse_iso(s):
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# Collect data per repo
# ---------------------------------------------------------------------------
repos = par["repos"]
if isinstance(repos, str):
    repos = [repos]

report_data = {
    "period": {
        "from": date_from.date().isoformat(),
        "to": date_to.date().isoformat(),
    },
    "repos": {},
    "totals": {
        "merged_prs": 0,
        "releases": 0,
        "commits": 0,
    },
}

all_prs = []
all_releases = []

for repo in repos:
    print(f"Querying {repo} ...")
    parts = repo.split("/", 1)
    if len(parts) != 2:
        print(f"ERROR: Invalid repo format '{repo}'. Expected project/repo.", file=sys.stderr)
        sys.exit(1)
    project, slug = parts

    repo_data = {"merged_prs": [], "releases": [], "commits": 0}

    # --- Merged PRs ---
    if platform == "cloud":
        pr_path = f"/repositories/{project}/{slug}/pullrequests"
        pr_params = {"state": "MERGED", "sort": "-updated_on"}
    else:
        pr_path = f"/projects/{project}/repos/{slug}/pull-requests"
        pr_params = {"state": "MERGED", "order": "NEWEST"}

    prs = paginate(pr_path, pr_params)

    for pr in prs:
        if platform == "cloud":
            merged_at = parse_iso(pr.get("updated_on"))
            pr_number = pr.get("id", 0)
            pr_title = pr.get("title", "")
            pr_author = pr.get("author", {}).get("display_name", "unknown")
            pr_url = pr.get("links", {}).get("html", {}).get("href", "")
        else:
            closed_date = pr.get("closedDate")
            merged_at = ts_to_dt(closed_date)
            pr_number = pr.get("id", 0)
            pr_title = pr.get("title", "")
            pr_author = pr.get("author", {}).get("user", {}).get("slug", "unknown")
            self_links = pr.get("links", {}).get("self", [])
            pr_url = self_links[0]["href"] if self_links else ""

        if not merged_at:
            continue
        if merged_at < date_from:
            break
        if merged_at <= date_to:
            pr_entry = {
                "number": pr_number,
                "title": pr_title,
                "author": pr_author,
                "merged_at": merged_at.isoformat(),
                "labels": [],
                "url": pr_url,
            }
            repo_data["merged_prs"].append(pr_entry)
            all_prs.append({"repo": repo, **pr_entry})

    # --- Tags (as releases) ---
    if platform == "cloud":
        tag_path = f"/repositories/{project}/{slug}/refs/tags"
    else:
        tag_path = f"/projects/{project}/repos/{slug}/tags"

    tags = paginate(tag_path)

    for tag in tags:
        if platform == "cloud":
            tag_name = tag.get("name", "")
            tag_date = parse_iso(tag.get("date"))
            tag_url = tag.get("links", {}).get("html", {}).get("href", "")
        else:
            tag_name = tag.get("displayId", "")
            metadata = tag.get("metadata", {})
            commit_meta = metadata.get(
                "com.atlassian.bitbucket.server.bitbucket-ref-metadata:latest-commit-metadata", {}
            )
            tag_date = ts_to_dt(commit_meta.get("authorTimestamp"))
            tag_url = ""

        if not tag_date:
            continue
        if tag_date < date_from:
            continue
        if tag_date <= date_to:
            rel_entry = {
                "tag": tag_name,
                "name": tag_name,
                "published_at": tag_date.isoformat(),
                "prerelease": False,
                "url": tag_url,
            }
            repo_data["releases"].append(rel_entry)
            all_releases.append({"repo": repo, **rel_entry})

    # --- Commits on default branch ---
    if platform == "cloud":
        commit_path = f"/repositories/{project}/{slug}/commits"
    else:
        commit_path = f"/projects/{project}/repos/{slug}/commits"

    commits = paginate(commit_path)

    count = 0
    for commit in commits:
        if platform == "cloud":
            commit_date = parse_iso(commit.get("date"))
        else:
            commit_date = ts_to_dt(commit.get("authorTimestamp"))
        if not commit_date:
            continue
        if commit_date < date_from:
            break
        if commit_date <= date_to:
            count += 1

    repo_data["commits"] = count

    report_data["repos"][repo] = repo_data
    report_data["totals"]["merged_prs"] += len(repo_data["merged_prs"])
    report_data["totals"]["releases"] += len(repo_data["releases"])
    report_data["totals"]["commits"] += repo_data["commits"]

# ---------------------------------------------------------------------------
# Write JSON output
# ---------------------------------------------------------------------------
if par["output_json"]:
    with open(par["output_json"], "w") as f:
        json.dump(report_data, f, indent=2, default=str)
    print(f"JSON report written to {par['output_json']}")

# ---------------------------------------------------------------------------
# Write Markdown report
# ---------------------------------------------------------------------------
lines = []
lines.append("# Development Activity Report")
lines.append("")
lines.append(f"Period: **{report_data['period']['from']}** to **{report_data['period']['to']}**")
lines.append(f"Repositories: {', '.join(repos)}")
lines.append("")

# Summary
t = report_data["totals"]
lines.append("## Summary")
lines.append("")
lines.append("| Metric | Value |")
lines.append("|--------|-------|")
lines.append(f"| Merged PRs | {t['merged_prs']} |")
lines.append(f"| Releases | {t['releases']} |")
lines.append(f"| Commits | {t['commits']} |")
lines.append("")

# Releases / tags
if all_releases:
    lines.append("## Releases")
    lines.append("")
    for rel in sorted(all_releases, key=lambda r: r["published_at"], reverse=True):
        pre = " (pre-release)" if rel["prerelease"] else ""
        if rel["url"]:
            lines.append(f"- **{rel['repo']}** [{rel['tag']}]({rel['url']}){pre} ({rel['published_at'][:10]})")
        else:
            lines.append(f"- **{rel['repo']}** {rel['tag']}{pre} ({rel['published_at'][:10]})")
        if rel["name"] != rel["tag"]:
            lines.append(f"  {rel['name']}")
    lines.append("")

# Merged PRs
if all_prs:
    lines.append("## Merged Pull Requests")
    lines.append("")

    prs_by_repo = {}
    for pr in all_prs:
        prs_by_repo.setdefault(pr["repo"], []).append(pr)

    for repo in repos:
        repo_prs = prs_by_repo.get(repo, [])
        if not repo_prs:
            continue
        lines.append(f"### {repo}")
        lines.append("")
        for pr in sorted(repo_prs, key=lambda p: p["merged_at"], reverse=True):
            if pr["url"]:
                lines.append(f"- [#{pr['number']}]({pr['url']}) {pr['title']} (@{pr['author']})")
            else:
                lines.append(f"- #{pr['number']} {pr['title']} (@{pr['author']})")
        lines.append("")

# Per-repo commit activity
lines.append("## Commit Activity")
lines.append("")
lines.append("| Repository | Commits |")
lines.append("|------------|---------|")
for repo in repos:
    rd = report_data["repos"].get(repo, {})
    lines.append(f"| {repo} | {rd.get('commits', 0)} |")
lines.append("")

with open(par["output"], "w") as f:
    f.write("\n".join(lines) + "\n")

print(f"Markdown report written to {par['output']}")
