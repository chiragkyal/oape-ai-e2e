"""
Core agent execution logic shared between sync and async endpoints.

Supports both single-command execution and full workflow orchestration.
"""

import json
import logging
import os
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    ToolResultBlock,
)

# Resolve the plugin directory (repo root) relative to this file.
PLUGIN_DIR = str(Path(__file__).resolve().parent.parent / "plugins" / "oape")
TEAM_REPOS_CSV = str(Path(__file__).resolve().parent.parent / "team-repos.csv")

CONVERSATION_LOG = Path("/tmp/conversation.log")

conv_logger = logging.getLogger("conversation")
conv_logger.setLevel(logging.INFO)
_handler = logging.FileHandler(CONVERSATION_LOG)
_handler.setFormatter(logging.Formatter("%(message)s"))
conv_logger.addHandler(_handler)

with open(Path(__file__).resolve().parent / "config.json") as cf:
    CONFIGS = json.loads(cf.read())

# ---------------------------------------------------------------------------
# Workflow system prompt — instructs a single long-running agent session
# to execute the full feature development pipeline.
# ---------------------------------------------------------------------------

WORKFLOW_SYSTEM_PROMPT = """\
You are an OpenShift operator AI feature development agent. Your job is to
execute a complete feature development workflow given an Enhancement Proposal
(EP) PR URL. You MUST follow every phase below **in order**, and you MUST NOT
skip any phase. Stream your progress clearly so the user can follow along.

## Inputs
- EP_URL: the GitHub Enhancement Proposal PR URL (provided in the user prompt).

## Allowed repositories
Read the file {team_repos_csv} to get the list of allowed repositories and
their base branches (CSV columns: product, role, repo_url, base_branch).

## Phase 0 — Detect target repository
1. Fetch the EP PR description using `gh pr view <EP_URL> --json body -q .body`
   (or WebFetch the PR page).
2. From the EP content, determine which operator repository it targets.
   Match against the repos in {team_repos_csv}.
3. Extract: REPO_SHORT_NAME, REPO_URL, BASE_BRANCH.
   - REPO_SHORT_NAME is the last path component of the repo URL without .git
     (e.g. "cert-manager-operator").
4. Print a summary: "Detected repo: <REPO_SHORT_NAME>, base branch: <BASE_BRANCH>".

If you cannot determine the repo, STOP and report the failure.

## Phase 1 — Clone repository
1. Run `/oape:init <REPO_SHORT_NAME>` in the current working directory.
2. After init completes, `cd` into the cloned repo directory.
3. Run `git fetch origin` and `git checkout <BASE_BRANCH>` to ensure you are
   on the correct base branch.
4. Extract the EP number from EP_URL (the numeric part after /pull/).

## Phase 2 — PR #1: API Types + Tests
1. Create and checkout a new branch: `git checkout -b oape/api-types-<EP_NUMBER>`
2. Run `/oape:api-generate <EP_URL>`.
3. Identify the generated API directory (typically `api/` or a subdirectory).
4. Run `/oape:api-generate-tests <path-to-api-directory>`.
5. Run `make generate && make manifests` (if Makefile targets exist).
6. Run `make build && make test` to verify the code compiles and tests pass.
   If build or tests fail, attempt to fix the issues.
7. Run `/oape:review NO_TICKET origin/<BASE_BRANCH>` to review code quality.
   The review will auto-fix issues it finds.
8. Run `make build && make test` again after review fixes.
9. Stage all changes: `git add -A`
10. Commit: `git commit -m "oape: generate API types and tests from EP #<EP_NUMBER>"`
11. Push: `git push -u origin oape/api-types-<EP_NUMBER>`
12. Create PR #1:
    ```
    gh pr create \\
      --base <BASE_BRANCH> \\
      --title "oape: API types and tests from EP #<EP_NUMBER>" \\
      --body "Auto-generated API type definitions and integration tests from <EP_URL>"
    ```
13. Save the PR #1 URL.

## Phase 3 — PR #2: Controller Implementation
1. From the current branch (oape/api-types-<EP_NUMBER>), create a new branch:
   `git checkout -b oape/controller-<EP_NUMBER>`
2. Run `/oape:api-implement <EP_URL>`.
3. Run `make generate && make manifests` (if targets exist).
4. Run `make build && make test`. Fix failures if any.
5. Run `/oape:review NO_TICKET origin/<BASE_BRANCH>` to review.
6. Run `make build && make test` again after review fixes.
7. Stage, commit: `git commit -m "oape: implement controller from EP #<EP_NUMBER>"`
8. Push: `git push -u origin oape/controller-<EP_NUMBER>`
9. Create PR #2 (base = the api-types branch so it stacks):
    ```
    gh pr create \\
      --base oape/api-types-<EP_NUMBER> \\
      --title "oape: controller implementation from EP #<EP_NUMBER>" \\
      --body "Auto-generated controller/reconciler code from <EP_URL>"
    ```
10. Save the PR #2 URL.

## Phase 4 — PR #3: E2E Tests
1. Go back to the api-types branch: `git checkout oape/api-types-<EP_NUMBER>`
2. Create a new branch: `git checkout -b oape/e2e-<EP_NUMBER>`
3. Run `/oape:e2e-generate <BASE_BRANCH>`.
4. Run `/oape:review NO_TICKET origin/<BASE_BRANCH>` to review.
5. Fix any issues, verify build passes.
6. Stage, commit: `git commit -m "oape: generate e2e tests from EP #<EP_NUMBER>"`
7. Push: `git push -u origin oape/e2e-<EP_NUMBER>`
8. Create PR #3 (base = the api-types branch):
    ```
    gh pr create \\
      --base oape/api-types-<EP_NUMBER> \\
      --title "oape: e2e tests from EP #<EP_NUMBER>" \\
      --body "Auto-generated e2e test artifacts from <EP_URL>"
    ```
9. Save the PR #3 URL.

## Phase 5 — Summary
Output a final summary in this exact format:

```
=== OAPE Workflow Complete ===

Enhancement Proposal: <EP_URL>
Target Repository:    <REPO_SHORT_NAME>
Base Branch:          <BASE_BRANCH>

PR #1 (API Types + Tests):      <PR_1_URL>
PR #2 (Controller):             <PR_2_URL>
PR #3 (E2E Tests):              <PR_3_URL>
```

## Critical Rules
- NEVER skip a phase. Execute them in order.
- If a phase fails and you cannot recover, STOP and report which phase failed and why.
- Always use `git add -A` before committing to include all generated files.
- The review command with NO_TICKET skips Jira validation and reviews code quality only.
- Use `gh pr create` (not manual URL construction) for creating PRs.
- Do NOT modify the EP or any upstream repository.
"""


