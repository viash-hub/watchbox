import json
import os
import sys

import requests

## VIASH START
par = {
    "base_url": "https://api.cloud.seqera.io",
    "token": None,
    "org": None,
    "output": "seqera_workspaces.md",
    "output_json": "seqera_workspaces.json",
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
# API helpers
# ---------------------------------------------------------------------------
base_url = par["base_url"].rstrip("/")
headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/json",
}


def api_get(path):
    url = f"{base_url}{path}"
    resp = requests.get(url, headers=headers, timeout=30)
    if not resp.ok:
        print(f"ERROR: API returned HTTP {resp.status_code} for {resp.url}", file=sys.stderr)
        try:
            detail = resp.json().get("message", resp.text[:500])
        except Exception:
            detail = resp.text[:500]
        print(f"  Detail: {detail}", file=sys.stderr)
        resp.raise_for_status()
    if not resp.content:
        print(f"ERROR: Empty response from {resp.url} (HTTP {resp.status_code})", file=sys.stderr)
        sys.exit(1)
    try:
        return resp.json()
    except requests.exceptions.JSONDecodeError:
        print(f"ERROR: Non-JSON response from {resp.url} (HTTP {resp.status_code})", file=sys.stderr)
        print(f"  Content-Type: {resp.headers.get('Content-Type', 'unknown')}", file=sys.stderr)
        print(f"  Body (first 500 chars): {resp.text[:500]}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Fetch organizations
# ---------------------------------------------------------------------------
print("Fetching organizations ...")
data = api_get("/orgs")
orgs = data.get("organizations", [])

if par["org"]:
    orgs = [o for o in orgs if o["name"] == par["org"]]
    if not orgs:
        print(f"ERROR: No organization named '{par['org']}' found.", file=sys.stderr)
        sys.exit(1)

print(f"Found {len(orgs)} organization(s).")

# ---------------------------------------------------------------------------
# Fetch workspaces per organization
# ---------------------------------------------------------------------------
result_orgs = []

for org in orgs:
    org_id = org["orgId"]
    org_name = org["name"]
    print(f"Fetching workspaces for {org_name} (ID: {org_id}) ...")
    ws_data = api_get(f"/orgs/{org_id}/workspaces")
    workspaces = ws_data.get("workspaces", [])
    result_orgs.append({
        "name": org_name,
        "id": org_id,
        "workspaces": [
            {
                "name": ws["name"],
                "full_name": ws.get("fullName", ws["name"]),
                "id": ws["id"],
                "visibility": ws.get("visibility", "UNKNOWN"),
            }
            for ws in workspaces
        ],
    })

# ---------------------------------------------------------------------------
# Write JSON output
# ---------------------------------------------------------------------------
report_data = {"organizations": result_orgs}

if par["output_json"]:
    with open(par["output_json"], "w") as f:
        json.dump(report_data, f, indent=2)
    print(f"JSON output written to {par['output_json']}")

# ---------------------------------------------------------------------------
# Write Markdown report
# ---------------------------------------------------------------------------
lines = []
lines.append("# Seqera Platform: Organizations and Workspaces")
lines.append("")

if not result_orgs:
    lines.append("No organizations found.")
else:
    lines.append("| Organization | Org ID | Workspace | Workspace ID | Visibility |")
    lines.append("|--------------|--------|-----------|--------------|------------|")
    for org in result_orgs:
        if not org["workspaces"]:
            lines.append(f"| {org['name']} | {org['id']} | (none) | - | - |")
        else:
            for ws in org["workspaces"]:
                lines.append(f"| {org['name']} | {org['id']} | {ws['name']} | {ws['id']} | {ws['visibility']} |")
    lines.append("")

with open(par["output"], "w") as f:
    f.write("\n".join(lines) + "\n")

print(f"Markdown report written to {par['output']}")
