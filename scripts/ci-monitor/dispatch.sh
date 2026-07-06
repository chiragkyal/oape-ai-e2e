#!/usr/bin/env bash
# dispatch.sh — Reads ci-monitor-result.json and invokes further oape-ai-e2e
# tools based on the failure classification.
#
# This script is the bridge between "CI monitoring" (monitor.sh) and
# "further processing" (auto-fix, Claude, retest). It runs immediately
# after monitor.sh in the same CI job, with the oape-ai-e2e repo cloned
# and available at OAPE_ROOT.
#
# Required environment:
#   RESULT_FILE  — Path to ci-monitor-result.json (default: /tmp/ci-monitor-result.json)
#
# Optional environment:
#   OAPE_ROOT              — Root of the cloned oape-ai-e2e repo (default: /app)
#   DRY_RUN                — If "true", log actions without executing them
#   PHASE                  — Override dispatch phase (default: "2")
#   RETEST_INFRA_FLAKES    — If "true", post /test for infra flakes (default: "false")
#   MAX_RETESTS_PER_RUN    — Max retest comments per run (default: 2)
#   WORK_DIR               — Working directory with CI logs (default: /tmp/ci-monitor)

set -euo pipefail

RESULT_FILE="${RESULT_FILE:-/tmp/ci-monitor-result.json}"
OAPE_ROOT="${OAPE_ROOT:-/app}"
DRY_RUN="${DRY_RUN:-false}"
PHASE="${PHASE:-2}"
RETEST_INFRA_FLAKES="${RETEST_INFRA_FLAKES:-false}"
MAX_RETESTS_PER_RUN="${MAX_RETESTS_PER_RUN:-2}"
WORK_DIR="${WORK_DIR:-/tmp/ci-monitor}"
REPORT_MARKER="<!-- oape-ci-monitor -->"

# ---------------------------------------------------------------------------
# Prechecks
# ---------------------------------------------------------------------------
if [[ ! -f "$RESULT_FILE" ]]; then
  echo "[dispatch] No result file found at ${RESULT_FILE} — nothing to dispatch"
  exit 0
fi

if ! command -v jq &>/dev/null; then
  echo "[dispatch] ERROR: jq is not installed" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Read result
# ---------------------------------------------------------------------------
OVERALL_STATUS=$(jq -r '.overall_status' "$RESULT_FILE")
TRIGGER_COUNT=$(jq '.trigger_actions | length' "$RESULT_FILE")
PR_URL=$(jq -r '.pr_url' "$RESULT_FILE")
OWNER=$(jq -r '.owner' "$RESULT_FILE")
REPO=$(jq -r '.repo' "$RESULT_FILE")
PR_NUMBER=$(jq -r '.pr_number' "$RESULT_FILE")

echo "============================================"
echo "  OAPE CI Monitor — Dispatch"
echo "  PR: ${PR_URL}"
echo "  Status: ${OVERALL_STATUS}"
echo "  Trigger Actions: ${TRIGGER_COUNT}"
echo "  Phase: ${PHASE}"
echo "  Dry Run: ${DRY_RUN}"
echo "  Retest Infra Flakes: ${RETEST_INFRA_FLAKES}"
echo "============================================"

# ---------------------------------------------------------------------------
# If all passed, nothing to dispatch
# ---------------------------------------------------------------------------
if [[ "$OVERALL_STATUS" == "passed" ]]; then
  echo "[dispatch] All CI checks passed — no further action needed"
  exit 0
fi

if [[ "$TRIGGER_COUNT" -eq 0 ]]; then
  echo "[dispatch] No trigger actions in result — nothing to dispatch"
  exit 0
fi

# ---------------------------------------------------------------------------
# Pre-compute: are ALL failures infra-flakes?
# ---------------------------------------------------------------------------
ALL_INFRA_FLAKE="false"
non_retest_count=$(jq '[.trigger_actions[] | select(.action != "retest")] | length' "$RESULT_FILE")
if [[ "$non_retest_count" -eq 0 && "$TRIGGER_COUNT" -gt 0 ]]; then
  ALL_INFRA_FLAKE="true"
