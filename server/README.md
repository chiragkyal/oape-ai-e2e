# OAPE Server

FastAPI server for OAPE (OpenShift AI-Powered Engineering) commands using direct Vertex AI API calls.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              OAPE Server                                │
│                                                                         │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────────┐  │
│  │   main.py    │───▶│vertex_client │───▶│  Google Vertex AI API    │  │
│  │  (FastAPI)   │    │   .py        │    │  (Claude Models)         │  │
│  └──────────────┘    └──────────────┘    └──────────────────────────┘  │
│         │                   │                                           │
│         │                   ▼                                           │
│         │            ┌──────────────┐                                   │
│         │            │    tools/    │                                   │
│         │            │  executor.py │                                   │
│         │            └──────────────┘                                   │
│         │                   │                                           │
│         ▼                   ▼                                           │
│  ┌──────────────┐    ┌──────────────────────────────────────────────┐  │
│  │context_loader│    │  bash.py │ file_ops.py │ web_fetch.py        │  │
│  │    .py       │    │  (Tool implementations)                      │  │
│  └──────────────┘    └──────────────────────────────────────────────┘  │
│         │                                                               │
│         ▼                                                               │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  plugins/oape/commands/*.md  │  plugins/oape/skills/*.md         │  │
│  │  (Loaded as system prompt context)                                │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

## Files

| File | Purpose |
|------|---------|
| `main.py` | FastAPI application with endpoints |
| `vertex_client.py` | Direct Anthropic API client via Vertex AI |
| `context_loader.py` | Loads MD files as system prompt |
| `config.json` | Server configuration |
| `tools/__init__.py` | Tool exports |
| `tools/executor.py` | Tool router and Anthropic tool definitions |
| `tools/bash.py` | Bash command execution |
| `tools/file_ops.py` | File operations (Read, Write, Edit, Glob, Grep) |
| `tools/web_fetch.py` | HTTP URL fetching |

## Quick Start

### Prerequisites

- Python 3.11+
- Google Cloud project with Vertex AI enabled
- GCP credentials with Vertex AI access

### Local Development

```bash
# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export ANTHROPIC_VERTEX_PROJECT_ID="your-gcp-project-id"
export CLOUD_ML_REGION="us-east5"
export GOOGLE_APPLICATION_CREDENTIALS="$HOME/.config/gcloud/application_default_credentials.json"

# Run server
uvicorn main:app --reload --port 8000
```

### Docker

```bash
# Build
docker build -t oape-server ..

# Run
docker run -p 8000:8000 \
  -e ANTHROPIC_VERTEX_PROJECT_ID="your-project" \
  -e CLOUD_ML_REGION="us-east5" \
  -v $HOME/.config/gcloud:/secrets/gcloud:ro \
  -e GOOGLE_APPLICATION_CREDENTIALS=/secrets/gcloud/application_default_credentials.json \
  oape-server
```

## API Endpoints

### Web UI

```
GET /
```

Interactive web form to run commands.

### Submit Job (Async)

```
POST /submit
Content-Type: application/x-www-form-urlencoded

command=api-implement&prompt=https://github.com/openshift/enhancements/pull/1234&working_dir=/path/to/repo
```

Returns: `{"job_id": "abc123"}`

### Job Status

```
GET /status/{job_id}
```

Returns job status, output, token usage.

### Stream Job (SSE)

```
GET /stream/{job_id}
```

Server-Sent Events stream of conversation messages.

### Run Command (Sync)

```
POST /api/v1/run
Content-Type: application/json

{
  "command": "api-implement",
  "prompt": "https://github.com/openshift/enhancements/pull/1234",
  "working_dir": "/path/to/repo"
}
```

Waits for completion and returns full result.

### List Commands

```
GET /api/v1/commands
```

Returns available OAPE commands.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_VERTEX_PROJECT_ID` | Yes | GCP project ID |
| `CLOUD_ML_REGION` | No | GCP region (default: `us-east5`) |
| `GOOGLE_APPLICATION_CREDENTIALS` | Yes | Path to GCP credentials JSON |

## Available Commands

| Command | Description | Prompt Example |
|---------|-------------|----------------|
| `init` | Clone operator repository | `cert-manager-operator` |
| `api-generate` | Generate API types | EP PR URL |
| `api-generate-tests` | Generate integration tests | `api/v1alpha1/` |
| `api-implement` | Generate controller code | EP PR URL |
| `e2e-generate` | Generate e2e test artifacts | `main` (base branch) |
| `review` | Code review against Jira | `OCPBUGS-12345` |
| `implement-review-fixes` | Apply fixes from report | Report path |

## Tool Capabilities

The AI model can use these tools:

| Tool | Description |
|------|-------------|
| `bash` | Execute shell commands |
| `read_file` | Read file contents |
| `write_file` | Write/create files |
| `edit_file` | Search and replace in files |
| `glob` | Find files by pattern |
| `grep` | Search file contents with regex |
| `web_fetch` | Fetch URL contents |

## How It Works

1. **Request** → User submits command + prompt + working_dir
2. **Context Loading** → `context_loader.py` reads:
   - `AGENTS.md` (base instructions)
   - `team-repos.csv` (allowed repositories)
   - `plugins/oape/skills/*.md` (reusable knowledge)
   - `plugins/oape/commands/{command}.md` (command instructions)
3. **API Call** → `vertex_client.py` sends to Vertex AI:
   - System prompt = combined context
   - User message = "Execute: {command} {prompt}"
   - Tools = available tool definitions
4. **Tool Loop** → When model requests a tool:
   - `tools/executor.py` routes to appropriate tool
   - Result sent back to model
   - Loop continues until model finishes
5. **Response** → Final output returned to user

## Security Considerations

- Commands run with server process permissions
- Working directory is validated before execution
- Command output is truncated to prevent memory issues
- Timeout on bash commands (default 5 minutes)
- File size limits on reads (1MB)

## Extending

### Adding New Tools

1. Create tool class in `tools/`
2. Add to `tools/executor.py`:
   - Add tool definition to `TOOL_DEFINITIONS`
   - Add handler in `ToolExecutor.execute()`
3. Export in `tools/__init__.py`

### Adding New Commands

1. Create `plugins/oape/commands/{command}.md`
2. Add to `COMMAND_FILES` in `context_loader.py`
3. Optionally add command-specific skills to `COMMAND_SKILLS`
