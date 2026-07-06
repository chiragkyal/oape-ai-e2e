#!/usr/bin/env bash
# auto-fix.sh — Standalone auto-fix engine for the OAPE CI Monitor.
#
# Clones a PR's repo, applies a deterministic fix for a specific failure
# category, verifies the fix compiles, and pushes it. Called by dispatch.sh
# after monitor.sh classifies failures.
#
# Usage:
#   auto-fix.sh --pr-url <URL> --category <category> [options]
#
# Required:
#   --pr-url <URL>       PR URL (https://github.com/OWNER/REPO/pull/N)
#   --category <cat>     Fix category: trivial-format, trivial-import,
#                        trivial-lint, trivial-generated-files,
#                        lint-failure (coarse — refined via log analysis)
#
# Optional:
#   --job <name>         Prow job name (for audit logging)
#   --log-dir <path>     Directory containing CI log files (for fine-grained classification)
#   --dry-run            Show what would be done without committing/pushing

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=scripts/pr-agent/safety.sh
source "${SCRIPT_DIR}/safety.sh"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BOT_USER="${BOT_USER:-openshift-app-platform-shift-bot}"
DRY_RUN="${DRY_RUN:-false}"
RUNNER_TEMP="${RUNNER_TEMP:-/tmp}"

OWNER=""
REPO=""
PR_NUMBER=""
CURRENT_PR_URL=""

# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------
usage() {
  echo "Usage: auto-fix.sh --pr-url <URL> --category <category> [--job <name>] [--log-dir <path>] [--dry-run]"
  echo ""
  echo "Categories: trivial-format, trivial-import, trivial-lint, trivial-generated-files, lint-failure"
  exit 1
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
PR_URL_ARG=""
CATEGORY=""
JOB_NAME=""
LOG_DIR=""

# shellcheck disable=SC2034
while [[ $# -gt 0 ]]; do
  case "$1" in
    --pr-url)    PR_URL_ARG="$2"; shift 2 ;;
    --category)  CATEGORY="$2"; shift 2 ;;
    --job)       JOB_NAME="$2"; shift 2 ;;
    --log-dir)   LOG_DIR="$2"; shift 2 ;;
    --dry-run)   DRY_RUN="true"; shift ;;
    --help|-h)   usage ;;
    *)           echo "[auto-fix] ERROR: Unknown argument: $1" >&2; usage ;;
  esac
done

if [[ -z "$PR_URL_ARG" ]]; then
  echo "[auto-fix] ERROR: --pr-url is required" >&2
  usage
fi

if [[ -z "$CATEGORY" ]]; then
  echo "[auto-fix] ERROR: --category is required" >&2
  usage
fi

case "$CATEGORY" in
  trivial-format|trivial-import|trivial-lint|trivial-generated-files|lint-failure) ;;
  *)
    echo "[auto-fix] ERROR: Unsupported category: ${CATEGORY}" >&2
    echo "[auto-fix] Supported: trivial-format, trivial-import, trivial-lint, trivial-generated-files, lint-failure" >&2
    exit 1
    ;;
esac

