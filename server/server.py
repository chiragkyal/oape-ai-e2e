"""
FastAPI server that exposes the OAPE full workflow agent via SSE streaming.

Usage:
    uvicorn server:app --reload

Endpoints:
    GET  /                  - Homepage with submission form
    POST /submit            - Submit a workflow job (returns job_id)
    GET  /status/{job_id}   - Poll job status
    GET  /stream/{job_id}   - SSE stream of agent conversation
"""

import asyncio
import json
import re
import uuid

from fastapi import FastAPI, HTTPException, Form
from fastapi.responses import HTMLResponse
from pathlib import Path
from sse_starlette.sse import EventSourceResponse

from agent import run_workflow


app = FastAPI(
    title="OAPE Operator Feature Developer",
    description="Runs the full OAPE feature development workflow: "
    "API types, controller implementation, and E2E tests "
    "from an OpenShift enhancement proposal.",
    version="0.2.0",
)

EP_URL_PATTERN = re.compile(
    r"^https://github\.com/openshift/enhancements/pull/\d+/?$"
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


_HOMEPAGE_PATH = Path(__file__).parent / "homepage.html"
HOMEPAGE_HTML = _HOMEPAGE_PATH.read_text()


@app.get("/", response_class=HTMLResponse)
async def homepage():
    """Serve the submission form."""
    return HOMEPAGE_HTML


@app.post("/submit")
async def submit_job(
    ep_url: str = Form(...),
):
    """Validate the EP URL, create a background workflow job, and return its ID."""
    _validate_ep_url(ep_url)

    job_id = uuid.uuid4().hex[:12]
    jobs[job_id] = {
        "status": "running",
        "ep_url": ep_url,
        "conversation": [],
        "message_event": asyncio.Condition(),
        "output": "",
        "cost_usd": 0.0,
        "error": None,
    }
    asyncio.create_task(_run_job(job_id, ep_url))
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


async def _run_job(job_id: str, ep_url: str):
    """Run the full workflow in the background and stream messages to the job store."""
    condition = jobs[job_id]["message_event"]

    loop = asyncio.get_running_loop()

    def on_message(msg: dict) -> None:
        jobs[job_id]["conversation"].append(msg)
        loop.create_task(_notify(condition))

    result = await run_workflow(ep_url, on_message=on_message)
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
