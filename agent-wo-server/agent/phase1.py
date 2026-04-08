"""
Phase 1: Sequential API Types Pipeline

  init -> api-generate -> api-generate-tests -> review-and-fix -> raise PR
"""

import textwrap
import time

from claude_agent_sdk import ClaudeSDKClient

from .config import make_agent_options
from .state import WorkflowState, make_workdir, write_state_summary
from .utils import collect_response, extract_pr_url, extract_text


async def run(state: WorkflowState) -> None:
    """Execute the full Phase 1 pipeline inside a single ClaudeSDKClient session."""
    workdir = make_workdir("phase1-api-types")

    print("\n" + "=" * 70)
    print("PHASE 1: API Types Pipeline")
    print("=" * 70)

    opts = make_agent_options(
        cwd=str(workdir),
        system_prompt_append=textwrap.dedent(f"""\
            You are running an automated OAPE workflow.
            The Enhancement Proposal URL is: {state.ep_url}
            The target repository short name is: {state.repo_short_name}
            The target repository URL is: {state.repo_url}
            The base branch is: {state.base_branch}

            You will execute a series of /oape: slash commands in sequence.
            After each command completes, proceed to the next.
            Do NOT ask the user for confirmation between steps -- proceed autonomously.
            If a step fails, report the error and stop.

            At the end, write a summary of everything that happened to a file
            called 'api-types-summary.md' in the current working directory.
        """),
    )

    async with ClaudeSDKClient(opts) as client:
        # -- Step 1: Clone repo --
        print("\n--- Step 1/5: /oape:init ---")
        await client.query(f"/oape:init {state.repo_short_name}")
        await collect_response(client)

        # Determine the cloned repo path
        cloned_dir = workdir / state.repo_short_name
        if cloned_dir.is_dir():
            state.repo_local_path = str(cloned_dir)
        else:
            for child in workdir.iterdir():
                if (child / ".git").is_dir():
                    state.repo_local_path = str(child)
                    break

        # -- Step 2: Generate API types --
        print("\n--- Step 2/5: /oape:api-generate ---")
        await client.query(
            f"cd {state.repo_local_path} && /oape:api-generate {state.ep_url}"
        )
        msgs = await collect_response(client)
        api_gen_text = extract_text(msgs)

        # -- Step 3: Generate API tests --
        print("\n--- Step 3/5: /oape:api-generate-tests ---")
        await client.query(
            "Now run /oape:api-generate-tests on the API types directory you just "
            "generated. Determine the correct path from the api-generate output above."
        )
        msgs = await collect_response(client)
        api_tests_text = extract_text(msgs)

        # -- Step 4: Review and fix --
        print("\n--- Step 4/5: Review and fix ---")
        await client.query(
            "Now review the changes you've made. Run `go build ./...` and `go vet ./...` "
            "to check for compilation errors. Fix any issues found. "
            "If `make generate` or `make manifests` targets exist, run them. "
            "Ensure the code compiles cleanly."
        )
        await collect_response(client)

        # -- Step 5: Commit and raise PR --
        print("\n--- Step 5/5: Raise PR ---")
        branch_name = f"oape/api-types-{int(time.time())}"
        await client.query(
            textwrap.dedent(f"""\
                Now commit all changes and raise a PR:
                1. Create and checkout a new branch: {branch_name}
                2. Stage all changed/new files (except .oape-work/)
                3. Commit with a descriptive conventional commit message
                4. Push the branch to origin
                5. Create a PR against '{state.base_branch}' using `gh pr create`
                   with a clear title and body describing the API types from the EP.
                6. Print the PR URL at the end.
            """)
        )
        msgs = await collect_response(client)
        pr_url = extract_pr_url(extract_text(msgs))
        if pr_url:
            state.pr_urls["api-types"] = pr_url
            print(f"\n  >> API Types PR: {pr_url}")

    # -- Write state summary for downstream phases --
    summary = textwrap.dedent(f"""\
        # Phase 1: API Types Summary

        ## Enhancement Proposal
        {state.ep_url}

        ## Repository
        - Short name: {state.repo_short_name}
        - URL: {state.repo_url}
        - Base branch: {state.base_branch}
        - Local path: {state.repo_local_path}

        ## Steps Completed
        1. Repository cloned via /oape:init
        2. API types generated via /oape:api-generate
        3. API integration tests generated via /oape:api-generate-tests
        4. Code reviewed and fixed (build + vet)
        5. PR raised: {state.pr_urls.get('api-types', 'N/A')}

        ## API Generation Output (excerpt)
        {api_gen_text[:2000]}

        ## API Test Generation Output (excerpt)
        {api_tests_text[:2000]}
    """)
    state.api_summary_md = str(
        write_state_summary(workdir, "api-types-summary.md", summary)
    )
    print(f"  State summary: {state.api_summary_md}")