@dataclass
class AgentResult:
    """Result returned after running the Claude agent."""

    output: str
    cost_usd: float
    error: str | None = None
    conversation: list[dict] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.error is None


async def run_agent(
    prompt: str,
    working_dir: str,
    system_prompt: str,
    on_message: Callable[[dict], None] | None = None,
) -> AgentResult:
    """Run the Claude agent with an arbitrary prompt and system prompt.

    Args:
        prompt: The user prompt to send to the agent.
        working_dir: Absolute path to the working directory.
        system_prompt: The system prompt for the agent.
        on_message: Optional callback invoked with each conversation message
            dict as it arrives, enabling real-time streaming.

    Returns:
        An AgentResult with the output or error.
    """
    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        cwd=working_dir,
        permission_mode="bypassPermissions",
        allowed_tools=CONFIGS["claude_allowed_tools"],
        plugins=[{"type": "local", "path": PLUGIN_DIR}],
    )

    output_parts: list[str] = []
    conversation: list[dict] = []
    cost_usd = 0.0

    conv_logger.info(
        f"\n{'=' * 60}\n[request] prompt={prompt[:120]}  "
        f"cwd={working_dir}\n{'=' * 60}"
    )

    def _emit(entry: dict) -> None:
        """Append to conversation and invoke on_message callback if set."""
        conversation.append(entry)
        if on_message is not None:
            on_message(entry)

    try:
        async for message in query(
            prompt=prompt,
            options=options,
        ):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        output_parts.append(block.text)
                        entry = {"type": "assistant", "block_type": "text",
                                 "content": block.text}
                        _emit(entry)
                        conv_logger.info(f"[assistant] {block.text}")
                    elif isinstance(block, ThinkingBlock):
                        entry = {"type": "assistant", "block_type": "thinking",
                                 "content": block.thinking}
                        _emit(entry)
                        conv_logger.info(
                            f"[assistant:ThinkingBlock] (thinking)")
                    elif isinstance(block, ToolUseBlock):
                        entry = {"type": "assistant", "block_type": "tool_use",
                                 "tool_name": block.name,
                                 "tool_input": block.input}
                        _emit(entry)
                        conv_logger.info(
                            f"[assistant:ToolUseBlock] {block.name}")
                    elif isinstance(block, ToolResultBlock):
                        content = block.content
                        if not isinstance(content, str):
                            content = json.dumps(content, default=str)
                        entry = {"type": "assistant", "block_type": "tool_result",
                                 "tool_use_id": block.tool_use_id,
                                 "content": content,
                                 "is_error": block.is_error or False}
                        _emit(entry)
                        conv_logger.info(
                            f"[assistant:ToolResultBlock] {block.tool_use_id}")
                    else:
                        detail = json.dumps(
                            getattr(block, "__dict__", str(block)),
                            default=str,
                        )
                        entry = {
                            "type": "assistant",
                            "block_type": type(block).__name__,
                            "content": detail,
                        }
                        _emit(entry)
                        conv_logger.info(
                            f"[assistant:{type(block).__name__}] {detail}"
                        )
            elif isinstance(message, ResultMessage):
                cost_usd = message.total_cost_usd
                if message.result:
                    output_parts.append(message.result)
                entry = {
                    "type": "result",
                    "content": message.result,
                    "cost_usd": cost_usd,
                }
                _emit(entry)
                conv_logger.info(
                    f"[result] {message.result}  cost=${cost_usd:.4f}"
                )
            else:
                detail = json.dumps(
                    getattr(message, "__dict__", str(message)), default=str
                )
                entry = {
                    "type": type(message).__name__,
                    "content": detail,
                }
                _emit(entry)
                conv_logger.info(f"[{type(message).__name__}] {detail}")

        conv_logger.info(
            f"[done] cost=${cost_usd:.4f}  parts={len(output_parts)}\n"
        )
        return AgentResult(
            output="\n".join(output_parts),
            cost_usd=cost_usd,
            conversation=conversation,
        )
    except Exception as exc:
        conv_logger.info(f"[error] {traceback.format_exc()}")
        return AgentResult(
            output="",
            cost_usd=cost_usd,
            error=str(exc),
            conversation=conversation,
        )


async def run_workflow(
    ep_url: str,
    on_message: Callable[[dict], None] | None = None,
) -> AgentResult:
    """Run the full OAPE feature development workflow.

    Creates a temp directory, then launches a single long-running agent session
    that executes all phases: init, api-generate, api-generate-tests, review,
    PR creation, api-implement, e2e-generate, etc.

    Args:
        ep_url: The enhancement proposal PR URL.
        on_message: Optional streaming callback.

    Returns:
        An AgentResult with the final summary or error.
    """
    job_id = uuid.uuid4().hex[:12]
    working_dir = f"/tmp/oape-{job_id}"
    os.makedirs(working_dir, exist_ok=True)

    system_prompt = WORKFLOW_SYSTEM_PROMPT.format(
        team_repos_csv=TEAM_REPOS_CSV,
    )

    return await run_agent(
        prompt=(
            f"Execute the full OAPE feature development workflow for this "
            f"Enhancement Proposal: {ep_url}"
        ),
        working_dir=working_dir,
        system_prompt=system_prompt,
        on_message=on_message,
    )
