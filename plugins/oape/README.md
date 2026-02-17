# OAPE Commands

AI-driven OpenShift operator development tools, following OpenShift and Kubernetes API conventions.

## Commands

### `init`

Clones an allowed OpenShift operator repository by short name into the current directory.

**Prompt:** Repository short name (e.g., `cert-manager-operator`)

**What it does:**
1. Validates the short name against the allowlist
2. Runs `git clone --filter=blob:none`
3. Verifies Go module and detects framework

### `api-generate`

Reads an OpenShift enhancement proposal PR, extracts API changes, and generates compliant Go type definitions.

**Prompt:** Enhancement PR URL (e.g., `https://github.com/openshift/enhancements/pull/1234`)

**What it does:**
1. Fetches and internalizes OpenShift/Kubernetes API conventions
2. Analyzes the enhancement proposal
3. Generates Go type definitions following conventions
4. Adds FeatureGate registration when applicable

### `api-generate-tests`

Generates `.testsuite.yaml` integration test files for OpenShift API type definitions.

**Prompt:** Path to types file (e.g., `api/v1alpha1/myresource_types.go`)

**What it does:**
1. Reads Go types to extract fields, validation markers, enums
2. Generates test cases covering create, update, validation, error scenarios
3. Writes `.testsuite.yaml` files

### `api-implement`

Reads an enhancement proposal and generates complete controller/reconciler code.

**Prompt:** Enhancement PR URL

**What it does:**
1. Fetches controller-runtime patterns and operator best practices
2. Analyzes enhancement for business logic requirements
3. Generates Reconcile() logic, SetupWithManager, finalizers, status updates
4. Registers controller with manager

### `e2e-generate`

Generates e2e test artifacts by analyzing git diff from a base branch.

**Prompt:** Base branch name (e.g., `main`)

**What it does:**
1. Detects framework (controller-runtime vs library-go)
2. Discovers API types, CRDs, existing e2e patterns
3. Analyzes git diff to understand changes
4. Generates test-cases.md, execution-steps.md, e2e_test.go or e2e_test.sh

### `review`

Performs production-grade code review against Jira requirements.

**Prompt:** Jira ticket ID (e.g., `OCPBUGS-12345`)

**What it does:**
1. Fetches Jira issue details
2. Analyzes git diff
3. Reviews: Golang logic, bash scripts, operator metadata, build consistency
4. Generates structured report with fix prompts

### `implement-review-fixes`

Automatically applies fixes from a review report.

**Prompt:** Path to review report

**What it does:**
1. Parses review report
2. Applies fixes in severity order (CRITICAL first)
3. Verifies build still passes

---

## Typical Workflow

```
# API call format: POST /api/v1/run
# { "command": "<command>", "prompt": "<prompt>", "working_dir": "<path>" }

1. init → prompt: "cert-manager-operator"
2. api-generate → prompt: "https://github.com/openshift/enhancements/pull/1234"
3. api-generate-tests → prompt: "api/v1alpha1/"
4. api-implement → prompt: "https://github.com/openshift/enhancements/pull/1234"
5. e2e-generate → prompt: "main"
```

## Prerequisites

- **go** — Go toolchain
- **git** — Git
- **gh** (GitHub CLI) — installed and authenticated
- **make** — Make
- **curl** — For fetching Jira issues (review command)

## Conventions Enforced

- [OpenShift API Conventions](https://github.com/openshift/enhancements/blob/master/dev-guide/api-conventions.md)
- [Kubernetes API Conventions](https://github.com/kubernetes/community/blob/master/contributors/devel/sig-architecture/api-conventions.md)
- [Kubebuilder Controller Patterns](https://book.kubebuilder.io/cronjob-tutorial/controller-implementation)
- [Controller-Runtime Best Practices](https://pkg.go.dev/sigs.k8s.io/controller-runtime)

## Supported Repositories

See [team-repos.csv](../../team-repos.csv) for the list of allowed repositories.
