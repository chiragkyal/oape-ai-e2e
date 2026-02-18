"""
FastAPI server for OAPE commands using direct Vertex AI API.

This replaces the claude_agent_sdk-based implementation with direct
API calls to Vertex AI, giving full control over the execution.

Usage:
    uvicorn main:app --reload --port 8000

Endpoints:
    GET  /                          - Homepage with submission form
    POST /submit                    - Submit a job (returns job_id)
    GET  /status/{job_id}           - Poll job status
    GET  /stream/{job_id}           - SSE stream of agent conversation
    GET  /api/v1/commands           - List available commands
    POST /api/v1/run                - Run a command (async with streaming)
"""

import asyncio
import json
import logging
import os
import re
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Form
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from vertex_client import VertexClient, ConversationMessage
from context_loader import load_context, get_available_commands, validate_command
from tools import TOOL_DEFINITIONS, ToolExecutor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="OAPE Operator Feature Developer",
    description=(
        "AI-driven tools for end-to-end feature development in OpenShift operators. "
        "Uses direct Vertex AI API calls with Claude models."
    ),
    version="0.2.0",
)

# Regex patterns for validation
EP_URL_PATTERN = re.compile(
    r"^https://github\.com/openshift/enhancements/pull/\d+/?$"
)

# In-memory job store
jobs: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Request/Response Models
# ---------------------------------------------------------------------------


class RunRequest(BaseModel):
    """Request to run an OAPE command."""

    command: str
    prompt: str
    working_dir: str | None = None


class JobResponse(BaseModel):
    """Response with job ID."""

    job_id: str


class StatusResponse(BaseModel):
    """Job status response."""

    status: str
    command: str
    working_dir: str
    output: str
    error: str | None
    message_count: int
    input_tokens: int
    output_tokens: int


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------


def validate_working_dir(cwd: str | None) -> str:
    """Validate and resolve working directory."""
    working_dir = cwd if cwd else os.getcwd()
    if not os.path.isdir(working_dir):
        raise HTTPException(
            status_code=400,
            detail=f"Working directory does not exist: {working_dir}",
        )
    return os.path.abspath(working_dir)


def validate_ep_url(ep_url: str) -> None:
    """Validate enhancement proposal URL format."""
    if not EP_URL_PATTERN.match(ep_url.rstrip("/")):
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid enhancement PR URL. "
                "Expected: https://github.com/openshift/enhancements/pull/<number>"
            ),
        )


# ---------------------------------------------------------------------------
# Homepage
# ---------------------------------------------------------------------------