fi

# ---------------------------------------------------------------------------
# Dispatch each action
# ---------------------------------------------------------------------------
echo "[dispatch] Processing ${TRIGGER_COUNT} trigger action(s)..."
echo ""

ACTIONS_TAKEN_FILE="${WORK_DIR}/dispatch-actions.txt"
: > "$ACTIONS_TAKEN_FILE"
RETEST_COUNT_FILE="${WORK_DIR}/retest-count.txt"
echo 0 > "$RETEST_COUNT_FILE"

# Use process substitution instead of pipe to avoid subshell variable scoping
while IFS= read -r entry; do
  action=$(echo "$entry" | jq -r '.action')
  job=$(echo "$entry" | jq -r '.job')

  echo "[dispatch] Action: ${action} | Job: ${job}"

  case "$action" in

    # --- Retest: post /test for infra flakes ---
    retest)
      RETEST_COUNT=$(cat "$RETEST_COUNT_FILE")
      if [[ "$RETEST_INFRA_FLAKES" != "true" ]]; then
        echo "  -> Auto-retest disabled (set RETEST_INFRA_FLAKES=true to enable)"
      elif [[ "$ALL_INFRA_FLAKE" != "true" ]]; then
        echo "  -> Skipping retest: not all failures are infra-flakes (mixed failure types)"
      elif [[ "$RETEST_COUNT" -ge "$MAX_RETESTS_PER_RUN" ]]; then
        echo "  -> Retest limit reached (${RETEST_COUNT}/${MAX_RETESTS_PER_RUN})"
      else
        # Extract short job name (strip pull-ci-<owner>-<repo>-<branch>- prefix)
        # shellcheck disable=SC2001
        short_name=$(echo "$job" | sed "s/^pull-ci-${OWNER}-${REPO}-[^-]*-//")
        if [[ -z "$short_name" || "$short_name" == "$job" ]]; then
          echo "  -> WARN: Could not extract short job name, falling back to /retest"
          short_name=""
        fi

        if [[ -n "$short_name" ]]; then
          retest_cmd="/test ${short_name}"
        else
          retest_cmd="/retest"
        fi

        if [[ "$DRY_RUN" != "true" ]]; then
          echo "  -> Posting '${retest_cmd}' for infra-flake: ${job}"
          gh pr comment "$PR_NUMBER" --repo "${OWNER}/${REPO}" \
            --body "$retest_cmd" 2>/dev/null || true
          echo "posted \`${retest_cmd}\` for infra-flake \`${job}\`" >> "$ACTIONS_TAKEN_FILE"
        else
          echo "  -> DRY RUN: Would post '${retest_cmd}' for ${job}"
        fi
        echo $((RETEST_COUNT + 1)) > "$RETEST_COUNT_FILE"
      fi
      ;;

    # --- Auto-fix for lint failures ---
    auto-fix-lint)
      auto_fix_script="${OAPE_ROOT}/scripts/pr-agent/auto-fix.sh"
      if [[ ! -x "$auto_fix_script" ]]; then
        echo "  -> Auto-fix script not found at ${auto_fix_script}"
      else
        echo "  -> Running auto-fix for lint failure: ${job}"
        fix_output=""
        fix_args=(--pr-url "$PR_URL" --category lint-failure --job "$job" --log-dir "$WORK_DIR")
        if [[ "$DRY_RUN" == "true" ]]; then
          fix_args+=(--dry-run)
        fi

        if fix_output=$("$auto_fix_script" "${fix_args[@]}" 2>&1); then
          echo "$fix_output"
          fix_sha=$(echo "$fix_output" | grep -oP 'Pushed fix: \K[a-f0-9]+' || true)
          if [[ -n "$fix_sha" ]]; then
            echo "auto-fixed \`lint-failure\` (commit ${fix_sha})" >> "$ACTIONS_TAKEN_FILE"
          elif [[ "$DRY_RUN" != "true" ]]; then
            echo "auto-fix attempted for \`lint-failure\` on \`${job}\` (no changes needed)" >> "$ACTIONS_TAKEN_FILE"
          fi
        else
          echo "$fix_output"
          echo "  -> Auto-fix failed for ${job} (non-fatal, continuing)"
        fi
      fi
      ;;

    # --- Auto-fix for generated files (make generate/manifests) ---
    auto-fix-generated)
      auto_fix_script="${OAPE_ROOT}/scripts/pr-agent/auto-fix.sh"
      if [[ ! -x "$auto_fix_script" ]]; then
        echo "  -> Auto-fix script not found at ${auto_fix_script}"
      else
        echo "  -> Running auto-fix for generated files: ${job}"
        fix_output=""
        fix_args=(--pr-url "$PR_URL" --category trivial-generated-files --job "$job" --log-dir "$WORK_DIR")
        if [[ "$DRY_RUN" == "true" ]]; then
          fix_args+=(--dry-run)
        fi

        if fix_output=$("$auto_fix_script" "${fix_args[@]}" 2>&1); then
          echo "$fix_output"
          fix_sha=$(echo "$fix_output" | grep -oP 'Pushed fix: \K[a-f0-9]+' || true)
          if [[ -n "$fix_sha" ]]; then
            echo "auto-fixed \`trivial-generated-files\` (commit ${fix_sha})" >> "$ACTIONS_TAKEN_FILE"
          elif [[ "$DRY_RUN" != "true" ]]; then
            echo "auto-fix attempted for \`trivial-generated-files\` on \`${job}\` (no changes needed)" >> "$ACTIONS_TAKEN_FILE"
          fi
        else
          echo "$fix_output"
          echo "  -> Auto-fix failed for ${job} (non-fatal, continuing)"
        fi
      fi
      ;;

    # --- Investigate: Claude analysis for complex failures ---
    investigate)
      echo "  -> Claude analysis not yet available (Step 4 — pending PR #60 merge)"
      ;;

    *)
      echo "  -> Unknown action: ${action} — skipping"
      ;;
  esac

  echo ""
