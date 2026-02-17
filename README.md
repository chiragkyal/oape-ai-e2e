# OAPE AI E2E

AI-driven end-to-end feature development tools for OpenShift operators.

## Overview

OAPE (OpenShift AI-Powered Engineering) provides AI-driven tools that take an Enhancement Proposal (EP) and generate:
1. **API type definitions** (Go structs)
2. **Integration tests** for API types
3. **Controller/reconciler** implementation code
4. **E2E test artifacts**

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         OAPE Server (FastAPI)                           │
│                                                                         │
│  POST /api/v1/run                     GET /stream/{job_id}              │
│  { command, prompt, working_dir }     (SSE streaming)                   │
└───────────────────────────────────────┬─────────────────────────────────┘
                                        │
                                        ▼
         ┌─────────────────────────────────────────────────┐
         │            Google Vertex AI API                 │
         │         (Claude / Anthropic Models)             │
         └─────────────────────────────────────────────────┘
                                        │
                                        ▼
         ┌─────────────────────────────────────────────────┐
         │  plugins/oape/commands/*.md  (Command Logic)    │
         │  plugins/oape/skills/*.md    (Reusable Skills)  │
         │  (Loaded as system prompt context)              │
         └─────────────────────────────────────────────────┘
```

## Quick Start

### 1. Install Dependencies

```bash
cd server
pip install -r requirements.txt
```

### 2. Configure GCP Credentials

```bash
export ANTHROPIC_VERTEX_PROJECT_ID="your-gcp-project-id"
export CLOUD_ML_REGION="us-east5"
export GOOGLE_APPLICATION_CREDENTIALS="$HOME/.config/gcloud/application_default_credentials.json"
```

### 3. Run Server

```bash
uvicorn main:app --reload --port 8000
```

### 4. Use the API

**Web UI:** Open http://localhost:8000

**API Call:**
```bash
curl -X POST http://localhost:8000/api/v1/run \
  -H "Content-Type: application/json" \
  -d '{
    "command": "api-implement",
    "prompt": "https://github.com/openshift/enhancements/pull/1234",
    "working_dir": "/path/to/operator/repo"
  }'
```

## Available Commands

| Command | Description | Prompt Example |
|---------|-------------|----------------|
| `init` | Clone an operator repository | `cert-manager-operator` |
| `api-generate` | Generate API types from EP | `https://github.com/openshift/enhancements/pull/1234` |
| `api-generate-tests` | Generate integration tests | `api/v1alpha1/` |
| `api-implement` | Generate controller code | `https://github.com/openshift/enhancements/pull/1234` |
| `e2e-generate` | Generate e2e test artifacts | `main` (base branch) |
| `review` | Code review against Jira | `OCPBUGS-12345` |
| `implement-review-fixes` | Apply fixes from report | `<report-path>` |

## Typical Workflow

```bash
# 1. Clone the operator repository
curl -X POST http://localhost:8000/api/v1/run \
  -H "Content-Type: application/json" \
  -d '{"command": "init", "prompt": "cert-manager-operator"}'

# 2. Generate API types from enhancement proposal
curl -X POST http://localhost:8000/api/v1/run \
  -H "Content-Type: application/json" \
  -d '{
    "command": "api-generate",
    "prompt": "https://github.com/openshift/enhancements/pull/1234",
    "working_dir": "/path/to/cert-manager-operator"
  }'

# 3. Generate integration tests
curl -X POST http://localhost:8000/api/v1/run \
  -H "Content-Type: application/json" \
  -d '{
    "command": "api-generate-tests",
    "prompt": "api/v1alpha1/",
    "working_dir": "/path/to/cert-manager-operator"
  }'

# 4. Generate controller implementation
curl -X POST http://localhost:8000/api/v1/run \
  -H "Content-Type: application/json" \
  -d '{
    "command": "api-implement",
    "prompt": "https://github.com/openshift/enhancements/pull/1234",
    "working_dir": "/path/to/cert-manager-operator"
  }'

# 5. Build and verify (run in operator repo)
make generate && make manifests && make build && make test

# 6. Generate e2e tests
curl -X POST http://localhost:8000/api/v1/run \
  -H "Content-Type: application/json" \
  -d '{
    "command": "e2e-generate",
    "prompt": "main",
    "working_dir": "/path/to/cert-manager-operator"
  }'
```

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | GET | Web UI |
| `/submit` | POST | Submit async job (returns job_id) |
| `/status/{job_id}` | GET | Poll job status |
| `/stream/{job_id}` | GET | SSE stream of conversation |
| `/api/v1/run` | POST | Run command (sync, waits for completion) |
| `/api/v1/commands` | GET | List available commands |

## Project Structure

```
oape-ai-e2e/
├── AGENTS.md               # AI agent instructions (system prompt)
├── team-repos.csv          # Allowed operator repositories
├── plugins/oape/           # Command and skill definitions
│   ├── commands/           # Command logic (loaded as context)
│   │   ├── init.md
│   │   ├── api-generate.md
│   │   ├── api-implement.md
│   │   └── ...
│   ├── skills/             # Reusable knowledge modules
│   │   ├── effective-go/
│   │   └── e2e-test-generator/
│   └── e2e-test-generator/ # Fixtures and examples
├── server/                 # FastAPI server
│   ├── main.py             # API endpoints
│   ├── vertex_client.py    # Vertex AI client
│   ├── context_loader.py   # Loads MD files as context
│   ├── tools/              # Tool implementations
│   └── README.md
├── deploy/                 # Kubernetes deployment
│   └── deployment.yaml
└── Dockerfile
```

## Supported Repositories

Defined in [`team-repos.csv`](team-repos.csv):

| Product | Repository |
|---------|------------|
| cert-manager Operator | openshift/cert-manager-operator |
| cert-manager Operator | openshift/jetstack-cert-manager |
| cert-manager Operator | openshift/cert-manager-istio-csr |
| External Secrets Operator | openshift/external-secrets-operator |

## Framework Detection

The server auto-detects the operator framework:

| Framework | Detection | Code Pattern |
|-----------|-----------|--------------|
| **controller-runtime** | `sigs.k8s.io/controller-runtime` in go.mod | `Reconcile(ctx, req) (Result, error)` |
| **library-go** | `github.com/openshift/library-go` in go.mod | `sync(ctx, syncCtx) error` |

## Docker Deployment

```bash
# Build
docker build -t oape-server .

# Run
docker run -p 8000:8000 \
  -e ANTHROPIC_VERTEX_PROJECT_ID="your-project" \
  -e CLOUD_ML_REGION="us-east5" \
  -v $HOME/.config/gcloud:/secrets/gcloud:ro \
  -e GOOGLE_APPLICATION_CREDENTIALS=/secrets/gcloud/application_default_credentials.json \
  oape-server
```

## Kubernetes Deployment

```bash
# Update secrets in deploy/deployment.yaml
kubectl apply -f deploy/deployment.yaml
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_VERTEX_PROJECT_ID` | Yes | GCP project ID |
| `CLOUD_ML_REGION` | No | GCP region (default: `us-east5`) |
| `GOOGLE_APPLICATION_CREDENTIALS` | Yes | Path to GCP credentials JSON |

## Conventions Enforced

- [OpenShift API Conventions](https://github.com/openshift/enhancements/blob/master/dev-guide/api-conventions.md)
- [Kubernetes API Conventions](https://github.com/kubernetes/community/blob/master/contributors/devel/sig-architecture/api-conventions.md)
- [Kubebuilder Controller Patterns](https://book.kubebuilder.io/)
- [Effective Go](https://go.dev/doc/effective_go)

## Prerequisites

- Python 3.11+
- GCP project with Vertex AI enabled
- GCP credentials with Vertex AI access
- For operator work: `gh`, `go`, `git`, `make`

## License

See [LICENSE](LICENSE).
