"""Standalone worker entrypoint for K8s Job execution.

Reads EP_URL and REPO from environment variables and runs the full
operator feature development workflow. All output is printed to stdout
as JSON (one message per line), which the orchestrator streams as pod logs.
"""

import asyncio
import json
import os
import sys

from agent import run_workflow


async def main():
    ep_url = os.environ.get("EP_URL")
    repo = os.environ.get("REPO")

    if not ep_url or not repo:
        print("ERROR: EP_URL and REPO environment variables are required", file=sys.stderr)
        sys.exit(1)

    working_dir = os.environ.get("WORKING_DIR", "/workspace")
    os.makedirs(working_dir, exist_ok=True)

    print(f"Starting workflow: ep_url={ep_url} repo={repo} cwd={working_dir}", flush=True)

    def on_message(msg):
        print(json.dumps(msg, default=str), flush=True)

    result = await run_workflow(ep_url, repo, working_dir, on_message=on_message)

    if result.success:
        print(f"WORKFLOW_SUCCESS cost=${result.cost_usd:.4f}", flush=True)
        for pr in result.prs:
            print(f"PR_CREATED: {pr.pr_url}", flush=True)
        sys.exit(0)
    else:
        print(f"WORKFLOW_FAILED: {result.error}", file=sys.stderr, flush=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
