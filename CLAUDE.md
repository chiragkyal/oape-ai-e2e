# CLAUDE.md - OAPE AI E2E Feature Development

This document provides context for Claude to work with the OAPE AI E2E Feature Development tools.

## Purpose

This project provides AI-driven tools for end-to-end feature development in OpenShift operators. The workflow takes an Enhancement Proposal (EP) and generates:
1. API type definitions (Go structs)
2. Controller/reconciler implementation code

## Commands

| Command | Purpose |
|---------|---------|
| `/oape:api-generate <EP-URL>` | Generate Go API types from Enhancement Proposal |
| `/oape:api-implement <EP-URL>` | Generate controller code from Enhancement Proposal + API types |

## Typical Workflow

```bash
# 1. Navigate to an operator repository
cd /path/to/operator-repo

# 2. Generate API types first
/oape:api-generate https://github.com/openshift/enhancements/pull/XXXX

# 3. Generate controller implementation
/oape:api-implement https://github.com/openshift/enhancements/pull/XXXX

# 4. Build and verify
make generate && make manifests && make build && make test
```

---

## Supported Operator Repositories

These repositories can be used to test the OAPE commands. Clone any of them and run the commands from within.

### Cert-Manager Operators

| Repository | Description | Framework |
|------------|-------------|-----------|
| [openshift/cert-manager-operator](https://github.com/openshift/cert-manager-operator) | Manages cert-manager installation on OpenShift | controller-runtime |
| [openshift/jetstack-cert-manager](https://github.com/openshift/jetstack-cert-manager) | Core cert-manager (upstream fork) | controller-runtime |
| [openshift/cert-manager-istio-csr](https://github.com/openshift/cert-manager-istio-csr) | Certificate signing for Istio service mesh | controller-runtime |

### External Secrets Operators

| Repository | Description | Framework |
|------------|-------------|-----------|
| [openshift/external-secrets-operator](https://github.com/openshift/external-secrets-operator) | Manages external-secrets on OpenShift | controller-runtime |
| [openshift/external-secrets](https://github.com/openshift/external-secrets) | Core external-secrets (upstream fork) | controller-runtime |

### Additional Test Repositories

| Repository | Description | Framework |
|------------|-------------|-----------|
| [openshift/cluster-ingress-operator](https://github.com/openshift/cluster-ingress-operator) | Good example of controller-runtime patterns | controller-runtime |
| [openshift/cluster-authentication-operator](https://github.com/openshift/cluster-authentication-operator) | Good example of library-go patterns | library-go |

---

## Quick Clone Commands

```bash
# Cert-Manager Operators
git clone --filter=blob:none https://github.com/openshift/cert-manager-operator.git
git clone --filter=blob:none https://github.com/openshift/jetstack-cert-manager.git
git clone --filter=blob:none https://github.com/openshift/cert-manager-istio-csr.git

# External Secrets Operators
git clone --filter=blob:none https://github.com/openshift/external-secrets-operator.git
git clone --filter=blob:none https://github.com/openshift/external-secrets.git
```

---

## Operator Framework Detection

The commands automatically detect which framework the repository uses:

| Framework | Detection | Code Pattern |
|-----------|-----------|--------------|
| **controller-runtime** | `sigs.k8s.io/controller-runtime` in go.mod | `Reconcile(ctx, req) (Result, error)` |
| **library-go** | `github.com/openshift/library-go` in go.mod | `sync(ctx, syncCtx) error` |

---

## Project Structure


---

## Skills

| Skill | Purpose |
|-------|---------|
| `effective-go` | Ensures generated Go code follows official best practices |

---

## Prerequisites

Before running commands, ensure:

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

- Always run `/oape:api-generate` before `/oape:api-implement`
- The commands READ existing code patterns and replicate them
- Generated code follows the repository's existing style
- API types are NOT modified by `api-implement` (only reads them)
