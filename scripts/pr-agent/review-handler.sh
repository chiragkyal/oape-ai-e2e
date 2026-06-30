#!/usr/bin/env bash
# review-handler.sh — Standalone bot that addresses PR review comments
# using Claude Code CLI in agentic mode.
#
# Usage:
#   review-handler.sh --pr-url https://github.com/org/repo/pull/123 [--dry-run]
#
# Requires: gh (authenticated), claude CLI, python3, jq, git

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Source shared safety guardrails
# shellcheck source=safety.sh
source "$SCRIPT_DIR/safety.sh"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BOT_USER="${BOT_USER:-openshift-app-platform-shift-bot}"
DRY_RUN="${DRY_RUN:-false}"
OAPE_ROOT="${OAPE_ROOT:-$REPO_ROOT}"
PLUGINS_DIR="${PLUGINS_DIR:-${OAPE_ROOT}/plugins/oape/skills}"
SKIP_USERS="${SKIP_USERS:-openshift-ci,openshift-bot,dependabot,codecov,sonarcloud}"
CLAUDE_TIMEOUT="${CLAUDE_TIMEOUT:-300}"

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
PR_URL_ARG=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --pr-url)
      PR_URL_ARG="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN="true"
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "Usage: review-handler.sh --pr-url <URL> [--dry-run]" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$PR_URL_ARG" ]]; then
  echo "Usage: review-handler.sh --pr-url <URL> [--dry-run]" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Parse PR URL into OWNER, REPO, PR_NUMBER
# ---------------------------------------------------------------------------
parse_pr_url() {
  local url="$1"
  if [[ "$url" =~ github\.com/([^/]+)/([^/]+)/pull/([0-9]+) ]]; then
    OWNER="${BASH_REMATCH[1]}"
    REPO="${BASH_REMATCH[2]}"
    PR_NUMBER="${BASH_REMATCH[3]}"
  else
    echo "ERROR: Cannot parse PR URL: $url" >&2
    exit 1
  fi
}

# ---------------------------------------------------------------------------
# Graceful degradation: check prerequisites
# ---------------------------------------------------------------------------
if ! command -v claude &>/dev/null; then
  echo "[review] Claude CLI not available — skipping review comment handling"
  exit 0
fi

if ! command -v python3 &>/dev/null; then
  echo "[review] python3 not available — skipping review comment handling"
  exit 0
fi

if ! command -v jq &>/dev/null; then
  echo "[review] jq not available — skipping review comment handling" >&2
  exit 1
fi

if [[ -z "${GH_TOKEN:-}" ]]; then
  echo "[review] GH_TOKEN not set — cannot authenticate for push/comment" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# build_threads — Invoke build_threads.py to fetch/filter/group comments
# ---------------------------------------------------------------------------
build_threads() {
  local owner="$1" repo="$2" pr_number="$3"
  local output_file="${RUNNER_TEMP:-/tmp}/review-threads-${owner}-${repo}-${pr_number}.json"

  python3 "${PLUGINS_DIR}/address-review-comments/build_threads.py" \
    --owner "$owner" --repo "$repo" --pr "$pr_number" \
    --bot-user "$BOT_USER" \
    --skip-users "$SKIP_USERS" \
    --max-comment-size 5000 \
    --output "$output_file" \
    || { echo "[review] Thread building failed" >&2; return 1; }

  echo "$output_file"
}

# ---------------------------------------------------------------------------
# clone_and_checkout — Clone repo and checkout the PR branch
# ---------------------------------------------------------------------------
clone_and_checkout() {
  local owner="$1" repo="$2" pr_number="$3"
  local workdir="${RUNNER_TEMP:-/tmp}/review-${owner}-${repo}-${pr_number}"

  if [[ -d "$workdir/.git" ]]; then
    cd "$workdir"
    git pull --ff-only 2>/dev/null || true
  else
    gh_retry gh repo clone "${owner}/${repo}" "$workdir" -- --filter=blob:none --single-branch
    cd "$workdir"
    gh pr checkout "$pr_number"
    git config user.name "$BOT_USER"
    git config user.email "267347085+${BOT_USER}@users.noreply.github.com"

    # For fork-based PRs, push to the fork (head repo), not the upstream
    local head_repo
    head_repo=$(gh pr view "$pr_number" --repo "${owner}/${repo}" --json headRepository,headRepositoryOwner \
      -q '"\(.headRepositoryOwner.login)/\(.headRepository.name)"' 2>/dev/null || echo "${owner}/${repo}")
    PUSH_REMOTE_URL="https://x-access-token:${GH_TOKEN}@github.com/${head_repo}.git"
    git remote set-url origin "$PUSH_REMOTE_URL"
  fi
}

