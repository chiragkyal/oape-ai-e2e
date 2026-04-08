"""
Phase 2: Parallel sub-agents launched from API type changes.

  2a) api-implement  -> review-and-fix -> raise PR
  2b) e2e-generate   -> review-and-fix -> raise PR

Both run concurrently via asyncio.gather.
"""

import asyncio
import textwrap
import time
from pathlib import Path

from claude_agent_sdk import ClaudeSDKClient

from .config import make_agent_options
from .state import (
    WorkflowState,
    make_workdir,
    read_state_summary,
    write_state_summary,
)
from .utils import collect_response, extract_pr_url, extract_text


# ---------------------------------------------------------------------------
# 2a – Controller implementation
# ---------------------------------------------------------------------------


async def _run_controller(state: WorkflowState) -> str | None:
    """Run api-implement -> review-and-fix -> raise PR.  Returns PR URL."""
    workdir = make_workdir("phase2a-controller")
    print("\n" + "-" * 60)
    print("PHASE 2a: Controller Implementation (sub-agent)")
    print("-" * 60)

    api_summary = read_state_summary(Path(state.api_summary_md))
    write_state_summary(workdir, "api-types-summary.md", api_summary)

    opts = make_agent_options(
        cwd=state.repo_local_path,
        system_prompt_append=textwrap.dedent(f"""\
            You are a sub-agent in the OAPE workflow.
            Your task is to generate controller/reconciler implementation code.

            Context from the previous phase (API types generation):
            {api_summary[:3000]}

            Enhancement Proposal URL: {state.ep_url}
            Base branch: {state.base_branch}

            Steps to execute:
            1. Run /oape:api-implement {state.ep_url}
            2. Run `go build ./...` and fix any compilation errors
            3. If `make generate` and `make manifests` exist, run them
            4. Run `go vet ./...` and fix any issues
            5. Create a new branch, commit, push, and raise a PR against '{state.base_branch}'
            6. Print the PR URL

            Do NOT ask for confirmation. Proceed autonomously.
        """),
    )

    async with ClaudeSDKClient(opts) as client:
        branch = f"oape/controller-impl-{int(time.time())}"
        await client.query(
            f"/oape:api-implement {state.ep_url}\n\n"
            "After that completes, build, fix issues, commit to a new branch "
            f"'{branch}', push, and raise a PR against '{state.base_branch}'."
        )
        msgs = await collect_response(client)
        text = extract_text(msgs)
        pr_url = extract_pr_url(text)

        if not pr_url:
            await client.query(
                "Please create the PR now if you haven't already. "
                "Print the PR URL when done."
            )
            msgs2 = await collect_response(client)
            pr_url = extract_pr_url(extract_text(msgs2))
            text += "\n" + extract_text(msgs2)

    write_state_summary(
        workdir,
        "controller-summary.md",
        f"# Controller Implementation Summary\n\nPR: {pr_url or 'N/A'}\n\n"
        f"## Output\n{text[:3000]}",
    )

    if pr_url:
        state.pr_urls["controller"] = pr_url
        print(f"  >> Controller PR: {pr_url}")
    return pr_url


# ---------------------------------------------------------------------------
# 2b – E2E test generation
# ---------------------------------------------------------------------------


async def _run_e2e_tests(state: WorkflowState) -> str | None:
    """Run e2e-generate -> review-and-fix -> raise PR.  Returns PR URL."""
    workdir = make_workdir("phase2b-e2e-tests")
    print("\n" + "-" * 60)
    print("PHASE 2b: E2E Test Generation (sub-agent)")
    print("-" * 60)

    api_summary = read_state_summary(Path(state.api_summary_md))
    write_state_summary(workdir, "api-types-summary.md", api_summary)

    opts = make_agent_options(
        cwd=state.repo_local_path,
        system_prompt_append=textwrap.dedent(f"""\
            You are a sub-agent in the OAPE workflow.
            Your task is to generate e2e tests based on the API type changes.

            Context from the previous phase (API types generation):
            {api_summary[:3000]}

            Enhancement Proposal URL: {state.ep_url}
            Base branch: {state.base_branch}

            Steps to execute:
            1. Run /oape:e2e-generate {state.base_branch}
            2. Review the generated test artifacts
            3. Copy the generated e2e test code into the appropriate test directory
            4. Run `go build ./...` and fix any compilation errors
            5. Create a new branch, commit, push, and raise a PR against '{state.base_branch}'
            6. Print the PR URL

            Do NOT ask for confirmation. Proceed autonomously.
        """),
    )

    async with ClaudeSDKClient(opts) as client:
        branch = f"oape/e2e-tests-{int(time.time())}"
        await client.query(
            f"/oape:e2e-generate {state.base_branch}\n\n"
            "After that completes, copy test files into the repo's test directory, "
            f"build, fix issues, commit to a new branch '{branch}', push, and "
            f"raise a PR against '{state.base_branch}'."
        )
        msgs = await collect_response(client)
        text = extract_text(msgs)
        pr_url = extract_pr_url(text)

        if not pr_url:
            await client.query(
                "Please create the PR now if you haven't already. "
                "Print the PR URL when done."
            )
            msgs2 = await collect_response(client)
            pr_url = extract_pr_url(extract_text(msgs2))
            text += "\n" + extract_text(msgs2)

    write_state_summary(
        workdir,
        "e2e-summary.md",
        f"# E2E Test Generation Summary\n\nPR: {pr_url or 'N/A'}\n\n"
        f"## Output\n{text[:3000]}",
    )

    if pr_url:
        state.pr_urls["e2e-tests"] = pr_url
        print(f"  >> E2E Tests PR: {pr_url}")
    return pr_url


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def run(state: WorkflowState) -> None:
    """Launch both sub-agents in parallel and collect results."""
    print("\n" + "=" * 70)
    print("PHASE 2: Parallel Sub-Agents (Controller + E2E Tests)")
    print("=" * 70)

    results = await asyncio.gather(
        _run_controller(state),
        _run_e2e_tests(state),
        return_exceptions=True,
    )

    labels = ["Controller", "E2E Tests"]
    for label, result in zip(labels, results):
        if isinstance(result, Exception):
            print(f"  {label} sub-agent failed: {result}")
        elif result:
            print(f"  {label} PR: {result}")
        else:
            print(f"  {label}: no PR URL captured")
