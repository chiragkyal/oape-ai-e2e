# oape Plugin

AI-driven OpenShift operator development tools, following OpenShift and Kubernetes API conventions.

## Commands

### `/oape:api-generate`

Reads an OpenShift enhancement proposal PR, extracts the required API changes, and generates compliant Go type definitions in the correct paths of the current OpenShift operator repository.

**Usage:**
```shell
/oape:api-generate https://github.com/openshift/enhancements/pull/1234
```

**What it does:**
1. **Prechecks** -- Validates the PR URL, required tools (`gh`, `go`, `git`), GitHub authentication, repository type (must be an OpenShift operator repo with `openshift/api` dependency), and PR accessibility. Fails immediately if any precheck fails.
2. **Knowledge Refresh** -- Fetches and internalizes the latest OpenShift and Kubernetes API conventions before generating any code.
3. **Enhancement Analysis** -- Reads the enhancement proposal to extract API group, version, kinds, fields, validation requirements, feature gate info, and whether it is a configuration or workload API.
4. **Code Generation** -- Generates or modifies Go type definitions following conventions derived from the authoritative documents and patterns from the existing codebase.
5. **FeatureGate Registration** -- Adds FeatureGate to `features.go` when applicable.

### `/oape:api-generate-tests`

Generates `.testsuite.yaml` integration test files for OpenShift API type definitions. Reads Go types, CRD manifests, and validation markers to produce comprehensive test suites.

**Usage:**
```shell
/oape:api-generate-tests api/v1alpha1/myresource_types.go
```

**What it does:**
1. **Prechecks** -- Verifies the repository, identifies target API types, and checks for CRD manifests.
2. **Type Analysis** -- Reads Go types to extract fields, validation markers, enums, unions, immutability rules, and feature gates.
3. **Test Generation** -- Generates test cases covering: minimal valid create, valid/invalid field values, update scenarios, immutable fields, singleton name validation, discriminated unions, feature-gated fields, and status subresource tests.
4. **File Output** -- Writes `.testsuite.yaml` files following the repo's existing naming and directory conventions.

### `/oape:api-implement`

Reads an OpenShift enhancement proposal PR, extracts the required implementation logic, and generates complete controller/reconciler code following controller-runtime and operator-sdk conventions.

**Usage:**
```shell
/oape:api-implement https://github.com/openshift/enhancements/pull/1234
```

**What it does:**
1. **Prechecks** -- Validates the PR URL, required tools (`gh`, `go`, `git`, `make`), GitHub authentication, repository type (controller-runtime or library-go), and PR accessibility.
2. **Knowledge Refresh** -- Fetches and internalizes the latest controller-runtime patterns and operator best practices.
3. **Enhancement Analysis** -- Reads the enhancement proposal to extract business logic requirements, reconciliation workflow, conditions, events, and error handling.
4. **Pattern Detection** -- Identifies the controller layout pattern used in the repository.
5. **Code Generation** -- Generates complete Reconcile() logic, SetupWithManager, finalizer handling, status updates, and event recording.
6. **Controller Registration** -- Adds the new controller to the manager.

**Typical Workflow:**
```shell
# First, generate the API types
/oape:api-generate https://github.com/openshift/enhancements/pull/1234

# Then, generate integration tests for the new types
/oape:api-generate-tests api/v1alpha1/myresource_types.go

# Then, generate the controller implementation
/oape:api-implement https://github.com/openshift/enhancements/pull/1234
```

---

### `/oape:review`

Performs a "Principal Engineer" level code review that verifies code changes against Jira requirements.

**Usage:**
```shell
/oape:review OCPBUGS-12345
/oape:review OCPBUGS-12345 origin/release-4.15
```

**What it does:**
1. **Fetches Jira Issue** -- Retrieves the ticket details and acceptance criteria
2. **Analyzes Git Diff** -- Gets changes between base ref and HEAD
3. **Reviews Code** -- Applies four review modules:
   - **Golang Logic & Safety**: Intent matching, execution traces, edge cases, context usage, concurrency, error handling
   - **Bash Scripts**: Safety patterns, variable quoting, temp file handling
   - **Operator Metadata (OLM)**: RBAC updates, finalizer handling
   - **Build Consistency**: Generation drift detection
4. **Generates Report** -- Returns structured JSON with verdict, issues, and fix prompts
5. **Applies Fixes Automatically** -- When issues are found, invokes `implement-review-fixes.md` to apply the suggested code changes in severity order (CRITICAL first), then verifies the build still passes

## Prerequisites

- **gh** (GitHub CLI) -- installed and authenticated
- **go** -- Go toolchain
- **git** -- Git
- **make** -- Make (for api-implement)
- **curl** -- For fetching Jira issues (for review)
- Must be run from within an OpenShift operator repository

## Conventions Enforced

- [OpenShift API Conventions](https://github.com/openshift/enhancements/blob/master/dev-guide/api-conventions.md)
- [Kubernetes API Conventions](https://github.com/kubernetes/community/blob/master/contributors/devel/sig-architecture/api-conventions.md)
- [Kubebuilder Controller Patterns](https://book.kubebuilder.io/cronjob-tutorial/controller-implementation)
- [Controller-Runtime Best Practices](https://pkg.go.dev/sigs.k8s.io/controller-runtime)
