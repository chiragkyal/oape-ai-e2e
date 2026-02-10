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

---

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

# Then, generate the controller implementation
/oape:api-implement https://github.com/openshift/enhancements/pull/1234
```

## Prerequisites

- **gh** (GitHub CLI) -- installed and authenticated
- **go** -- Go toolchain
- **git** -- Git
- **make** -- Make (for api-implement)
- Must be run from within an OpenShift operator repository

## Conventions Enforced

- [OpenShift API Conventions](https://github.com/openshift/enhancements/blob/master/dev-guide/api-conventions.md)
- [Kubernetes API Conventions](https://github.com/kubernetes/community/blob/master/contributors/devel/sig-architecture/api-conventions.md)
- [Kubebuilder Controller Patterns](https://book.kubebuilder.io/cronjob-tutorial/controller-implementation)
- [Controller-Runtime Best Practices](https://pkg.go.dev/sigs.k8s.io/controller-runtime)
