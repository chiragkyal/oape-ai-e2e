---
description: Production-grade OpenShift code reviewer that validates logic, safety, OLM, and build consistency against Jira requirements
argument-hint: <ticket_id> [base_ref]
---

## Name
oape:review

## Synopsis
```shell
/oape:review <ticket_id> [base_ref]
```

## Description

The `oape:review` command performs a "Principal Engineer" level code review. It verifies that the code **actually solves the Jira problem** (Logic) and follows OpenShift safety standards.

The review covers four key modules:
- **Golang Logic & Safety**: Intent matching, execution traces, edge cases, context usage, concurrency, error handling
- **Bash Scripts**: Safety patterns, variable quoting, temp file handling
- **Operator Metadata (OLM)**: RBAC updates, finalizer handling
- **Build Consistency**: Generation drift detection for types and CRDs

## Arguments

- `$1` (ticket_id_or_NO_TICKET): The Jira Ticket ID (e.g., OCPBUGS-12345) **OR** the literal string `NO_TICKET`. **Required.**
  - When `NO_TICKET` is provided, the review skips Jira validation and focuses on code quality, safety, and build consistency only.
- `$2` (base_ref): The base git ref to diff against. Defaults to `origin/master`. **Optional.**


## Implementation

### Step 1: Determine Base Ref
- If `$2` (base_ref) is provided, use it
- If NOT provided, use `origin/master`

```bash
BASE_REF="${2:-origin/master}"
```

### Step 2: Fetch Context
1. **Jira Issue** (skip if `$1` is `NO_TICKET`):
   - If `$1` is NOT `NO_TICKET`, fetch the Jira issue details using curl:
     ```bash
     curl -s "https://issues.redhat.com/browse/$1"
     ```
     Focus on Acceptance Criteria as the primary validation source.
   - If `$1` IS `NO_TICKET`, skip Jira fetching entirely. The review will focus
     on code quality (Modules A-D) without validating against Jira acceptance criteria.
     In the Logic Verification module, skip the "Intent Match" check that compares
     code against Jira requirements.

2. **Git Diff**: Get the code changes:
   ```bash
   git diff ${BASE_REF}...HEAD --stat -p
   ```

3. **File List**: Get list of changed files:
   ```bash
   git diff ${BASE_REF}...HEAD --name-only
   ```

### Step 3: Analyze Code Changes

Apply the following review criteria:

#### Module A: Golang (Logic & Safety)

**Logic Verification (The "Mental Sandbox")**:
- **Intent Match:** (Skip if `NO_TICKET` mode) Does the code implementation match the Jira Acceptance Criteria? Quote the Jira line that justifies the change. In `NO_TICKET` mode, verify that the code changes are internally consistent and logically correct.
- **Execution Trace:** Mentally simulate the function.
    - *Happy Path:* Does it succeed as expected?
    - *Error Path:* If the API fails, does it retry or return an error?
- **Edge Cases:**
    - **Nil/Empty:** Does it handle `nil` pointers or empty slices?
    - **State:** Does it handle resources that are `Deleting` or `Pending`?

**Safety & Patterns**:
- **Context:** REJECT `context.TODO()` in production paths. Must use `context.WithTimeout`.
- **Concurrency:** `go func` must be tracked (WaitGroup/ErrGroup). No race conditions.
- **Errors:** Must use `fmt.Errorf("... %w", err)`. No capitalized error strings.
- **Complexity:** Flag functions > 50 lines or > 3 nesting levels.

**Idiomatic Clean Code (via Golang-Skills):**
- **Slices/Maps:** Ensure slices are pre-allocated with `make` if the length is known. Avoid unnecessary `nil` slice vs. `empty` slice confusion.
- **Interfaces:** Reject "Interface Pollution" (defining interfaces before they are actually used by multiple implementations).
- **Naming:** Follow Go conventions (e.g., `url` not `URL` in mixed-case, `id` not `ID` for local vars, no `Get` prefix).
- **Receiver Types:** Check for consistency in pointer vs. value receivers.

#### Module B: Bash (Scripts)
- **Safety:** Must start with `set -euo pipefail`.
- **Quoting:** Variables in `oc`/`kubectl` commands MUST be quoted (`"$VAR"`).
- **Tmp Files:** Must use `mktemp`, never hardcoded paths like `/tmp/data`.

#### Module C: Operator Metadata (OLM)
- **RBAC:** If new K8s APIs are used in Go, check if `config/rbac/role.yaml` is updated.
- **Finalizers:** If logic deletes resources, ensure Finalizers are handled to prevent hanging.

#### Module D: Build Consistency (The "Gotchas")
- **Generation Drift:**
    - IF `types.go` is modified, AND `zz_generated.deepcopy.go` is NOT in the file list -> **CRITICAL FAIL**.
    - IF `types.go` is modified, AND `config/crd/bases/...yaml` is NOT in the file list -> **CRITICAL FAIL**.

### Step 4: Generate Report
Generate a structured JSON report based on the analysis.

### Step 5: Apply Fixes Automatically

After the report is generated, if the `issues` array is non-empty, automatically apply the suggested fixes by following the procedure in `implement-review-fixes.md`, passing the review report produced in Step 4 as input.

This step is skipped when the verdict is `"Approved"` and there are no issues.

## Return Value

Returns a JSON report with the following structure, followed by an automatic fix summary if issues were found:

```json
{
  "summary": {
    "verdict": "Approved | Changes Requested",
    "rating": "1-10",
    "simplicity_score": "1-10"
  },
  "logic_verification": {
    "jira_intent_met": true,  // Set to null in NO_TICKET mode
    "missing_edge_cases": ["List handled edge cases or gaps (e.g., 'Does not handle pod deletion')"]
  },
  "issues": [
    {
      "severity": "CRITICAL",
      "module": "Logic",
      "file": "pkg/controller/gather.go",
      "line": 45,
      "description": "Logic Error: Jira asks to 'retry on failure', but code returns 'nil' immediately.",
      "fix_prompt": "Update the error handling to use the retry logic..."
    }
  ]
}
```

When issues are present, the fixes are applied automatically and a fix summary is appended (see `implement-review-fixes.md` for the summary format).

## Examples

1. **Review changes against origin/master**:
   ```shell
   /oape:review OCPBUGS-12345
   ```

2. **Review changes against a specific branch**:
   ```shell
   /oape:review OCPBUGS-12345 origin/release-4.15
   ```

3. **Review changes against a specific commit**:
   ```shell
   /oape:review OCPBUGS-12345 abc123def
   ```