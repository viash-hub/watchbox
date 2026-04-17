import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

import requests

## VIASH START
par = {
    "base_url": "https://seqera.example.com/api",
    "token": None,
    "workspace_id": "12345",
    "days": 7,
    "from_date": None,
    "to_date": None,
    "output": "seqera_report.md",
    "output_json": "seqera_report.json",
}
## VIASH END

# ---------------------------------------------------------------------------
# Resolve token
# ---------------------------------------------------------------------------
token = par["token"] or os.environ.get("TOWER_ACCESS_TOKEN")
if not token:
    print("ERROR: No API token provided. Use --token or set TOWER_ACCESS_TOKEN.", file=sys.stderr)
    sys.exit(1)

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
workspace_id = par["workspace_id"]
headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/json",
}


def api_get(path, params=None):
    url = f"{base_url}{path}"
    resp = requests.get(url, headers=headers, params=params, timeout=30)
    if not resp.ok:
        print(f"ERROR: API returned HTTP {resp.status_code} for {resp.url}", file=sys.stderr)
        try:
            detail = resp.json().get("message", resp.text[:500])
        except Exception:
            detail = resp.text[:500]
        print(f"  Detail: {detail}", file=sys.stderr)
        resp.raise_for_status()
    if not resp.content:
        print(f"ERROR: Empty response from {resp.request.method} {resp.url} (HTTP {resp.status_code})", file=sys.stderr)
        sys.exit(1)
    try:
        return resp.json()
    except requests.exceptions.JSONDecodeError:
        print(f"ERROR: Non-JSON response from {resp.url} (HTTP {resp.status_code})", file=sys.stderr)
        print(f"  Content-Type: {resp.headers.get('Content-Type', 'unknown')}", file=sys.stderr)
        print(f"  Body (first 500 chars): {resp.text[:500]}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Fetch workflow runs
# ---------------------------------------------------------------------------
print(f"Fetching workflows from {date_from.date()} to {date_to.date()} ...")

workflows = []
offset = 0
page_size = 50

while True:
    data = api_get(
        "/workflow",
        params={
            "workspaceId": workspace_id,
            "max": page_size,
            "offset": offset,
            "search": "",
        },
    )
    batch = data.get("workflows", [])
    if not batch:
        break

    # Workflows returned newest-first; stop once we pass date_from.
    reached_cutoff = False
    for entry in batch:
        wf = entry.get("workflow", entry)
        submitted = wf.get("submit")
        if not submitted:
            continue
        submit_dt = datetime.fromisoformat(submitted.replace("Z", "+00:00"))
        if submit_dt < date_from:
            reached_cutoff = True
            break
        if submit_dt <= date_to:
            workflows.append(wf)

    if reached_cutoff or len(batch) < page_size:
        break
    offset += page_size

print(f"Found {len(workflows)} workflow run(s) in the time window.")

# ---------------------------------------------------------------------------
# Analyse runs
# ---------------------------------------------------------------------------
status_counts = Counter()
pipeline_stats = {}
errors = []

for wf in workflows:
    status = wf.get("status", "UNKNOWN")
    status_counts[status] += 1

    pipeline = wf.get("projectName") or wf.get("runName") or "unknown"
    if pipeline not in pipeline_stats:
        pipeline_stats[pipeline] = {
            "runs": 0,
            "succeeded": 0,
            "failed": 0,
            "cancelled": 0,
            "other": 0,
            "durations_min": [],
        }
    stats = pipeline_stats[pipeline]
    stats["runs"] += 1

    if status == "SUCCEEDED":
        stats["succeeded"] += 1
    elif status == "FAILED":
        stats["failed"] += 1
        error_report = wf.get("errorReport") or wf.get("errorMessage") or "No error details"
        errors.append({
            "id": wf.get("id", ""),
            "run_name": wf.get("runName", ""),
            "pipeline": pipeline,
            "error_message": wf.get("errorMessage") or "",
            "error_report": error_report,
            "exit_status": wf.get("exitStatus"),
            "submitted": wf.get("submit", ""),
            "command_line": wf.get("commandLine") or "",
        })
    elif status == "CANCELLED":
        stats["cancelled"] += 1
    else:
        stats["other"] += 1

    duration = wf.get("duration")
    if duration and isinstance(duration, (int, float)) and duration > 0:
        stats["durations_min"].append(duration / 60000.0)


def fmt_duration(minutes):
    if minutes < 60:
        return f"{minutes:.0f}m"
    hours = minutes / 60
    return f"{hours:.1f}h"


# ---------------------------------------------------------------------------
# Build report data
# ---------------------------------------------------------------------------
total_runs = len(workflows)
total_succeeded = status_counts.get("SUCCEEDED", 0)
total_failed = status_counts.get("FAILED", 0)
success_rate = (total_succeeded / total_runs * 100) if total_runs > 0 else 0

report_data = {
    "period": {
        "from": date_from.date().isoformat(),
        "to": date_to.date().isoformat(),
    },
    "summary": {
        "total_runs": total_runs,
        "succeeded": total_succeeded,
        "failed": total_failed,
        "cancelled": status_counts.get("CANCELLED", 0),
        "other": sum(v for k, v in status_counts.items() if k not in ("SUCCEEDED", "FAILED", "CANCELLED")),
        "success_rate_pct": round(success_rate, 1),
    },
    "pipelines": {},
    "errors": errors[:20],
}

for name, stats in sorted(pipeline_stats.items()):
    sr = (stats["succeeded"] / stats["runs"] * 100) if stats["runs"] > 0 else 0
    durations = stats["durations_min"]
    avg_dur = sum(durations) / len(durations) if durations else None
    report_data["pipelines"][name] = {
        "runs": stats["runs"],
        "succeeded": stats["succeeded"],
        "failed": stats["failed"],
        "cancelled": stats["cancelled"],
        "success_rate_pct": round(sr, 1),
        "avg_duration_min": round(avg_dur, 1) if avg_dur else None,
    }

# ---------------------------------------------------------------------------
# Write JSON output
# ---------------------------------------------------------------------------
if par["output_json"]:
    with open(par["output_json"], "w") as f:
        json.dump(report_data, f, indent=2)
    print(f"JSON report written to {par['output_json']}")

# ---------------------------------------------------------------------------
# Write Markdown report
# ---------------------------------------------------------------------------
lines = []
lines.append(f"# Seqera Platform Report")
lines.append(f"")
lines.append(f"Period: **{report_data['period']['from']}** to **{report_data['period']['to']}**")
lines.append(f"")

# Summary
s = report_data["summary"]
lines.append(f"## Summary")
lines.append(f"")
lines.append(f"| Metric | Value |")
lines.append(f"|--------|-------|")
lines.append(f"| Total runs | {s['total_runs']} |")
lines.append(f"| Succeeded | {s['succeeded']} |")
lines.append(f"| Failed | {s['failed']} |")
lines.append(f"| Cancelled | {s['cancelled']} |")
lines.append(f"| Success rate | {s['success_rate_pct']}% |")
lines.append(f"")

# Per-pipeline breakdown
if report_data["pipelines"]:
    lines.append(f"## Pipeline Breakdown")
    lines.append(f"")
    lines.append(f"| Pipeline | Runs | Succeeded | Failed | Success Rate | Avg Duration |")
    lines.append(f"|----------|------|-----------|--------|--------------|--------------|")
    for name, ps in sorted(report_data["pipelines"].items(), key=lambda x: x[1]["runs"], reverse=True):
        dur_str = fmt_duration(ps["avg_duration_min"]) if ps["avg_duration_min"] else "-"
        lines.append(f"| {name} | {ps['runs']} | {ps['succeeded']} | {ps['failed']} | {ps['success_rate_pct']}% | {dur_str} |")
    lines.append(f"")

# Errors
if errors:
    lines.append(f"## Recent Failures")
    lines.append(f"")
    for err in errors[:10]:
        date_str = err["submitted"][:10] if err["submitted"] else "?"
        exit_str = f", exit {err['exit_status']}" if err["exit_status"] is not None else ""
        lines.append(f"### {err['run_name']} ({err['pipeline']}, {date_str}{exit_str})")
        lines.append(f"")
        if err["id"]:
            lines.append(f"Run ID: `{err['id']}`")
            lines.append(f"")
        report = err["error_report"].strip()
        if report:
            lines.append(f"```")
            lines.append(report[:2000])
            lines.append(f"```")
            lines.append(f"")
    lines.append(f"")

with open(par["output"], "w") as f:
    f.write("\n".join(lines) + "\n")

print(f"Markdown report written to {par['output']}")