HOMEPAGE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OAPE - OpenShift Operator Feature Developer</title>
    <style>
        :root {
            --bg: #0d1117;
            --surface: #161b22;
            --border: #30363d;
            --text: #c9d1d9;
            --text-muted: #8b949e;
            --accent: #58a6ff;
            --accent-hover: #79b8ff;
            --success: #3fb950;
            --error: #f85149;
            --warning: #d29922;
        }
        
        * { box-sizing: border-box; margin: 0; padding: 0; }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.6;
            min-height: 100vh;
        }
        
        .container {
            max-width: 900px;
            margin: 0 auto;
            padding: 2rem;
        }
        
        header {
            text-align: center;
            margin-bottom: 2rem;
            padding-bottom: 1.5rem;
            border-bottom: 1px solid var(--border);
        }
        
        h1 {
            font-size: 2rem;
            font-weight: 600;
            margin-bottom: 0.5rem;
        }
        
        h1 span { color: var(--accent); }
        
        .subtitle {
            color: var(--text-muted);
            font-size: 1rem;
        }
        
        .form-group {
            margin-bottom: 1.5rem;
        }
        
        label {
            display: block;
            margin-bottom: 0.5rem;
            font-weight: 500;
        }
        
        select, input, textarea {
            width: 100%;
            padding: 0.75rem;
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 6px;
            color: var(--text);
            font-size: 1rem;
            font-family: inherit;
        }
        
        select:focus, input:focus, textarea:focus {
            outline: none;
            border-color: var(--accent);
        }
        
        textarea {
            resize: vertical;
            min-height: 100px;
            font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
        }
        
        button {
            background: var(--accent);
            color: #fff;
            border: none;
            padding: 0.75rem 1.5rem;
            border-radius: 6px;
            font-size: 1rem;
            font-weight: 500;
            cursor: pointer;
            transition: background 0.2s;
        }
        
        button:hover { background: var(--accent-hover); }
        button:disabled { opacity: 0.6; cursor: not-allowed; }
        
        #output {
            margin-top: 2rem;
            padding: 1rem;
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 6px;
            font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
            font-size: 0.875rem;
            white-space: pre-wrap;
            max-height: 500px;
            overflow-y: auto;
        }
        
        .status {
            display: inline-block;
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 500;
            text-transform: uppercase;
        }
        
        .status-running { background: var(--warning); color: #000; }
        .status-success { background: var(--success); color: #000; }
        .status-failed { background: var(--error); color: #fff; }
        
        .help-text {
            color: var(--text-muted);
            font-size: 0.875rem;
            margin-top: 0.25rem;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>OAPE Operator Feature Developer</h1>
            <p class="subtitle">Generate controller code from an OpenShift Enhancement Proposal</p>
        </header>
        
        <form id="commandForm">
            <div class="form-group">
                <label for="command">Command</label>
                <select id="command" name="command" required>
                    <option value="api-implement" selected>api-implement</option>
                </select>
            </div>
            
            <div class="form-group">
                <label for="prompt">Enhancement Proposal PR URL</label>
                <input type="text" id="prompt" name="prompt" required
                    placeholder="https://github.com/openshift/enhancements/pull/1234">
            </div>
            
            <div class="form-group">
                <label for="working_dir">Working Directory <span style="color: var(--text-muted);">(optional)</span></label>
                <input type="text" id="working_dir" name="working_dir"
                    placeholder="/path/to/operator-repo">
            </div>
            
            <button type="submit" id="submitBtn">Generate</button>
            <span id="statusBadge" style="margin-left: 1rem;"></span>
        </form>
        
        <div id="output"></div>
    </div>
    
    <script>
        const form = document.getElementById('commandForm');
        const output = document.getElementById('output');
        const submitBtn = document.getElementById('submitBtn');
        const statusBadge = document.getElementById('statusBadge');
        
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const command = document.getElementById('command').value;
            const prompt = document.getElementById('prompt').value;
            const working_dir = document.getElementById('working_dir').value;
            
            output.textContent = 'Starting...\\n';
            submitBtn.disabled = true;
            statusBadge.innerHTML = '<span class="status status-running">Running</span>';
            
            try {
                // Submit job
                const res = await fetch('/submit', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: new URLSearchParams({ command, prompt, working_dir })
                });
                
                if (!res.ok) {
                    const err = await res.json();
                    throw new Error(err.detail || 'Submission failed');
                }
                
                const { job_id } = await res.json();
                output.textContent += `Job ID: ${job_id}\\n\\n`;
                
                // Stream results
                const eventSource = new EventSource(`/stream/${job_id}`);
                
                eventSource.addEventListener('message', (e) => {
                    const msg = JSON.parse(e.data);
                    if (msg.type === 'text') {
                        output.textContent += msg.content + '\\n';
                    } else if (msg.type === 'tool_use') {
                        output.textContent += `[tool: ${msg.tool_name}]\\n`;
                    } else if (msg.type === 'tool_result') {
                        output.textContent += `[result: ${msg.content.substring(0, 200)}...]\\n`;
                    }
                    output.scrollTop = output.scrollHeight;
                });
                
                eventSource.addEventListener('complete', (e) => {
                    const result = JSON.parse(e.data);
                    eventSource.close();
                    submitBtn.disabled = false;
                    
                    if (result.status === 'success') {
                        statusBadge.innerHTML = '<span class="status status-success">Success</span>';
                        output.textContent += '\\n=== COMPLETE ===\\n';
                    } else {
                        statusBadge.innerHTML = '<span class="status status-failed">Failed</span>';
                        output.textContent += `\\n=== FAILED ===\\n${result.error}\\n`;
                    }
                });
                
                eventSource.onerror = () => {
                    eventSource.close();
                    submitBtn.disabled = false;
                    statusBadge.innerHTML = '<span class="status status-failed">Error</span>';
                };
                
            } catch (err) {
                output.textContent += `Error: ${err.message}\\n`;
                submitBtn.disabled = false;
                statusBadge.innerHTML = '<span class="status status-failed">Error</span>';
            }
        });
    </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def homepage():
    """Serve the web UI."""
    return HOMEPAGE_HTML


# ---------------------------------------------------------------------------
# Job Submission & Streaming
# ---------------------------------------------------------------------------


@app.post("/submit", response_model=JobResponse)
async def submit_job(
    command: str = Form(...),
    prompt: str = Form(...),
    working_dir: str = Form(default=""),
):
    """Submit a job to run an OAPE command."""
    # Validate command
    if not validate_command(command):
        raise HTTPException(
            status_code=400,
            detail=f"Unknown command: {command}. Available: {get_available_commands()}",
        )

    # Validate working directory
    resolved_dir = validate_working_dir(working_dir if working_dir else None)

    # Create job
    job_id = uuid.uuid4().hex[:12]
    jobs[job_id] = {
        "status": "running",
        "command": command,
        "prompt": prompt,
        "working_dir": resolved_dir,
        "conversation": [],
        "message_event": asyncio.Condition(),
        "output": "",
        "error": None,
        "input_tokens": 0,
        "output_tokens": 0,
    }

    # Start background task
    asyncio.create_task(_run_job(job_id))

    return JobResponse(job_id=job_id)


@app.get("/status/{job_id}", response_model=StatusResponse)
async def job_status(job_id: str):
    """Get the status of a job."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = jobs[job_id]
    return StatusResponse(
        status=job["status"],
        command=job["command"],
        working_dir=job["working_dir"],
        output=job.get("output", ""),
        error=job.get("error"),
        message_count=len(job.get("conversation", [])),
        input_tokens=job.get("input_tokens", 0),
        output_tokens=job.get("output_tokens", 0),
    )


@app.get("/stream/{job_id}")
async def stream_job(job_id: str):
    """Stream job messages via Server-Sent Events."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator():
        cursor = 0
        condition = jobs[job_id]["message_event"]

        while True:
            # Send new messages
            conversation = jobs[job_id]["conversation"]
            while cursor < len(conversation):
                msg = conversation[cursor]
                yield {
                    "event": "message",
                    "data": json.dumps(
                        {
                            "type": msg.type,
                            "content": msg.content,
                            "tool_name": msg.tool_name,
                        },
                        default=str,
                    ),
                }
                cursor += 1

            # Check completion
            status = jobs[job_id]["status"]
            if status != "running":
                yield {
                    "event": "complete",
                    "data": json.dumps(
                        {
                            "status": status,
                            "output": jobs[job_id].get("output", ""),
                            "error": jobs[job_id].get("error"),
                            "input_tokens": jobs[job_id].get("input_tokens", 0),
                            "output_tokens": jobs[job_id].get("output_tokens", 0),
                        }
                    ),
                }
                return

            # Wait for new messages
            async with condition:
                try:
                    await asyncio.wait_for(condition.wait(), timeout=30.0)
                except asyncio.TimeoutError:
                    yield {"event": "keepalive", "data": ""}

    return EventSourceResponse(event_generator())


async def _run_job(job_id: str):
    """Execute the job in background."""
    job = jobs[job_id]
    condition = job["message_event"]
    loop = asyncio.get_running_loop()

    # Callback for streaming messages
    def on_message(msg: ConversationMessage) -> None:
        job["conversation"].append(msg)
        loop.create_task(_notify(condition))

    try:
        # Load context for the command
        system_prompt = load_context(job["command"])

        # Create Vertex client
        client = VertexClient()

        # Create tool executor
        executor = ToolExecutor(job["working_dir"])

        def tool_executor(name: str, input_data: dict):
            from tools.executor import ToolResult

            result = executor.execute(name, input_data)
            return result

        # Build the full prompt
        full_prompt = f"Execute: /oape:{job['command']} {job['prompt']}"

        # Run the agent
        result = await client.run(
            prompt=full_prompt,
            system_prompt=system_prompt,
            tools=TOOL_DEFINITIONS,
            tool_executor=tool_executor,
            on_message=on_message,
        )

        # Update job with results
        job["output"] = result.output
        job["input_tokens"] = result.input_tokens
        job["output_tokens"] = result.output_tokens

        if result.success:
            job["status"] = "success"
        else:
            job["status"] = "failed"
            job["error"] = result.error

    except Exception as e:
        logger.exception("Job execution failed")
        job["status"] = "failed"
        job["error"] = str(e)

    # Final notification
    async with condition:
        condition.notify_all()


async def _notify(condition: asyncio.Condition) -> None:
    """Notify waiters on condition."""
    async with condition:
        condition.notify_all()


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------


@app.get("/api/v1/commands")
async def list_commands():
    """List available OAPE commands."""
    return {"commands": get_available_commands()}


@app.post("/api/v1/run")
async def run_command(request: RunRequest):
    """Run a command synchronously (waits for completion)."""
    # Validate
    if not validate_command(request.command):
        raise HTTPException(
            status_code=400,
            detail=f"Unknown command: {request.command}",
        )

    working_dir = validate_working_dir(request.working_dir)

    try:
        # Load context
        system_prompt = load_context(request.command)

        # Create client and executor
        client = VertexClient()
        executor = ToolExecutor(working_dir)

        def tool_executor(name: str, input_data: dict):
            return executor.execute(name, input_data)

        # Run
        full_prompt = f"Execute: /oape:{request.command} {request.prompt}"
        result = await client.run(
            prompt=full_prompt,
            system_prompt=system_prompt,
            tools=TOOL_DEFINITIONS,
            tool_executor=tool_executor,
        )

        if not result.success:
            raise HTTPException(status_code=500, detail=result.error)

        return {
            "status": "success",
            "output": result.output,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Command execution failed")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Backward Compatibility
# ---------------------------------------------------------------------------


@app.get("/api/v1/oape-api-implement")
async def api_implement_compat(
    ep_url: str = Query(..., description="Enhancement proposal PR URL"),
    cwd: str = Query(default="", description="Working directory"),
):
    """
    Backward-compatible endpoint for api-implement.
    
    Maintained for compatibility with existing integrations.
    """
    validate_ep_url(ep_url)
    working_dir = validate_working_dir(cwd if cwd else None)

    request = RunRequest(
        command="api-implement",
        prompt=ep_url,
        working_dir=working_dir,
    )

    return await run_command(request)

