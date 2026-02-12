"""
FastAPI server that exposes the /oape:api-implement Claude Code skill
via the Claude Agent SDK.

Usage:
    uvicorn api.server:app --reload

Endpoint:
    GET /api-implement?ep_url=<enhancement-pr-url>&cwd=<operator-repo-path>
"""

import os
import re
from pathlib import Path

import anyio
from fastapi import FastAPI, HTTPException, Query
from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    TextBlock,
)

app = FastAPI(
    title="OAPE API Implement",
    description="Invokes the /oape:api-implement Claude Code skill to generate "
    "controller/reconciler code from an OpenShift enhancement proposal.",
    version="0.1.0",
)

EP_URL_PATTERN = re.compile(
    r"^https://github\.com/openshift/enhancements/pull/\d+/?$"
)

# Resolve the plugin directory (repo root) relative to this file.
PLUGIN_DIR = str(Path(__file__).resolve().parent.parent)


@app.get("/api-implement")
async def api_implement(
    ep_url: str = Query(
        ...,
        description="GitHub PR URL for the OpenShift enhancement proposal "
        "(e.g. https://github.com/openshift/enhancements/pull/1234)",
    ),
    cwd: str = Query(
        default="",
        description="Absolute path to the operator repository where code "
        "will be generated. Defaults to the current working directory.",
    ),
):
    """Generate controller/reconciler code from an enhancement proposal."""

    # --- Validate EP URL ---
    if not EP_URL_PATTERN.match(ep_url.rstrip("/")):
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid enhancement PR URL. "
                "Expected format: https://github.com/openshift/enhancements/pull/<number>"
            ),
        )

    # --- Resolve working directory ---
    working_dir = cwd if cwd else os.getcwd()
    if not os.path.isdir(working_dir):
        raise HTTPException(
            status_code=400,
            detail=f"The provided cwd is not a valid directory: {working_dir}",
        )

    # --- Build SDK options ---
    options = ClaudeAgentOptions(
        system_prompt=(
            "You are an OpenShift operator code generation assistant. "
            "Execute the /oape:api-implement skill with the provided EP URL. "
            "Generate production-ready controller code with zero TODOs."
        ),
        cwd=working_dir,
        permission_mode="bypassPermissions",
        allowed_tools=[
            "Bash",
            "Read",
            "Write",
            "Edit",
            "Glob",
            "Grep",
            "WebFetch",
            "Task",
        ],
        plugins=[PLUGIN_DIR],
    )

    # --- Run the agent ---
    output_parts: list[str] = []
    cost_usd = 0.0

    try:
        async for message in query(
            prompt=f"/oape:api-implement {ep_url}",
            options=options,
        ):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        output_parts.append(block.text)
            elif isinstance(message, ResultMessage):
                cost_usd = message.total_cost_usd
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Agent execution failed: {exc}",
        )

    return {
        "status": "success",
        "ep_url": ep_url,
        "cwd": working_dir,
        "output": "\n".join(output_parts),
        "cost_usd": cost_usd,
    }
