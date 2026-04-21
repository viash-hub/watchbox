import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

## VIASH START
par = {
    "seqera_json": [],
    "development_json": [],
    "title": "WatchBox Report",
    "subtitle": None,
    "theme": "cosmo",
    "output": "report.html",
    "output_md": None,
    "output_qmd": None,
}
## VIASH END


# ---------------------------------------------------------------------------
# Load inputs
# ---------------------------------------------------------------------------
def as_list(val):
    if val is None:
        return []
    if isinstance(val, (list, tuple)):
        return list(val)
    return [val]


seqera_paths = as_list(par.get("seqera_json"))
dev_paths = as_list(par.get("development_json"))

if not seqera_paths and not dev_paths:
    print(
        "ERROR: No input JSON provided. Use --seqera_json and/or --development_json.",
        file=sys.stderr,
    )
    sys.exit(1)


def load_json(path):
    with open(path) as f:
        return json.load(f)


seqera_reports = [(Path(p), load_json(p)) for p in seqera_paths]
dev_reports = [(Path(p), load_json(p)) for p in dev_paths]


# ---------------------------------------------------------------------------
# Combined summary
# ---------------------------------------------------------------------------
combined = {
    "seqera_runs": sum(r["summary"]["total_runs"] for _, r in seqera_reports),
    "seqera_succeeded": sum(r["summary"]["succeeded"] for _, r in seqera_reports),
    "seqera_failed": sum(r["summary"]["failed"] for _, r in seqera_reports),
    "seqera_cancelled": sum(r["summary"].get("cancelled", 0) for _, r in seqera_reports),
    "merged_prs": sum(r["totals"]["merged_prs"] for _, r in dev_reports),
    "releases": sum(r["totals"]["releases"] for _, r in dev_reports),
    "commits": sum(r["totals"]["commits"] for _, r in dev_reports),
}
success_rate = (
    combined["seqera_succeeded"] / combined["seqera_runs"] * 100
    if combined["seqera_runs"]
    else None
)

periods = [r["period"] for _, r in seqera_reports + dev_reports]
if periods:
    period_from = min(p["from"] for p in periods)
    period_to = max(p["to"] for p in periods)
else:
    today = datetime.now(timezone.utc).date().isoformat()
    period_from = period_to = today

generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ---------------------------------------------------------------------------
# Render helpers
# ---------------------------------------------------------------------------
def yaml_escape(s):
    return str(s).replace('"', '\\"')


def md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        out.append("| " + " | ".join(str(c) for c in row) + " |")
    return out


want_md = bool(par.get("output_md"))


# ---------------------------------------------------------------------------
# Build .qmd document
# ---------------------------------------------------------------------------
lines = []
lines.append("---")
lines.append(f'title: "{yaml_escape(par["title"])}"')
if par.get("subtitle"):
    lines.append(f'subtitle: "{yaml_escape(par["subtitle"])}"')
lines.append(f'date: "{generated_at}"')
lines.append("format:")
lines.append("  html:")
lines.append("    toc: true")
lines.append("    toc-depth: 3")
lines.append("    toc-location: left")
lines.append("    number-sections: true")
lines.append(f"    theme: {par.get('theme') or 'cosmo'}")
lines.append("    code-fold: true")
lines.append("    embed-resources: true")
if want_md:
    lines.append("  gfm:")
    lines.append("    toc: true")
lines.append("---")
lines.append("")
lines.append(f"Report period: **{period_from}** to **{period_to}**.")
lines.append("")

# --- Executive summary ------------------------------------------------------
lines.append("# Executive summary")
lines.append("")
summary_rows = []
if seqera_reports:
    summary_rows.append(("Pipeline runs", combined["seqera_runs"]))
    sr = f"{success_rate:.1f}%" if success_rate is not None else "-"
    summary_rows.append(("Pipeline success rate", sr))
    summary_rows.append(("Pipeline failures", combined["seqera_failed"]))
    summary_rows.append(("Pipeline cancellations", combined["seqera_cancelled"]))
if dev_reports:
    summary_rows.append(("Merged pull requests", combined["merged_prs"]))
    summary_rows.append(("Releases / tags", combined["releases"]))
    summary_rows.append(("Commits", combined["commits"]))

lines.extend(md_table(["Metric", "Value"], summary_rows))
lines.append("")

# --- Seqera sections --------------------------------------------------------
if seqera_reports:
    lines.append("# Pipeline operations")
    lines.append("")
    for path, r in seqera_reports:
        label = path.stem
        lines.append(f"## {label}")
        lines.append("")
        lines.append(f"Period: {r['period']['from']} → {r['period']['to']}")
        lines.append("")

        s = r["summary"]
        lines.extend(
            md_table(
                ["Metric", "Value"],
                [
                    ("Total runs", s["total_runs"]),
                    ("Succeeded", s["succeeded"]),
                    ("Failed", s["failed"]),
                    ("Cancelled", s.get("cancelled", 0)),
                    ("Success rate", f"{s['success_rate_pct']}%"),
                ],
            )
        )
        lines.append("")

        pipelines = r.get("pipelines") or {}
        if pipelines:
            lines.append("### Pipelines")
            lines.append("")
            rows = []
            for name, ps in sorted(
                pipelines.items(), key=lambda x: x[1]["runs"], reverse=True
            ):
                dur = ps.get("avg_duration_min")
                dur_str = f"{dur}" if dur is not None else "-"
                rows.append(
                    (
                        name,
                        ps["runs"],
                        ps["succeeded"],
                        ps["failed"],
                        f"{ps['success_rate_pct']}%",
                        dur_str,
                    )
                )
            lines.extend(
                md_table(
                    ["Pipeline", "Runs", "Succeeded", "Failed", "Success rate",
                     "Avg duration (min)"],
                    rows,
                )
            )
            lines.append("")

        errors = r.get("errors") or []
        if errors:
            lines.append("### Recent failures")
            lines.append("")
            for err in errors[:10]:
                submitted = (err.get("submitted") or "")[:10] or "?"
                exit_str = (
                    f", exit {err['exit_status']}"
                    if err.get("exit_status") is not None
                    else ""
                )
                heading = (
                    f"{err.get('run_name') or '?'} "
                    f"({err.get('pipeline') or '?'}, {submitted}{exit_str})"
                )
                lines.append(f"#### {heading}")
                lines.append("")
                if err.get("id"):
                    lines.append(f"Run ID: `{err['id']}`")
                    lines.append("")
                report = (err.get("error_report") or "").strip()
                if report:
                    lines.append("```")
                    lines.append(report[:2000])
                    lines.append("```")
                    lines.append("")

