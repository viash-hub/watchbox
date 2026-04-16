# WatchBox

Platform operations reporting components for [Viash Hub](https://github.com/viash-hub/watchbox). Collects pipeline execution stats, development activity, and operational metrics from various services and produces structured reports.

## Components

### `operations/seqera_workspaces`

Lists organizations and workspaces from a Seqera Platform instance with their numeric IDs. Use this to discover the workspace ID required by the `seqera` component.

The Seqera Platform UI uses workspace names in URLs (e.g. `/orgs/MyOrg/workspaces/Demo/launchpad`), but the API requires numeric IDs. This component bridges that gap.

**Authentication:** Provide a token via `--token` or set the `TOWER_ACCESS_TOKEN` environment variable.

```bash
# List all organizations and workspaces
target/executable/operations/seqera_workspaces/seqera_workspaces \
  --base_url https://api.cloud.seqera.io

# Filter to a specific organization
target/executable/operations/seqera_workspaces/seqera_workspaces \
  --base_url https://api.cloud.seqera.io \
  --org MyOrg
```

Output (markdown table and JSON):

```
| Organization | Org ID          | Workspace | Workspace ID   | Visibility |
|--------------|-----------------|-----------|----------------|------------|
| MyOrg        | 229986376311324 | Demo      | 20807160317427 | PRIVATE    |
```

### `operations/seqera`

Queries a Seqera Platform instance for pipeline execution statistics over a given time window. Produces a report with run counts, success/failure rates, durations, per-pipeline breakdowns, and detailed error reports for failed runs.

**Authentication:** Provide a token via `--token` or set the `TOWER_ACCESS_TOKEN` environment variable.

The `--workspace_id` parameter requires the numeric workspace ID (not the name). Use the `seqera_workspaces` component to find it.

```bash
# Report for the last 7 days (default)
target/executable/operations/seqera/seqera \
  --base_url https://api.cloud.seqera.io \
  --workspace_id 20807160317427

# Report for the last 30 days
target/executable/operations/seqera/seqera \
  --base_url https://api.cloud.seqera.io \
  --workspace_id 20807160317427 \
  --days 30

# Report for a specific date range
target/executable/operations/seqera/seqera \
  --base_url https://api.cloud.seqera.io \
  --workspace_id 20807160317427 \
  --from_date 2025-01-01 \
  --to_date 2025-03-31
```

Outputs `seqera_report.md` and `seqera_report.json` containing:

- Summary table (total runs, succeeded, failed, cancelled, success rate)
- Per-pipeline breakdown with success rates and average durations
- Detailed failure reports with error output, run IDs, and exit statuses

### `development/github`

Queries GitHub for development activity over a given time window. Collects merged pull requests, releases/tags, and commit activity for a set of repositories.

**Authentication:** Provide a token via `--token` or set the `GITHUB_TOKEN` environment variable.

```bash
# Activity for one repo over the last 7 days
target/executable/development/github/github \
  --repos viash-io/viash

# Activity for multiple repos over the last 30 days
target/executable/development/github/github \
  --repos viash-io/viash viash-io/openpipeline \
  --days 30

# Custom date range and GitHub Enterprise
target/executable/development/github/github \
  --repos myorg/myrepo \
  --api_url https://github.example.com/api/v3 \
  --from_date 2025-01-01 \
  --to_date 2025-03-31
```

Outputs `development_report.md` and `development_report.json`.

### `development/bitbucket`

Queries a Bitbucket instance for development activity over a given time window. Collects merged pull requests, tags, and commit activity for a set of repositories. Supports both Bitbucket Cloud and Bitbucket Data Center / Server.

**Authentication:** Provide a token via `--token` or set the `BITBUCKET_TOKEN` environment variable.

```bash
# Bitbucket Data Center / Server (default)
target/executable/development/bitbucket/bitbucket \
  --base_url https://bitbucket.example.com/rest/api/1.0 \
  --repos PROJ/my-repo

# Multiple repos over the last 30 days
target/executable/development/bitbucket/bitbucket \
  --base_url https://bitbucket.example.com/rest/api/1.0 \
  --repos PROJ/repo-a PROJ/repo-b \
  --days 30

# Bitbucket Cloud
target/executable/development/bitbucket/bitbucket \
  --base_url https://api.bitbucket.org/2.0 \
  --platform cloud \
  --repos myteam/my-repo

# Custom date range
target/executable/development/bitbucket/bitbucket \
  --base_url https://bitbucket.example.com/rest/api/1.0 \
  --repos PROJ/my-repo \
  --from_date 2025-01-01 \
  --to_date 2025-03-31
```

Outputs `development_report.md` and `development_report.json` in the same format as the github component.
