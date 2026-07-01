---
name: PR Agent Safety
description: Safety guardrails for the OAPE PR Lifecycle Agent
---

# PR Agent Safety Guardrails

## File Modification Rules
- NEVER modify: *.key, *.pem, *.crt, *.env, credentials.*, kubeconfig,
  Dockerfile, Containerfile, .github/workflows/*, .tekton/*, Makefile,
  rbac/*.yaml, clusterrole*.yaml, go.mod, go.sum
- NEVER create files outside pkg/, internal/, api/, cmd/, test/

## Git Operation Rules
- NEVER use git push --force, git push -f, git rebase, git reset --hard
- Push only when explicitly instructed. Default: do NOT push.
- ALWAYS verify: go build ./... && go vet ./... before committing

## Change Scope Rules
- Minimal changes only — only modify what the review comment requests
- One commit per thread, max 500 lines changed
- Follow existing code style, naming conventions, and import organization

## Response Rules
- One response per thread — never respond via both inline AND general comment
- Keep replies under 200 words
- Admit uncertainty rather than making a potentially wrong change

## Commit Message Format
- fix: <description> — oape-pr-agent
