#!/usr/bin/env python3
"""
OAPE AI E2E Workflow — entry point.

Usage:
    python -m src.agent.main

You will be prompted for the Enhancement Proposal URL and target repository.
"""

import asyncio
import re
import sys

from . import phase1, phase2, phase3
from .config import MAX_CI_WAIT_MINS, POLL_INTERVAL_SECS
from .state import WorkflowState
from .utils import resolve_repo


def _prompt_ep_url() -> str:
    """Interactively ask for the Enhancement Proposal URL."""
    print("=" * 70)
    print("OAPE AI E2E Workflow Orchestrator")
    print("=" * 70)
    print()

    url = input("Enhancement Proposal PR URL: ").strip()

    if not re.match(
        r"^https://github\.com/openshift/enhancements/pull/\d+/?$", url
    ):
        print(
            "ERROR: URL must match "
            "https://github.com/openshift/enhancements/pull/<number>"
        )
        sys.exit(1)

    return url


async def run_workflow() -> None:
    """Full orchestration: prompt for inputs, run all phases."""
    ep_url = _prompt_ep_url()

    repo_short, repo_url, base_branch = resolve_repo(ep_url)

    state = WorkflowState(
        ep_url=ep_url,
        repo_short_name=repo_short,
        repo_url=repo_url,
        base_branch=base_branch,
    )

    print(f"\nTarget: {repo_short} ({repo_url})")
    print(f"Base branch: {base_branch}")

    # Phase 1 — sequential: init -> api-generate -> api-generate-tests -> fix -> PR
    await phase1.run(state)

    if not state.repo_local_path:
        print("ERROR: Phase 1 failed to establish repo local path. Aborting.")
        sys.exit(1)

    # Phase 2 — parallel sub-agents: controller + e2e tests
    await phase2.run(state)

    # Phase 3 — watch PRs for CI green
    await phase3.run(state)


def main() -> None:
    asyncio.run(run_workflow())


if __name__ == "__main__":
    main()
