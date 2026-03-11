"""
Phase 3: Watch all raised PRs for CI checks to pass, then notify the user.
"""

import asyncio
import json
import re
import subprocess
import textwrap
import time
from typing import Any

from .config import MAX_CI_WAIT_MINS, POLL_INTERVAL_SECS
from .state import WorkflowState, make_workdir, write_state_summary


def _check_pr_status(pr_url: str) -> dict[str, Any]:
    """Query CI status of a GitHub PR via `gh` CLI."""
    m = re.match(r"https://github\.com/([^/]+/[^/]+)/pull/(\d+)", pr_url)
    if not m:
        return {"state": "unknown", "checks_pass": False, "mergeable": False}

    repo, pr_number = m.group(1), m.group(2)

    try:
        result = subprocess.run(
            [
                "gh", "pr", "view", pr_number,
                "--repo", repo,
                "--json", "state,statusCheckRollup,mergeable,mergeStateStatus",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return {"state": "error", "checks_pass": False, "mergeable": False}

        data = json.loads(result.stdout)
        checks = data.get("statusCheckRollup", [])

        all_pass = all(
            c.get("conclusion") in ("SUCCESS", "NEUTRAL", "SKIPPED")
            for c in checks
            if c.get("status") == "COMPLETED"
        )
        all_complete = len(checks) > 0 and all(
            c.get("status") == "COMPLETED" for c in checks
        )

        return {
            "state": data.get("state", "unknown"),
            "checks_pass": all_pass and all_complete,
            "mergeable": data.get("mergeable", "") == "MERGEABLE",
            "merge_state": data.get("mergeStateStatus", ""),
            "num_checks": len(checks),
            "pending": sum(1 for c in checks if c.get("status") != "COMPLETED"),
        }
    except Exception as e:
        return {
            "state": "error",
            "checks_pass": False,
            "mergeable": False,
            "error": str(e),
        }


async def run(
    state: WorkflowState,
    max_wait_mins: int | None = None,
    poll_secs: int | None = None,
) -> None:
    """Poll all PRs until CI passes or timeout, then print a final report."""
    if not state.pr_urls:
        print("\nNo PRs to watch.")
        return

    wait = max_wait_mins or MAX_CI_WAIT_MINS
    interval = poll_secs or POLL_INTERVAL_SECS

    print("\n" + "=" * 70)
    print("PHASE 3: Watching PRs for CI")
    print("=" * 70)
    for label, url in state.pr_urls.items():
        print(f"  {label}: {url}")

    start = time.time()
    remaining = dict(state.pr_urls)
    passed: dict[str, str] = {}
    failed: dict[str, str] = {}

    while remaining and (time.time() - start) < wait * 60:
        for label, url in list(remaining.items()):
            status = _check_pr_status(url)
            elapsed = int((time.time() - start) / 60)

            if status["checks_pass"]:
                print(
                    f"  [{elapsed}m] {label}: ALL CHECKS PASSED "
                    f"({status['num_checks']} checks)"
                )
                passed[label] = url
                del remaining[label]
            elif status["state"] == "CLOSED":
                print(f"  [{elapsed}m] {label}: PR CLOSED")
                failed[label] = url
                del remaining[label]
            else:
                pending = status.get("pending", "?")
                print(f"  [{elapsed}m] {label}: waiting ({pending} pending)")

        if remaining:
            await asyncio.sleep(interval)

    # -- Final report --
    print("\n" + "=" * 70)
    print("WORKFLOW COMPLETE")
    print("=" * 70)

    if passed:
        print("\nPRs with ALL checks passing (ready for human merge):")
        for label, url in passed.items():
            print(f"  {label}: {url}")

    if failed:
        print("\nPRs closed or with issues:")
        for label, url in failed.items():
            print(f"  {label}: {url}")

    if remaining:
        print(f"\nPRs still pending after {wait}min timeout:")
        for label, url in remaining.items():
            print(f"  {label}: {url}")

    # -- Persist final summary --
    workdir = make_workdir("final")
    summary = textwrap.dedent(f"""\
        # OAPE Workflow Final Summary

        ## Enhancement Proposal
        {state.ep_url}

        ## Repository
        {state.repo_url} (base: {state.base_branch})

        ## PRs Created
        {"".join(f"- **{k}**: {v}" + chr(10) for k, v in state.pr_urls.items())}

        ## CI Status
        - Passed: {", ".join(passed.keys()) or "none"}
        - Failed/Closed: {", ".join(failed.keys()) or "none"}
        - Timed out: {", ".join(remaining.keys()) or "none"}

        ## Action Required
        Human review and merge of passing PRs.
    """)
    write_state_summary(workdir, "workflow-summary.md", summary)
    print(f"\nFull summary: .oape-work/final/workflow-summary.md")
