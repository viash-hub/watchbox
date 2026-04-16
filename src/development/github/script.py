import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

## VIASH START
par = {
    "token": None,
    "api_url": "https://api.github.com",
    "repos": ["viash-io/openpipeline"],
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
token = par["token"] or os.environ.get("GITHUB_TOKEN")
if not token:
    print("WARNING: No GitHub token provided. Rate limits will be strict.", file=sys.stderr)

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
api_url = par["api_url"].rstrip("/")
headers = {"Accept": "application/vnd.github+json"}
if token:
    headers["Authorization"] = f"Bearer {token}"


def api_get(path, params=None):
    url = f"{api_url}{path}"
    resp = requests.get(url, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def paginate(path, params=None, key=None):
    """Fetch all pages from a GitHub API endpoint."""
    params = dict(params or {})
    params.setdefault("per_page", 100)
    page = 1
    results = []
    while True:
        params["page"] = page
        data = api_get(path, params)
        items = data if isinstance(data, list) else data.get(key, [])
        if not items:
            break
        results.extend(items)
        if len(items) < params["per_page"]:
            break
        page += 1
    return results


def parse_dt(s):
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
    repo_data = {"merged_prs": [], "releases": [], "commits": 0}

    # --- Merged PRs ---
    prs = paginate(
        f"/repos/{repo}/pulls",
        params={
            "state": "closed",
            "sort": "updated",
            "direction": "desc",
        },
    )
    for pr in prs:
        merged_at = parse_dt(pr.get("merged_at"))
        if not merged_at:
            continue
        if merged_at < date_from:
            break
        if merged_at <= date_to:
            labels = [l["name"] for l in pr.get("labels", [])]
            pr_entry = {
                "number": pr["number"],
                "title": pr["title"],
                "author": pr.get("user", {}).get("login", "unknown"),
                "merged_at": merged_at.isoformat(),
                "labels": labels,
                "url": pr["html_url"],
            }
            repo_data["merged_prs"].append(pr_entry)
            all_prs.append({"repo": repo, **pr_entry})

    # --- Releases ---
    releases = api_get(f"/repos/{repo}/releases", params={"per_page": 20})
    for rel in releases:
        published = parse_dt(rel.get("published_at"))
        if not published:
            continue
        if published < date_from:
            break
        if published <= date_to:
            rel_entry = {
                "tag": rel["tag_name"],
                "name": rel.get("name", rel["tag_name"]),
                "published_at": published.isoformat(),
                "prerelease": rel.get("prerelease", False),
                "url": rel["html_url"],
            }
            repo_data["releases"].append(rel_entry)
            all_releases.append({"repo": repo, **rel_entry})

    # --- Commit count on default branch ---
    commits = paginate(
        f"/repos/{repo}/commits",
        params={
            "sha": par["default_branch"],
            "since": date_from.isoformat(),
            "until": date_to.isoformat(),
        },
    )
    repo_data["commits"] = len(commits)

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

# Releases
if all_releases:
    lines.append("## Releases")
    lines.append("")
    for rel in sorted(all_releases, key=lambda r: r["published_at"], reverse=True):
        pre = " (pre-release)" if rel["prerelease"] else ""
        lines.append(f"- **{rel['repo']}** [{rel['tag']}]({rel['url']}){pre} ({rel['published_at'][:10]})")
        if rel["name"] != rel["tag"]:
            lines.append(f"  {rel['name']}")
    lines.append("")

# Merged PRs
if all_prs:
    lines.append("## Merged Pull Requests")
    lines.append("")

    # Group by repo
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
            label_str = ""
            if pr["labels"]:
                label_str = " " + " ".join(f"`{l}`" for l in pr["labels"])
            lines.append(f"- [#{pr['number']}]({pr['url']}) {pr['title']} (@{pr['author']}){label_str}")
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