# --- Development sections ---------------------------------------------------
if dev_reports:
    lines.append("# Development activity")
    lines.append("")
    for path, r in dev_reports:
        label = path.stem
        lines.append(f"## {label}")
        lines.append("")
        lines.append(f"Period: {r['period']['from']} → {r['period']['to']}")
        lines.append("")

        t = r["totals"]
        lines.extend(
            md_table(
                ["Metric", "Value"],
                [
                    ("Merged PRs", t["merged_prs"]),
                    ("Releases", t["releases"]),
                    ("Commits", t["commits"]),
                ],
            )
        )
        lines.append("")

        repos = r.get("repos") or {}
        if repos:
            lines.append("### Per-repository activity")
            lines.append("")
            rows = []
            for repo_name, rd in repos.items():
                rows.append(
                    (
                        repo_name,
                        rd.get("commits", 0),
                        len(rd.get("merged_prs", []) or []),
                        len(rd.get("releases", []) or []),
                    )
                )
            lines.extend(
                md_table(
                    ["Repository", "Commits", "Merged PRs", "Releases"], rows
                )
            )
            lines.append("")

        # Releases
        all_rels = []
        for repo_name, rd in repos.items():
            for rel in rd.get("releases", []) or []:
                all_rels.append({**rel, "repo": repo_name})
        if all_rels:
            lines.append("### Releases")
            lines.append("")
            for rel in sorted(
                all_rels, key=lambda x: x.get("published_at") or "", reverse=True
            ):
                pre = " (pre-release)" if rel.get("prerelease") else ""
                pub = (rel.get("published_at") or "")[:10]
                tag = rel.get("tag") or rel.get("name") or "?"
                if rel.get("url"):
                    lines.append(
                        f"- **{rel['repo']}** [{tag}]({rel['url']}){pre} ({pub})"
                    )
                else:
                    lines.append(f"- **{rel['repo']}** {tag}{pre} ({pub})")
            lines.append("")

        # PRs
        all_prs = []
        for repo_name, rd in repos.items():
            for pr in rd.get("merged_prs", []) or []:
                all_prs.append({**pr, "repo": repo_name})
        if all_prs:
            lines.append("### Merged pull requests")
            lines.append("")
            prs_by_repo = {}
            for pr in all_prs:
                prs_by_repo.setdefault(pr["repo"], []).append(pr)
            for repo_name, prs in prs_by_repo.items():
                lines.append(f"#### {repo_name}")
                lines.append("")
                for pr in sorted(
                    prs, key=lambda x: x.get("merged_at") or "", reverse=True
                ):
                    labels = pr.get("labels") or []
                    label_str = (
                        " " + " ".join(f"`{l}`" for l in labels) if labels else ""
                    )
                    author = pr.get("author") or "unknown"
                    title = pr.get("title") or ""
                    number = pr.get("number", "?")
                    if pr.get("url"):
                        lines.append(
                            f"- [#{number}]({pr['url']}) {title} "
                            f"(@{author}){label_str}"
                        )
                    else:
                        lines.append(
                            f"- #{number} {title} (@{author}){label_str}"
                        )
                lines.append("")

qmd_content = "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Save intermediate qmd if requested
# ---------------------------------------------------------------------------
if par.get("output_qmd"):
    Path(par["output_qmd"]).write_text(qmd_content)
    print(f"QMD source written to {par['output_qmd']}")


# ---------------------------------------------------------------------------
# Render via quarto
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    workdir = Path(td)
    qmd_path = workdir / "report.qmd"
    qmd_path.write_text(qmd_content)

    print("Rendering report via quarto ...")
    try:
        subprocess.run(
            ["quarto", "render", "report.qmd"],
            cwd=workdir,
            check=True,
        )
    except FileNotFoundError:
        print(
            "ERROR: quarto CLI not found. Install quarto or run inside the "
            "component's docker image.",
            file=sys.stderr,
        )
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"ERROR: quarto render failed with exit code {e.returncode}",
              file=sys.stderr)
        sys.exit(1)

    html_out = workdir / "report.html"
    if not html_out.exists():
        print(f"ERROR: Expected HTML output not found at {html_out}",
              file=sys.stderr)
        sys.exit(1)
    shutil.copy(html_out, par["output"])
    print(f"HTML report written to {par['output']}")

    if want_md:
        md_out = workdir / "report.md"
        if not md_out.exists():
            print(f"ERROR: Expected Markdown output not found at {md_out}",
                  file=sys.stderr)
            sys.exit(1)
        shutil.copy(md_out, par["output_md"])
        print(f"Markdown report written to {par['output_md']}")