# ---------------------------------------------------------------------------
# address_thread — Use Claude to address a single review thread
# ---------------------------------------------------------------------------
address_thread() {
  local thread_json="$1"
  local thread_id file thread_type
  thread_id=$(echo "$thread_json" | jq -r '.thread_id')
  file=$(echo "$thread_json" | jq -r '.file // empty')
  thread_type=$(echo "$thread_json" | jq -r '.type')

  local thread_file="${RUNNER_TEMP:-/tmp}/thread-${thread_id}.json"
  echo "$thread_json" | jq '.comments' > "$thread_file"
  local head_before
  head_before=$(git rev-parse HEAD)

  local file_diff=""
  if [[ -n "$file" ]]; then
    file_diff=$(git diff "origin/${BASE_BRANCH}...HEAD" -- "$file" 2>/dev/null || echo "(diff not available)")
  fi

  local commit_messages
  commit_messages=$(gh pr view "$PR_NUMBER" --repo "${OWNER}/${REPO}" \
    --json commits -q '.commits[] | "- \(.messageHeadline)"' 2>/dev/null || echo "")

  local check_replied="${PLUGINS_DIR}/address-review-comments/check_replied.py"
  local safety_content=""
  local skill_content=""

  safety_content=$(sed '/^---$/,/^---$/d' "${PLUGINS_DIR}/pr-agent-safety/SKILL.md" 2>/dev/null || echo "")
  skill_content=$(sed '/^---$/,/^---$/d' "${PLUGINS_DIR}/address-review-comments/SKILL.md" 2>/dev/null || echo "")

  # Check commit limit — if reached, Claude can still post explanation-only replies
  local pr_commits commit_limit_note=""
  pr_commits=$(cat "${RUNNER_TEMP:-/tmp}/pr-review-commits-${PR_NUMBER}.txt" 2>/dev/null || echo 0)
  if ! check_commit_limit "$pr_commits" 2>/dev/null; then
    commit_limit_note="
COMMIT LIMIT REACHED: Do NOT make code changes or push commits for this thread.
You may ONLY post an explanation-only reply. If the reviewer requested a code change,
explain that the automated commit limit has been reached and a human will address it."
  fi

  local prompt
  prompt="You are the OAPE PR agent responding to a review comment on PR #${PR_NUMBER} in ${OWNER}/${REPO}.
The PR branch is checked out in the current directory.

SAFETY GUIDELINES:
${safety_content}

REVIEW COMMENT GUIDANCE:
${skill_content}

INSTRUCTIONS:
- If code change requested: edit, verify (go build ./... && go vet ./...), commit (fix: <desc> — oape-pr-agent), reply.
- Do NOT push. All commits will be pushed in a single batch after all threads are processed.
- If question: reply with explanation only. Do NOT change code.
- Reply exactly once per thread. End every reply with:
---
*AI-assisted response via Claude Code*
- Before posting any reply, run: python3 ${check_replied} ${OWNER} ${REPO} ${PR_NUMBER} <comment_id> --type <type>
  Exit 1 or 2 = do NOT post.
- If unsure about the requested change, explain your uncertainty instead of guessing.
${commit_limit_note}
THREAD CONTEXT (${thread_type}):
$(cat "$thread_file")"

  if [[ -n "$file" ]] && [[ -n "$file_diff" ]]; then
    prompt="${prompt}

FILE DIFF (${file}):
${file_diff}"
  fi

  if [[ -n "$commit_messages" ]]; then
    prompt="${prompt}

PR COMMITS:
${commit_messages}"
  fi

  local claude_stderr="${RUNNER_TEMP:-/tmp}/claude-review-stderr-${thread_id}.txt"
  local prompt_file="${RUNNER_TEMP:-/tmp}/claude-prompt-${thread_id}.txt"
  printf '%s' "$prompt" > "$prompt_file"
  local claude_exit=0
  timeout "$CLAUDE_TIMEOUT" claude \
    -p \
    --permission-mode bypassPermissions \
    --allowedTools "Bash(git diff*),Bash(git add*),Bash(git commit*),Bash(git log*),Bash(git status*),Bash(git stash*),Bash(go *),Bash(make *),Bash(gh api*),Bash(gh pr comment*),Bash(python3*),Read,Edit" \
    < "$prompt_file" \
    2>"$claude_stderr" || claude_exit=$?

  if [[ "$claude_exit" -ne 0 ]]; then
    echo "[review] Claude exited with code ${claude_exit} for thread ${thread_id}"
  fi
  if [[ -s "$claude_stderr" ]]; then
    echo "[review] Claude stderr for thread ${thread_id}:"
    cat "$claude_stderr"
  fi

  local new_commits
  new_commits=$(git rev-list --count HEAD ^"$head_before" 2>/dev/null || echo 0)
  if [[ "$new_commits" -gt 0 ]]; then
    pr_commits=$((pr_commits + new_commits))
    echo "$pr_commits" > "${RUNNER_TEMP:-/tmp}/pr-review-commits-${PR_NUMBER}.txt"
    for ((i = 0; i < new_commits; i++)); do
      increment_commit_count > /dev/null
    done
    audit_log "review-addressed" "review-code-change" "$file" "$(git rev-parse HEAD)" "pushed fix for thread ${thread_id}"
  else
    audit_log "review-addressed" "review-explanation" "$file" "" "replied to thread ${thread_id}"
  fi
}

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
main() {
  parse_pr_url "$PR_URL_ARG"
  CURRENT_PR_URL="$PR_URL_ARG"
  export CURRENT_PR_URL

  echo "============================================"
  echo "  OAPE Review Handler"
  echo "  PR: ${OWNER}/${REPO}#${PR_NUMBER}"
  echo "  Dry Run: ${DRY_RUN}"
  echo "============================================"

  local threads_file
  threads_file=$(build_threads "$OWNER" "$REPO" "$PR_NUMBER") || exit 0

  local processable total
  processable=$(jq '[.[] | select(.action == "process")] | length' "$threads_file" 2>/dev/null || echo 0)
  total=$(jq 'length' "$threads_file" 2>/dev/null || echo 0)
  echo "[review] Found ${total} thread(s), ${processable} need attention"

  if [[ "$processable" -eq 0 ]]; then
    echo "[review] No actionable threads — done"
    exit 0
  fi

  if [[ "$DRY_RUN" == "true" ]]; then
    echo "[review] DRY RUN: Would address ${processable} thread(s)"
    jq -r '.[] | select(.action == "process") | "[review] Would address thread \(.thread_id) (\(.type)) on \(.file // "PR-level")"' "$threads_file"
    exit 0
  fi

  clone_and_checkout "$OWNER" "$REPO" "$PR_NUMBER"
  BASE_BRANCH=$(gh pr view "$PR_NUMBER" --repo "${OWNER}/${REPO}" --json baseRefName -q .baseRefName 2>/dev/null || echo "main")
  git fetch origin "${BASE_BRANCH}" --deepen=50 2>/dev/null || true

  echo "0" > "${RUNNER_TEMP:-/tmp}/pr-review-commits-${PR_NUMBER}.txt"

  local addressed=0
  while IFS= read -r thread; do
    local tid
    tid=$(echo "$thread" | jq -r '.thread_id')
    echo "[review] Addressing thread ${tid}..."
    address_thread "$thread"
    addressed=$((addressed + 1))
    echo "[review] Thread ${tid} — done (${addressed}/${processable})"
  done < <(jq -c '.[] | select(.action == "process")' "$threads_file")

  echo "[review] Addressed ${addressed} thread(s)"

  # Batch push: single push for all commits across all threads
  local total_commits
  total_commits=$(cat "${RUNNER_TEMP:-/tmp}/pr-review-commits-${PR_NUMBER}.txt" 2>/dev/null || echo 0)
  if [[ "$total_commits" -gt 0 ]]; then
    echo "[review] Rebasing onto latest remote before push..."
    local branch_name
    branch_name=$(git branch --show-current)
    git fetch origin "$branch_name" 2>/dev/null || true
    if ! git rebase "origin/${branch_name}" 2>/dev/null; then
      echo "[review] Rebase conflict — aborting rebase and pushing without rebase" >&2
      git rebase --abort 2>/dev/null || true
    fi
    echo "[review] Pushing ${total_commits} commit(s)..."
    if ! git push origin HEAD; then
      echo "[review] Push failed — attempting force-push with lease..." >&2
      git push --force-with-lease origin HEAD
    fi

    # Post-push verification
    local local_sha remote_sha branch_name
    local_sha=$(git log -1 --format='%H')
    branch_name=$(git branch --show-current)
    remote_sha=$(git ls-remote origin "refs/heads/${branch_name}" | cut -f1)
    if [[ "$local_sha" == "$remote_sha" ]]; then
      echo "[review] Push verified — ${local_sha}"
    else
      echo "[review] WARNING: Push verification failed — local ${local_sha} != remote ${remote_sha}" >&2
    fi
  else
    echo "[review] No commits to push"
  fi
}

main