done < <(jq -c '.trigger_actions[]' "$RESULT_FILE")

# ---------------------------------------------------------------------------
# Post-dispatch report update
# ---------------------------------------------------------------------------
if [[ -s "$ACTIONS_TAKEN_FILE" && "$DRY_RUN" != "true" ]]; then
  echo "[dispatch] Updating CI monitor report with actions taken..."

  existing_comment_id=$(gh api "repos/${OWNER}/${REPO}/issues/${PR_NUMBER}/comments" \
    --jq ".[] | select(.body | contains(\"${REPORT_MARKER}\")) | .id" 2>/dev/null | head -1 || true)

  if [[ -n "$existing_comment_id" ]]; then
    existing_body=$(gh api "repos/${OWNER}/${REPO}/issues/comments/${existing_comment_id}" \
      --jq '.body' 2>/dev/null || true)

    actions_section=$'\n---\n### Actions Taken by oape-ci-monitor\n'
    while IFS= read -r line; do
      actions_section+="- ${line}"$'\n'
    done < "$ACTIONS_TAKEN_FILE"
    actions_section+=$'\n*Updated on '"$(date -u +'%Y-%m-%d %H:%M UTC')"'*'

    updated_body="${existing_body}${actions_section}"
    gh api "repos/${OWNER}/${REPO}/issues/comments/${existing_comment_id}" \
      -X PATCH -f body="$updated_body" > /dev/null 2>&1 || true
    echo "[dispatch] Report updated with actions taken"
  else
    echo "[dispatch] WARN: Could not find CI monitor comment to update"
  fi
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo "[dispatch] Dispatch complete"

CATEGORY_SUMMARY=$(jq -r '
  .failure_categories
  | to_entries
  | map("\(.key): \(.value)")
  | join(", ")' "$RESULT_FILE")

echo "[dispatch] Failure categories: ${CATEGORY_SUMMARY}"

if [[ -s "$ACTIONS_TAKEN_FILE" ]]; then
  echo "[dispatch] Actions taken:"
  while IFS= read -r line; do
    echo "  - ${line}"
  done < "$ACTIONS_TAKEN_FILE"
else
  echo "[dispatch] No actions were executed this run"
fi
