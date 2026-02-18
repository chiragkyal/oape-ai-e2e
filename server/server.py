"""
FastAPI server that exposes OAPE Claude Code skills via the Claude Agent SDK.

Usage:
    uvicorn server:app --reload

Endpoints:
    GET  /                                    - Homepage with submission form
    POST /submit                              - Submit a job (returns job_id)
    GET  /status/{job_id}                     - Poll job status
    GET  /stream/{job_id}                     - SSE stream of agent conversation
    GET  /api/v1/oape-api-implement?ep_url=.. - Synchronous API-implement endpoint
"""

import asyncio
import json
import os
from pathlib import Path
import re
import uuid

from fastapi import FastAPI, HTTPException, Query, Form
from fastapi.responses import HTMLResponse
from sse_starlette.sse import EventSourceResponse

from agent import run_agent, SUPPORTED_COMMANDS


app = FastAPI(
    title="OAPE Operator Feature Developer",
    description="Invokes OAPE Claude Code commands to generate "
    "controller/reconciler code from an OpenShift enhancement proposal.",
    version="0.1.0",
)

EP_URL_PATTERN = re.compile(
    r"^https://github\.com/openshift/enhancements/pull/\d+/?$"
)
# RFE key (e.g. RFE-7841) or Jira browse URL
RFE_INPUT_PATTERN = re.compile(
    r"^(?:https://issues\.redhat\.com/browse/)?([A-Z]+-\d+)/?$",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# In-memory job store
# ---------------------------------------------------------------------------
jobs: dict[str, dict] = {}


def _validate_ep_url(ep_url: str) -> None:
    """Raise HTTPException if ep_url is not a valid enhancement PR URL."""
    if not EP_URL_PATTERN.match(ep_url.rstrip("/")):
        raise HTTPException(
            status_code=400,
            detail="Invalid enhancement PR URL. "
            "Expected format: https://github.com/openshift/enhancements/pull/<number>",
        )


def _validate_rfe_input(value: str) -> None:
    """Raise HTTPException if value is not a valid RFE key or Jira URL."""
    if not value or not RFE_INPUT_PATTERN.match(value.strip()):
        raise HTTPException(
            status_code=400,
            detail="Invalid RFE input. Provide a Jira issue key (e.g. RFE-7841) "
            "or URL: https://issues.redhat.com/browse/RFE-7841",
        )


def _resolve_working_dir(cwd: str) -> str:
    """Resolve and validate the working directory."""
    working_dir = cwd if cwd else os.getcwd()
    if not os.path.isdir(working_dir):
        raise HTTPException(
            status_code=400,
            detail=f"The provided cwd is not a valid directory: {working_dir}",
        )
    return working_dir


_HOMEPAGE_PATH = Path(__file__).parent / "homepage.html"
HOMEPAGE_HTML = _HOMEPAGE_PATH.read_text()


@app.get("/", response_class=HTMLResponse)
async def homepage():
    """Serve the submission form."""
    return HOMEPAGE_HTML


@app.post("/submit")
async def submit_job(
    ep_url: str = Form(...),
    command: str = Form(default="api-implement"),
    cwd: str = Form(default=""),
):
    """Validate inputs, create a background job, and return its ID."""
    if command == "analyze-rfe":
        _validate_rfe_input(ep_url)
    else:
        _validate_ep_url(ep_url)
    if command not in SUPPORTED_COMMANDS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported command: {command}. "
            f"Supported: {', '.join(SUPPORTED_COMMANDS)}",
        )
    working_dir = _resolve_working_dir(cwd)

    job_id = uuid.uuid4().hex[:12]
    jobs[job_id] = {
        "status": "running",
        "ep_url": ep_url,
        "cwd": working_dir,
        "conversation": [],
        "message_event": asyncio.Condition(),
        "output": "",
        "cost_usd": 0.0,
        "error": None,
    }
    asyncio.create_task(_run_job(job_id, command, ep_url, working_dir))
    return {"job_id": job_id}


@app.get("/status/{job_id}")
async def job_status(job_id: str):
    """Return the current status of a job."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[job_id]
    return {
        "status": job["status"],
        "ep_url": job["ep_url"],
        "cwd": job["cwd"],
        "output": job.get("output", ""),
        "cost_usd": job.get("cost_usd", 0.0),
        "error": job.get("error"),
        "message_count": len(job.get("conversation", [])),
    }


@app.get("/stream/{job_id}")
async def stream_job(job_id: str):
    """Stream job conversation messages via Server-Sent Events."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator():
        cursor = 0
        condition = jobs[job_id]["message_event"]

        while True:
            # Send any new messages since the cursor
            conversation = jobs[job_id]["conversation"]
            while cursor < len(conversation):
                yield {
                    "event": "message",
                    "data": json.dumps(conversation[cursor], default=str),
                }
                cursor += 1

            # Check if the job is complete
            status = jobs[job_id]["status"]
            if status != "running":
                yield {
                    "event": "complete",
                    "data": json.dumps({
                        "status": status,
                        "output": jobs[job_id].get("output", ""),
                        "cost_usd": jobs[job_id].get("cost_usd", 0.0),
                        "error": jobs[job_id].get("error"),
                    }),
                }
                return

            # Wait for new messages or send keepalive on timeout
            async with condition:
                try:
                    await asyncio.wait_for(condition.wait(), timeout=30.0)
                except asyncio.TimeoutError:
                    yield {"event": "keepalive", "data": ""}

    return EventSourceResponse(event_generator())


async def _run_job(job_id: str, command: str, ep_url: str, working_dir: str):
    """Run the Claude agent in the background and stream messages to the job store."""
    condition = jobs[job_id]["message_event"]

    loop = asyncio.get_running_loop()

    def on_message(msg: dict) -> None:
        jobs[job_id]["conversation"].append(msg)
        loop.create_task(_notify(condition))

    result = await run_agent(command, ep_url, working_dir, on_message=on_message)
    if result.success:
        jobs[job_id]["status"] = "success"
        jobs[job_id]["output"] = result.output
        jobs[job_id]["cost_usd"] = result.cost_usd
    else:
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = result.error

    # Final notification so SSE clients see the status change
    async with condition:
        condition.notify_all()


async def _notify(condition: asyncio.Condition) -> None:
    """Notify all waiters on the condition."""
    async with condition:
        condition.notify_all()


@app.get("/api/v1/oape-api-implement")
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
    """Generate controller/reconciler code from an enhancement proposal (synchronous)."""
    _validate_ep_url(ep_url)
    working_dir = _resolve_working_dir(cwd)

    result = await run_agent("api-implement", ep_url, working_dir)
    if not result.success:
        raise HTTPException(
            status_code=500, detail=f"Agent execution failed: {result.error}"
        )

    return {
        "status": "success",
        "ep_url": ep_url,
        "cwd": working_dir,
        "output": result.output,
        "cost_usd": result.cost_usd,
    }
