import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


# ---------------------------------------------------------------------------
# Dummy input payloads
# ---------------------------------------------------------------------------
DUMMY_SEQERA = {
    "period": {"from": "2026-04-14", "to": "2026-04-21"},
    "summary": {
        "total_runs": 5,
        "succeeded": 3,
        "failed": 1,
        "cancelled": 1,
        "other": 0,
        "success_rate_pct": 60.0,
    },
    "pipelines": {
        "nf-core/rnaseq": {
            "runs": 3,
            "succeeded": 2,
            "failed": 1,
            "cancelled": 0,
            "success_rate_pct": 66.7,
            "avg_duration_min": 42.5,
        },
        "nf-core/sarek": {
            "runs": 2,
            "succeeded": 1,
            "failed": 0,
            "cancelled": 1,
            "success_rate_pct": 50.0,
            "avg_duration_min": 120.0,
        },
    },
    "errors": [
        {
            "id": "wf-abc",
            "run_name": "angry_einstein",
            "pipeline": "nf-core/rnaseq",
            "error_message": "Pipeline failed at step X",
            "error_report": "java.lang.RuntimeException: boom",
            "exit_status": 1,
            "submitted": "2026-04-20T10:00:00Z",
            "command_line": "nextflow run ...",
        }
    ],
}

DUMMY_DEV = {
    "period": {"from": "2026-04-14", "to": "2026-04-21"},
    "repos": {
        "viash-io/viash": {
            "merged_prs": [
                {
                    "number": 42,
                    "title": "Add feature X",
                    "author": "alice",
                    "merged_at": "2026-04-20T12:00:00+00:00",
                    "labels": ["enhancement"],
                    "url": "https://github.com/viash-io/viash/pull/42",
                },
                {
                    "number": 41,
                    "title": "Fix bug Y",
                    "author": "bob",
                    "merged_at": "2026-04-18T09:30:00+00:00",
                    "labels": ["bug"],
                    "url": "https://github.com/viash-io/viash/pull/41",
                },
            ],
            "releases": [
                {
                    "tag": "v1.2.3",
                    "name": "v1.2.3",
                    "published_at": "2026-04-19T00:00:00+00:00",
                    "prerelease": False,
                    "url": "https://github.com/viash-io/viash/releases/tag/v1.2.3",
                }
            ],
            "commits": 12,
        }
    },
    "totals": {"merged_prs": 2, "releases": 1, "commits": 12},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def component_executable():
    """Path to the viash-built component wrapper."""
    exe = None
    try:
        exe = meta["executable"]  # noqa: F821  -- injected by viash
    except NameError:
        exe = os.environ.get("VIASH_META_EXECUTABLE")
    if not exe:
        raise RuntimeError(
            "No component executable found. This test must be run via "
            "`viash test`, which injects meta['executable']."
        )
    return exe


def run_component(args):
    return subprocess.run(
        [component_executable(), *args],
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_full_report():
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        seqera_in = tdp / "seqera.json"
        dev_in = tdp / "dev.json"
        seqera_in.write_text(json.dumps(DUMMY_SEQERA))
        dev_in.write_text(json.dumps(DUMMY_DEV))

        out_html = tdp / "out.html"
        out_md = tdp / "out.md"
        out_qmd = tdp / "out.qmd"

        result = run_component([
            "--seqera_json", str(seqera_in),
            "--development_json", str(dev_in),
            "--title", "Unit Test Report",
            "--subtitle", "dummy data",
            "--theme", "cosmo",
            "--output", str(out_html),
            "--output_md", str(out_md),
            "--output_qmd", str(out_qmd),
        ])

        assert result.returncode == 0, (
            f"Component failed.\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )

        # --- QMD structure ---
        qmd = out_qmd.read_text()
        assert qmd.startswith("---\n"), "QMD missing YAML header"
        assert 'title: "Unit Test Report"' in qmd
        assert 'subtitle: "dummy data"' in qmd
        assert "theme: cosmo" in qmd
        assert "html:" in qmd and "gfm:" in qmd

        assert "# Executive summary" in qmd
        assert "| Pipeline runs | 5 |" in qmd
        assert "| Pipeline success rate | 60.0% |" in qmd
        assert "| Merged pull requests | 2 |" in qmd
        assert "| Releases / tags | 1 |" in qmd
        assert "| Commits | 12 |" in qmd

        assert "# Pipeline operations" in qmd
        assert "| nf-core/rnaseq | 3 | 2 | 1 | 66.7% | 42.5 |" in qmd
        assert "| nf-core/sarek | 2 | 1 | 0 | 50.0% | 120.0 |" in qmd
        assert "angry_einstein" in qmd
        assert "java.lang.RuntimeException: boom" in qmd
        assert "Run ID: `wf-abc`" in qmd

        assert "# Development activity" in qmd
        assert "| viash-io/viash | 12 | 2 | 1 |" in qmd
        assert "[v1.2.3]" in qmd
        assert "[#42]" in qmd and "Add feature X" in qmd
        assert "`enhancement`" in qmd

        # --- Rendered outputs (real quarto) ---
        html = out_html.read_text()
        md = out_md.read_text()
        assert "<html" in html.lower(), "HTML output does not look like HTML"
        assert "Executive summary" in html
        assert "Unit Test Report" in html
        assert "Executive summary" in md
        assert "Unit Test Report" in md

    print("PASS: test_full_report")


def test_seqera_only_no_md():
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        seqera_in = tdp / "seqera.json"
        seqera_in.write_text(json.dumps(DUMMY_SEQERA))

        out_html = tdp / "out.html"
        out_qmd = tdp / "out.qmd"

        result = run_component([
            "--seqera_json", str(seqera_in),
            "--title", "Seqera Only",
            "--output", str(out_html),
            "--output_qmd", str(out_qmd),
        ])

        assert result.returncode == 0, (
            f"Component failed.\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )

        qmd = out_qmd.read_text()
        assert "# Pipeline operations" in qmd
        assert "# Development activity" not in qmd
        assert "gfm:" not in qmd, "gfm format should be disabled without --output_md"

        html = out_html.read_text()
        assert "<html" in html.lower()
        assert "Seqera Only" in html

    print("PASS: test_seqera_only_no_md")


def test_fails_without_inputs():
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        out_html = tdp / "out.html"

        result = run_component([
            "--title", "Empty",
            "--output", str(out_html),
        ])

        assert result.returncode != 0, "Component should fail without inputs"
        assert "No input JSON provided" in (result.stderr + result.stdout)

    print("PASS: test_fails_without_inputs")


if __name__ == "__main__":
    test_full_report()
    test_seqera_only_no_md()
    test_fails_without_inputs()
    print("\nAll tests passed.")
