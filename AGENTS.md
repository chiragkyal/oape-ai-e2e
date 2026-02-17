# OAPE AI E2E Feature Development

This document provides context for the AI agent when executing OAPE commands.

## Purpose

This project provides AI-driven tools for end-to-end feature development in OpenShift operators. The workflow takes an Enhancement Proposal (EP) and generates:
1. API type definitions (Go structs)
2. Integration tests for the API types
3. Controller/reconciler implementation code

## Commands

| Command | Purpose |
| ------- | ------- |
| `init` | Clone an allowed operator repo by short name |
| `api-generate` | Generate Go API types from Enhancement Proposal |
| `api-generate-tests` | Generate integration test suites for API types |
| `api-implement` | Generate controller code from Enhancement Proposal + API types |
| `e2e-generate` | Generate e2e test artifacts from git diff against base branch |
| `review` | Production-grade code review against Jira requirements |
| `implement-review-fixes` | Automatically apply fixes from a review report |

## Typical Workflow

```bash
# 1. Clone an operator repository
command: init
prompt: cert-manager-operator

# 2. Generate API types
command: api-generate
prompt: https://github.com/openshift/enhancements/pull/XXXX

# 3. Generate integration tests for the API types
command: api-generate-tests
prompt: api/v1alpha1/

# 4. Generate controller implementation
command: api-implement
prompt: https://github.com/openshift/enhancements/pull/XXXX

# 5. Build and verify
# (run in operator repo): make generate && make manifests && make build && make test

# 6. Generate e2e tests for your changes
command: e2e-generate
prompt: main
```

---

## Supported Operator Repositories

The allowed repositories and their base branches are defined in [`team-repos.csv`](team-repos.csv). DO NOT raise PRs on any repos beyond that list. Always read `team-repos.csv` to determine the correct repo URL and base branch before cloning or creating branches.

---

## Operator Framework Detection

The commands automatically detect which framework the repository uses:

| Framework | Detection | Code Pattern |
| --------- | --------- | ------------ |
| **controller-runtime** | `sigs.k8s.io/controller-runtime` in go.mod | `Reconcile(ctx, req) (Result, error)` |
| **library-go** | `github.com/openshift/library-go` in go.mod | `sync(ctx, syncCtx) error` |

---

## Project Structure

```
oape-ai-e2e/
├── AGENTS.md               # This file - AI agent instructions
├── team-repos.csv          # Allowed operator repositories
├── plugins/oape/           # Command and skill definitions
│   ├── commands/           # Command logic (loaded as context)
│   ├── skills/             # Reusable knowledge modules
│   └── e2e-test-generator/ # Fixtures and examples
├── server/                 # FastAPI server (Vertex AI)
└── deploy/                 # Kubernetes deployment
```

---

## Prerequisites

Before running commands, ensure the working directory has:

- **gh** (GitHub CLI) - installed and authenticated (`gh auth login`)
- **go** - Go toolchain installed
- **git** - Git installed
- **make** - Make installed

---

## Key Conventions

When generating code, these conventions are followed:

1. **OpenShift API Conventions** - [dev-guide/api-conventions.md](https://github.com/openshift/enhancements/blob/master/dev-guide/api-conventions.md)
2. **Kubernetes API Conventions** - [sig-architecture/api-conventions.md](https://github.com/kubernetes/community/blob/master/contributors/devel/sig-architecture/api-conventions.md)
3. **Effective Go** - [go.dev/doc/effective_go](https://go.dev/doc/effective_go)
4. **Kubebuilder Patterns** - [book.kubebuilder.io](https://book.kubebuilder.io/)

---

## Important Notes

- Always run `api-generate` before `api-generate-tests` or `api-implement`
- The commands READ existing code patterns and replicate them
- Generated code follows the repository's existing style
- API types are NOT modified by `api-generate-tests` or `api-implement` (they only read them)

---

## Tool Capabilities

You have access to these tools:

| Tool | Description |
| ---- | ----------- |
| `bash` | Execute shell commands in working directory |
| `read_file` | Read file contents |
| `write_file` | Write/create files |
| `edit_file` | Search and replace in files |
| `glob` | Find files by pattern |
| `grep` | Search file contents with regex |
| `web_fetch` | Fetch URL contents (GitHub, docs, etc.) |

Use these tools to explore the repository, fetch enhancement proposals, and generate code.