# ---------------------------------------------------------------------------
# parse_pr_url — extract owner/repo/pr_number from PR URL
# ---------------------------------------------------------------------------
parse_pr_url() {
  local url="$1"
  if [[ "$url" =~ https://github.com/([^/]+)/([^/]+)/pull/([0-9]+) ]]; then
    OWNER="${BASH_REMATCH[1]}"
    REPO="${BASH_REMATCH[2]}"
    PR_NUMBER="${BASH_REMATCH[3]}"
  elif [[ "$url" =~ ^([^/]+)/([^#]+)#([0-9]+)$ ]]; then
    OWNER="${BASH_REMATCH[1]}"
    REPO="${BASH_REMATCH[2]}"
    PR_NUMBER="${BASH_REMATCH[3]}"
  else
    echo "[auto-fix] ERROR: Invalid PR URL format: $url" >&2
    exit 1
  fi
  CURRENT_PR_URL="https://github.com/${OWNER}/${REPO}/pull/${PR_NUMBER}"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
parse_pr_url "$PR_URL_ARG"

echo "============================================"
echo "  OAPE Auto-Fix"
echo "  PR: ${CURRENT_PR_URL}"
echo "  Category: ${CATEGORY}"
echo "  Job: ${JOB_NAME:-n/a}"
echo "  Dry Run: ${DRY_RUN}"
echo "============================================"

# --- Clone + checkout ---
workdir="${RUNNER_TEMP}/auto-fix-${OWNER}-${REPO}-${PR_NUMBER}"
if [[ -d "$workdir" ]]; then
  rm -rf "$workdir"
fi

echo "[auto-fix] Cloning ${OWNER}/${REPO}..."
if ! gh_retry gh repo clone "${OWNER}/${REPO}" "$workdir" -- --filter=blob:none --single-branch 2>/dev/null; then
  echo "[auto-fix] ERROR: Failed to clone ${OWNER}/${REPO}" >&2
  audit_log "error" "$CATEGORY" "" "" "clone failed for ${OWNER}/${REPO}"
  exit 1
fi

cd "$workdir"

if ! gh pr checkout "$PR_NUMBER" 2>/dev/null; then
  echo "[auto-fix] ERROR: Failed to checkout PR #${PR_NUMBER}" >&2
  audit_log "error" "$CATEGORY" "" "" "checkout failed for PR #${PR_NUMBER}"
  exit 1
fi

git config user.name "$BOT_USER"
git config user.email "267347085+${BOT_USER}@users.noreply.github.com"
git remote set-url origin "https://x-access-token:${GH_TOKEN}@github.com/${OWNER}/${REPO}.git"

base_branch=$(gh pr view "$PR_NUMBER" --repo "${OWNER}/${REPO}" --json baseRefName -q .baseRefName 2>/dev/null || echo "main")
git fetch origin "${base_branch}" --depth=1 2>/dev/null || true

echo "[auto-fix] On branch: $(git branch --show-current), base: ${base_branch}"

# --- Fine-grained classification from log files ---
# When dispatch.sh sends the coarse "lint-failure" category, refine it
# by reading the actual CI log files.
refine_lint_category() {
  local log_dir="$1"
  local job="$2"

  if [[ -z "$log_dir" || ! -d "$log_dir" ]]; then
    echo "trivial-format"
    return
  fi

  local log_id
  log_id=$(echo "$job" | tr '/ ' '__')
  local log_file="${log_dir}/log-${log_id}.txt"

  if [[ ! -s "$log_file" ]]; then
    for f in "${log_dir}"/log-*.txt; do
      [[ -s "$f" ]] && log_file="$f" && break
    done
  fi

  if [[ ! -s "$log_file" ]]; then
    echo "trivial-format"
    return
  fi

  local content
  content=$(cat "$log_file")

  if echo "$content" | grep -qiE 'generated code is out of date|make generate|make manifests|deepcopy-gen|zz_generated|boilerplate'; then
    echo "trivial-generated-files"
  elif echo "$content" | grep -qiE 'imported and not used|could not import|import ordering'; then
    echo "trivial-import"
  elif echo "$content" | grep -qiE 'golangci-lint|golint|staticcheck|revive'; then
    echo "trivial-lint"
  elif echo "$content" | grep -qiE 'gofmt|goimports|formatting differs|diff.*\.go'; then
    echo "trivial-format"
  else
    echo "trivial-format"
  fi
}

EFFECTIVE_CATEGORY="$CATEGORY"
if [[ "$CATEGORY" == "lint-failure" ]]; then
  EFFECTIVE_CATEGORY=$(refine_lint_category "$LOG_DIR" "$JOB_NAME")
  echo "[auto-fix] Refined lint-failure → ${EFFECTIVE_CATEGORY} (from log analysis)"
fi

# --- Apply fix ---
echo "[auto-fix] Applying fix for: ${EFFECTIVE_CATEGORY}"

changed_go_files=$(git diff --name-only "origin/${base_branch}" -- '*.go' 2>/dev/null || true)

case "$EFFECTIVE_CATEGORY" in
  trivial-format)
    if [[ -n "$changed_go_files" ]]; then
      echo "$changed_go_files" | xargs -r go fmt 2>/dev/null || true
      if command -v goimports &>/dev/null; then
        echo "$changed_go_files" | xargs -r goimports -w 2>/dev/null || true
      fi
    else
      echo "[auto-fix] No Go files changed in this PR"
    fi
    ;;

  trivial-import)
    if [[ -n "$changed_go_files" ]]; then
      if command -v goimports &>/dev/null; then
        echo "[auto-fix] Running goimports on PR-changed Go files"
        echo "$changed_go_files" | xargs -r goimports -w 2>/dev/null || true
      else
        echo "[auto-fix] goimports not available, falling back to go fmt"
        echo "$changed_go_files" | xargs -r go fmt 2>/dev/null || true
      fi
    else
      echo "[auto-fix] No Go files changed in this PR"
    fi
    ;;

  trivial-lint)
    if command -v golangci-lint &>/dev/null; then
      echo "[auto-fix] Running golangci-lint --fix"
      golangci-lint run --fix ./... 2>/dev/null || true
    else
      echo "[auto-fix] golangci-lint not available, skipping"
      audit_log "skipped" "$EFFECTIVE_CATEGORY" "" "" "golangci-lint not available"
      exit 0
    fi
    ;;

  trivial-generated-files)
    if [[ -f go.mod ]] && grep -q 'sigs.k8s.io/controller-runtime' go.mod; then
      echo "[auto-fix] Detected controller-runtime, running make generate && make manifests"
      make generate 2>/dev/null || true
      make manifests 2>/dev/null || true
    elif [[ -f go.mod ]] && grep -q 'github.com/openshift/library-go' go.mod; then
      echo "[auto-fix] Detected library-go, running make update"
      make update 2>/dev/null || true
    else
      echo "[auto-fix] Unknown framework, trying make generate then make update"
      make generate 2>/dev/null || make update 2>/dev/null || true
    fi
    ;;
esac

# --- Check for changes ---
modified_files=$(git diff --name-only; git ls-files --others --exclude-standard)
if [[ -z "$modified_files" ]]; then
  echo "[auto-fix] No changes after applying ${EFFECTIVE_CATEGORY} fix"
  audit_log "info" "$EFFECTIVE_CATEGORY" "" "" "no changes produced"
  exit 0
fi

echo "[auto-fix] Modified files:"
echo "$modified_files" | while IFS= read -r f; do echo "  $f"; done

# --- Safety checks ---
if ! check_blocklist "$modified_files" "$EFFECTIVE_CATEGORY"; then
  echo "[auto-fix] Blocklist violation on modified files, reverting" >&2
  git checkout -- . 2>/dev/null || true
  git clean -fd 2>/dev/null || true
  audit_log "reverted" "$EFFECTIVE_CATEGORY" "$modified_files" "" "post-fix blocklist violation"
  exit 1
fi

if ! check_diff_size; then
  echo "[auto-fix] Diff too large, reverting" >&2
  git checkout -- . 2>/dev/null || true
  git clean -fd 2>/dev/null || true
  audit_log "reverted" "$EFFECTIVE_CATEGORY" "$modified_files" "" "diff too large"
  exit 1
fi

echo "[auto-fix] Verifying fix compiles..."
if ! go build ./... 2>/dev/null; then
  echo "[auto-fix] Fix broke compilation, reverting" >&2
  git checkout -- . 2>/dev/null || true
  git clean -fd 2>/dev/null || true
  audit_log "reverted" "$EFFECTIVE_CATEGORY" "$modified_files" "" "fix broke compilation"
  exit 1
fi

if ! go vet ./... 2>/dev/null; then
  echo "[auto-fix] Fix failed go vet, reverting" >&2
  git checkout -- . 2>/dev/null || true
  git clean -fd 2>/dev/null || true
  audit_log "reverted" "$EFFECTIVE_CATEGORY" "$modified_files" "" "fix failed go vet"
  exit 1
fi

# --- Dry-run gate ---
if [[ "$DRY_RUN" == "true" ]]; then
  echo "[auto-fix] DRY RUN: Would commit and push fix for ${EFFECTIVE_CATEGORY}"
  echo "[auto-fix] DRY RUN: Modified files:"
  echo "$modified_files" | while IFS= read -r f; do echo "  $f"; done
  audit_log "dry-run" "$EFFECTIVE_CATEGORY" "$modified_files" "" "would commit and push"
  git checkout -- . 2>/dev/null || true
  git clean -fd 2>/dev/null || true
  exit 0
fi

# --- Commit + push ---
if ! check_commit_limit 0; then
  echo "[auto-fix] Commit limit reached, skipping push" >&2
  audit_log "skipped" "$EFFECTIVE_CATEGORY" "$modified_files" "" "commit limit reached"
  git checkout -- . 2>/dev/null || true
  git clean -fd 2>/dev/null || true
  exit 1
fi

git diff --name-only -z | xargs -0 -r git add
git ls-files --others --exclude-standard -z | xargs -0 -r git add
git commit -m "fix: ${EFFECTIVE_CATEGORY} — auto-fix by oape-ci-monitor"

sha=$(git rev-parse HEAD)

if ! git pull --rebase origin HEAD 2>/dev/null; then
  echo "[auto-fix] Rebase conflict — concurrent push detected, aborting" >&2
  git rebase --abort 2>/dev/null || true
  git reset --hard HEAD~1 2>/dev/null || true
  audit_log "reverted" "$EFFECTIVE_CATEGORY" "$modified_files" "$sha" "rebase conflict — concurrent push detected"
  exit 1
fi

git push origin HEAD
increment_commit_count > /dev/null

audit_log "auto-fix" "$EFFECTIVE_CATEGORY" "$modified_files" "$sha" "success"
echo "[auto-fix] Pushed fix: ${sha} (${EFFECTIVE_CATEGORY})"
