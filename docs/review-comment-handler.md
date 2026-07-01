# Review Comment Handler Module

## Context

The CI Monitor (`oape-ci-monitor` Prow presubmit) provides CI failure monitoring via `monitor.sh` + `dispatch.sh`. The Review Comment Handler is a **standalone module** that runs alongside the CI monitor — it is architecturally independent and has no dependencies on other modules (auto-fix, retest, etc.).

This module reads reviewer comments on PRs, determines which need attention, and invokes Claude Code CLI (agentic mode) to either make code changes or post explanations.

### Prior Art: `openshift-eng/ai-helpers` address-review-pr

Adapted from the production-tested [`address-review-pr`](https://github.com/openshift-eng/ai-helpers/tree/main/plugins/openshift-developer/skills/address-review-pr) skill:

- **Two-pass comment fetching** — metadata first, full body only for kept items
- **5-level categorization** — ACTION_INSTRUCTION > BLOCKING > CHANGE_REQUEST > QUESTION > SUGGESTION
- **`check_replied.py`** — stdlib-only Python script (~350 lines) using `gh` CLI subprocess for duplicate reply detection via GraphQL + REST. No pip dependencies.
- **Reply signature** — `*AI-assisted response via Claude Code*` for bot detection

**Adaptations for our CI context:**

| ai-helpers behavior | Our adaptation | Reason |
|---------------------|----------------|--------|
| `--preview` mode (interactive) | Removed | Headless in Prow |
| Amend relevant commits | New commits only | No force-push in CI |
| User-invoked slash command | Triggered as separate Prow step | Runs automatically |
| Bot signatures: `hypershift-jira-solve-ci[bot]` | `openshift-app-platform-shift-bot` | Our bot identity |
| No diff size or commit limits | `safety.sh` guardrails (500 lines, 5 commits/PR) | Automated bounds |

---

## What the User Gets

**Before:** Reviewer comments ("rename this variable", "why did you use a pointer here?") sit unaddressed until a human returns.

**After:** The review handler reads unresolved review threads, filters bot noise, and uses Claude to respond. Code change requests get a commit + push + reply. Questions get an explanation reply.

**Developer experience:**
1. Developer opens PR -> Prow CI runs (including `oape-ci-monitor`)
2. Reviewers leave comments -> next `oape-ci-monitor` run picks them up
3. Bot pushes fix commits for actionable feedback + replies to each thread
4. Bot posts explanations for questions
5. Developer returns to see mechanical feedback already handled

---

## Architecture Decisions

### Decision 1: Separate Prow step (not inside `dispatch.sh`)

**Problem:** `dispatch.sh` exits early when `OVERALL_STATUS == "passed"` (line 67-69) or `TRIGGER_COUNT == 0` (line 72-75). Review comments exist independently of CI status — a PR can have all-green CI but pending review comments.

**Decision:** Add `review-handler.sh` as a separate command in `prow-ci-operator-config.yaml`, after `dispatch.sh`:

```yaml
/app/scripts/ci-monitor/monitor.sh
/app/scripts/ci-monitor/dispatch.sh
/app/scripts/pr-agent/review-handler.sh --pr-url "$PR_URL"
```

This guarantees the review handler runs regardless of CI status. The `entrypoint.sh` integration is a secondary path for on-demand/periodic runs.

**Rejected alternative:** Restructuring `dispatch.sh` to not exit early — couples review handling to CI failure processing unnecessarily.

### Decision 2: Claude in `--print` mode with tool use

The review handler invokes `claude -p` (print mode) with `--permission-mode bypassPermissions` and `--allowedTools`. In print mode, Claude still has full tool access — it autonomously:
- Reads files, makes edits
- Runs `go build ./...` and `go vet ./...`
- Commits via `git commit`
- Posts replies via `gh api`

Print mode is preferred for CI because it processes the prompt, executes tools, and exits deterministically — no interactive session. Tool restrictions via `--allowedTools` prevent destructive operations (push is excluded — all commits are batched and pushed by the outer script). A `timeout 300` wrapper caps each invocation at 5 minutes.

### Decision 3: Claude CLI prerequisite — graceful degradation

The handler checks for `claude --version` at startup and exits 0 with a warning if unavailable. This means it can be deployed before Claude CLI is installed in the container image.

### Decision 4: One Claude invocation per thread

Each review thread gets its own `claude` invocation with `timeout 300`. Per-thread is simpler, more auditable, and prevents one complex thread from consuming the entire budget.

### Decision 5: `check_replied.py` as sole dedup mechanism

Use `check_replied.py` as the **only** duplicate prevention mechanism. It's API-based, works across runs, and requires no state persistence.

**Rejected alternative:** Dual dedup with `addressed[]` state arrays — creates state loading gaps between code paths (Prow step vs `entrypoint.sh`), batched-vs-per-thread update bugs, and dual-mechanism confusion.

### Decision 6: Let Claude categorize (no bash keyword matching)

Pass the raw comment to Claude with the SKILL.md guidance. Claude categorizes using the 5-level system described in the skill. Bash only determines: "has this thread been replied to?" (via `check_replied.py`) and "is this a bot comment?" (via `is_skip_user()`).

**Rejected alternative:** 5-level categorization in bash via keyword regex (~50-100 lines) — Claude does this better, and the full comment text is passed to Claude anyway.

### Decision 7: Thread building in Python (not bash)

The thread grouping logic (parse 3 API response formats, group by `in_reply_to_id`, group by file proximity within 10 lines, filter bots/orphans/oversized) is ~200 lines of JSON manipulation. This is fragile in bash+jq. A `build_threads.py` script handles thread construction using the same stdlib-only, `subprocess`-based pattern as `check_replied.py`.

### Decision 8: Self-contained clone

Always do a fresh blobless clone. Use `git pull --ff-only` (not `--rebase`) to stay consistent with safety rules that forbid rebase.

---

## Prerequisites

1. **`safety.sh` stable** — the review handler sources it for `audit_log()`, `check_commit_limit()`, `gh_retry()`, etc.
2. **GitHub App token** — required for pushing commits. Already set up in `prow-ci-operator-config.yaml` via the `openshift-app-platform-shift-github-bot` credential mount.
3. **Python 3** — available in the UBI9 base image (confirmed in `ci-monitor.Dockerfile`).

**NOT required:** auto-fix module, `dispatch.sh` activation, Node.js/npm (until Claude CLI container step).

---

## Implementation Plan

```
Step 1:  pr-agent-safety SKILL.md (safety rules for Claude prompts)
Step 1b: address-review-comments SKILL.md + check_replied.py + build_threads.py
Step 2:  review-handler.sh (core script — fetch, filter, Claude invoke)
Step 3:  prow-ci-operator-config.yaml (wire as separate Prow step)
Step 4:  entrypoint.sh integration (secondary path for on-demand runs)
Step 5:  safety.sh update (raise MAX_COMMITS_PER_PR to 5)
Step 6:  test-dry-run.sh updates (shellcheck + dry-run validation)
Step 7:  Claude CLI in container image (Dockerfile update)
Step 8:  Report section in entrypoint.sh
```

---

### Step 1: Create `plugins/oape/skills/pr-agent-safety/SKILL.md`

**Purpose:** Safety rules injected into Claude prompts via `cat`. Claude reads these before processing any review thread.

**Content:**

```markdown
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
- ALWAYS use git push origin HEAD (fast-forward only)
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
```

**Files:**
| File | Action |
|------|--------|
| `plugins/oape/skills/pr-agent-safety/SKILL.md` | Create |

---

### Step 1b: Create `plugins/oape/skills/address-review-comments/SKILL.md` + Python utilities

**Purpose:** Guidance skill teaching Claude how to address review comments. Plus two Python utilities for thread building and duplicate detection.

#### SKILL.md

Adapted from [`address-review-pr` skill](https://github.com/openshift-eng/ai-helpers/tree/main/plugins/openshift-developer/skills/address-review-pr). Contains:

- **5-level categorization guidance** — ACTION_INSTRUCTION > BLOCKING > CHANGE_REQUEST > QUESTION > SUGGESTION (Claude applies this, not bash)
- **Making code changes** — read before writing, minimal changes, preserve style, verify compilation, one commit per thread
- **Replying to comments** — template: "Done. [what changed]. [why]", signature, concise factual answers for questions
- **Pre-push verification** — detect Makefile/go.mod, run appropriate verify commands, max 3 retries
- **OpenShift operator conventions** — error handling, status conditions, RBAC markers, generated code reminders

Key difference from upstream: the categorization is guidance for Claude, not bash-side preprocessing.

#### `check_replied.py` — Duplicate Reply Prevention

Copied from [`openshift-eng/ai-helpers`](https://github.com/openshift-eng/ai-helpers/blob/main/plugins/openshift-developer/skills/address-review-pr/check_replied.py), adapted:

- **Stdlib-only** — uses `subprocess` to call `gh` CLI, no pip dependencies
- **~350 lines**
- `BOT_SIGNATURES` updated to include `openshift-app-platform-shift-bot`
- `REPLY_SIGNATURE` kept as `*AI-assisted response via Claude Code*`
- Exit codes: 0 (safe to reply), 1 (already replied), 2 (error — fail safe)

#### `build_threads.py` — Thread Construction (replaces bash `build_thread_list()`)

**Purpose:** Handles thread building in Python instead of ~200 lines of bash+jq.

**Interface:**
```bash
python3 build_threads.py \
  --owner "$OWNER" --repo "$REPO" --pr "$PR_NUMBER" \
  --bot-user "$BOT_USER" \
  --skip-users "openshift-ci,openshift-bot,dependabot,codecov,sonarcloud" \
  --max-comment-size 5000 \
  --output "$RUNNER_TEMP/review-threads.json"
```

**What it does:**
1. **Two-pass fetch via `gh api`** — metadata first (IDs, authors, body length, path, line, original_line), then full body for kept items
2. **Filter** — bot accounts (`is_skip_user`), orphaned comments (`line == null AND original_line == null`), oversized (>5000 chars). `coderabbitai` is NOT filtered (useful code review insights).
3. **Group inline comments** by `in_reply_to_id` into threads
4. **Group by proximity** — inline comments on the same file within 10 lines of each other
5. **Check replied** — calls `check_replied.py` per thread, marks as skip if already replied
6. **Output** — JSON array of thread objects:

```json
[
  {
    "thread_id": 12345,
    "type": "inline|review-summary|top-level",
    "action": "process|skip",
    "skip_reason": "",
    "file": "pkg/controller/reconciler.go",
    "line": 42,
    "comments": [
      {"author": "reviewer", "body": "rename this", "created_at": "...", "id": 111}
    ]
  }
]
```

Note: no `category` field — Claude determines that from the comment text.

**Stdlib-only**, uses `subprocess` for `gh api` calls (same pattern as `check_replied.py` and existing scripts in `plugins/oape/skills/analyze-rfe/scripts/`).

**Files:**
| File | Action |
|------|--------|
| `plugins/oape/skills/address-review-comments/SKILL.md` | Create |
| `plugins/oape/skills/address-review-comments/check_replied.py` | Create (from ai-helpers) |
| `plugins/oape/skills/address-review-comments/build_threads.py` | Create |

---

### Step 2: Create `scripts/pr-agent/review-handler.sh`

**Purpose:** Standalone script that fetches review threads via `build_threads.py`, then invokes agentic Claude per actionable thread.

**Interface:**
```
review-handler.sh --pr-url <URL> [--dry-run]
```

**Script structure (~200 lines):**

1. **Header + argument parsing** — source `safety.sh`, parse `--pr-url`, `--dry-run`, extract owner/repo/pr_number

2. **Claude CLI check** — graceful degradation:
   ```bash
   if ! command -v claude &>/dev/null; then
     echo "[review] Claude CLI not available — skipping review comment handling"
     exit 0
   fi
   ```

3. **`build_threads()` — delegate to Python:**
   ```bash
   build_threads() {
     local owner="$1" repo="$2" pr_number="$3"
     local build_threads_py="${OAPE_ROOT:-/app}/plugins/oape/skills/address-review-comments/build_threads.py"
     local output="${RUNNER_TEMP:-/tmp}/review-threads-${owner}-${repo}-${pr_number}.json"

     python3 "$build_threads_py" \
       --owner "$owner" --repo "$repo" --pr "$pr_number" \
       --bot-user "${BOT_USER:-openshift-app-platform-shift-bot}" \
       --skip-users "${SKIP_USERS:-openshift-ci,openshift-bot,dependabot,codecov,sonarcloud}" \
       --max-comment-size 5000 \
       --output "$output" || { echo "[review] Thread building failed"; return 1; }

     echo "$output"
   }
   ```

4. **`clone_and_checkout()` — self-contained:**
   ```bash
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
       git config user.name "${BOT_USER:-openshift-app-platform-shift-bot}"
       git config user.email "267347085+${BOT_USER:-openshift-app-platform-shift-bot}@users.noreply.github.com"
       git remote set-url origin "https://x-access-token:${GH_TOKEN}@github.com/${owner}/${repo}.git"
     fi
   }
   ```
   Uses `--ff-only` instead of `--rebase` (consistent with safety rules).

5. **`address_thread()` — agentic Claude invocation per thread:**
   ```bash
   address_thread() {
     local thread_json="$1"
     local thread_id file thread_type
     thread_id=$(echo "$thread_json" | jq -r '.thread_id')
     file=$(echo "$thread_json" | jq -r '.file // empty')
     thread_type=$(echo "$thread_json" | jq -r '.type')

     # Check commit limit
     local pr_commits
     pr_commits=$(cat "${RUNNER_TEMP:-/tmp}/pr-review-commits-${PR_NUMBER}.txt" 2>/dev/null || echo 0)
     if ! check_commit_limit "$pr_commits"; then
       audit_log "skipped" "review-comment" "$file" "" "commit limit reached"
       return 0
     fi

     # Write thread context to temp file
     local thread_file="${RUNNER_TEMP:-/tmp}/thread-${thread_id}.json"
     echo "$thread_json" | jq '.comments' > "$thread_file"

     # Record HEAD before Claude runs
     local head_before
     head_before=$(git rev-parse HEAD)

     # File diff for inline comments
     local file_diff=""
     if [[ -n "$file" ]]; then
       file_diff=$(git diff "origin/${BASE_BRANCH}...HEAD" -- "$file" 2>/dev/null || echo "(diff not available)")
     fi

     # Invoke Claude in print mode with tool use
     local skills_dir="${OAPE_ROOT:-/app}/plugins/oape/skills"
     local safety_skill="${skills_dir}/pr-agent-safety/SKILL.md"
     local review_skill="${skills_dir}/address-review-comments/SKILL.md"
     local check_replied="${skills_dir}/address-review-comments/check_replied.py"

     timeout 300 claude \
       -p \
       --permission-mode bypassPermissions \
       --allowedTools "Bash(git diff*),Bash(git add*),Bash(git commit*),Bash(git log*),Bash(git status*),Bash(git stash*),Bash(go *),Bash(make *),Bash(gh api*),Bash(gh pr comment*),Bash(python3*),Read,Edit" \
       < "$prompt_file" \
       2>"${RUNNER_TEMP:-/tmp}/claude-review-stderr-${thread_id}.txt" || claude_exit=$?

     # Check for new commits
     local new_commits
     new_commits=$(git rev-list --count HEAD ^"$head_before" 2>/dev/null || echo 0)
     if [[ "$new_commits" -gt 0 ]]; then
       local sha
       sha=$(git rev-parse HEAD)
       pr_commits=$((pr_commits + new_commits))
       echo "$pr_commits" > "${RUNNER_TEMP:-/tmp}/pr-review-commits-${PR_NUMBER}.txt"
       for ((i = 0; i < new_commits; i++)); do
         increment_commit_count > /dev/null
       done
       audit_log "review-addressed" "review-code-change" "$file" "$sha" "pushed fix for thread ${thread_id}"
     else
       audit_log "review-addressed" "review-explanation" "$file" "" "replied to thread ${thread_id}"
     fi
   }
   ```

   **Design choices:**
   - `timeout 300` wrapper (5 min cap per invocation)
   - `-p` (print mode) with `--permission-mode bypassPermissions` — deterministic exit for CI
   - `Write` excluded from `--allowedTools` (only `Edit` — Claude should modify existing files, not create new ones)
   - No `category` passed — Claude determines it from the comment text

6. **`main()` — orchestration:**
   ```bash
   main() {
     # Graceful degradation
     if ! command -v claude &>/dev/null; then
       echo "[review] Claude CLI not available — skipping"
       exit 0
     fi

     parse_pr_url "$PR_URL_ARG"

     echo "============================================"
     echo "  OAPE Review Handler"
     echo "  PR: ${CURRENT_PR_URL}"
     echo "  Dry Run: ${DRY_RUN}"
     echo "============================================"

     # Build thread list via Python
     local threads_file
     threads_file=$(build_threads "$OWNER" "$REPO" "$PR_NUMBER") || exit 0

     # Count processable threads
     local processable_count total_count
     processable_count=$(jq '[.[] | select(.action == "process")] | length' "$threads_file" 2>/dev/null || echo 0)
     total_count=$(jq 'length' "$threads_file" 2>/dev/null || echo 0)

     echo "[review] Found ${total_count} thread(s), ${processable_count} need attention"

     if [[ "$processable_count" -eq 0 ]]; then
       echo "[review] No actionable review threads — done"
       exit 0
     fi

     if [[ "$DRY_RUN" == "true" ]]; then
       echo "[review] DRY RUN: Would address ${processable_count} thread(s)"
       jq -r '.[] | select(.action == "process") |
         "[review] DRY RUN: Would address thread \(.thread_id) (\(.type)) on \(.file // "PR-level")"' \
         "$threads_file"
       exit 0
     fi

     # Clone and checkout
     clone_and_checkout "$OWNER" "$REPO" "$PR_NUMBER"
     BASE_BRANCH=$(gh pr view "$PR_NUMBER" --repo "${OWNER}/${REPO}" --json baseRefName -q .baseRefName 2>/dev/null || echo "main")
     git fetch origin "${BASE_BRANCH}" --depth=1 2>/dev/null || true

     # Address each thread (process substitution avoids subshell counter bug)
     local addressed=0
     while IFS= read -r thread; do
       local tid
       tid=$(echo "$thread" | jq -r '.thread_id')
       echo "[review] Addressing thread ${tid}..."
       address_thread "$thread"
       addressed=$((addressed + 1))
       echo "[review] Thread ${tid} — done (${addressed}/${processable_count})"
     done < <(jq -c '.[] | select(.action == "process")' "$threads_file")

     echo "[review] Addressed ${addressed} thread(s)"
   }
   ```

   **Bug fixes vs original plan:**
   - `while ... done < <(jq ...)` instead of `| while read` (fixes subshell counter bug)
   - No `addressed[]` state management — `check_replied.py` handles dedup

**Files:**
| File | Action |
|------|--------|
| `scripts/pr-agent/review-handler.sh` | Create (~200 lines) |

---

### Step 3: Wire into `prow-ci-operator-config.yaml` (primary path)

**Purpose:** Add the review handler as a separate Prow command that runs regardless of CI status.

**Change to `docs/prow-ci-operator-config.yaml`** — add after line 163:

```yaml
        /app/scripts/pr-agent/review-handler.sh --pr-url "$PR_URL"
```

The full command block becomes:
```yaml
        gh auth setup-git
        /app/scripts/ci-monitor/monitor.sh
        /app/scripts/ci-monitor/dispatch.sh
        /app/scripts/pr-agent/review-handler.sh --pr-url "$PR_URL"
```

The review handler runs after dispatch, independent of dispatch's exit status.

**Files:**
| File | Action |
|------|--------|
| `docs/prow-ci-operator-config.yaml` | Modify (add line after 163) |

---

### Step 4: Wire into `entrypoint.sh` (secondary path)

**Purpose:** The PR agent on-demand/periodic mode also runs the review handler.

**Changes to `scripts/pr-agent/entrypoint.sh`** — insert at line 826 (between auto-fix `fi` at 825 and status report at 827):

```bash
  # Module: Review Comment Handler (independent of CI status)
  if [[ "$MONITOR_ONLY" != "true" ]]; then
    echo "[PR #${PR_NUMBER}] Module: review comments — started"
    local review_handler="${SCRIPT_DIR}/review-handler.sh"
    if [[ -x "$review_handler" ]]; then
      "$review_handler" --pr-url "$pr_url" ${DRY_RUN:+--dry-run} || true
    fi
    echo "[PR #${PR_NUMBER}] Module: review comments — completed"
  fi
```

Labeled "Module:" (not "Phase:") to distinguish from the phase numbering. Runs outside the `if ci_status == "some-failed"` block, so it executes regardless of CI status.

**Files:**
| File | Action |
|------|--------|
| `scripts/pr-agent/entrypoint.sh` | Modify (`process_pr()`, line 826) |

---

### Step 5: Update `safety.sh` — raise commit limit

**Change to `scripts/pr-agent/safety.sh`** — line 17:

```bash
# Before:
MAX_COMMITS_PER_PR="${MAX_COMMITS_PER_PR:-3}"

# After:
MAX_COMMITS_PER_PR="${MAX_COMMITS_PER_PR:-5}"
```

5 commits per PR accommodates review handler commits alongside future auto-fix.

**Files:**
| File | Action |
|------|--------|
| `scripts/pr-agent/safety.sh` | Modify (line 17) |

---

### Step 6: Update `test-dry-run.sh`

**Changes:**

1. Add `review-handler.sh` to the shellcheck script list:
   ```bash
   "${REPO_ROOT}/scripts/pr-agent/review-handler.sh"
   ```

2. Add Python compile checks:
   ```bash
   python3 -m py_compile "${REPO_ROOT}/plugins/oape/skills/address-review-comments/check_replied.py"
   python3 -m py_compile "${REPO_ROOT}/plugins/oape/skills/address-review-comments/build_threads.py"
   ```

3. Add a dry-run test (after existing tests):
   ```bash
   echo "=== Review handler dry-run ==="
   if [[ -x "${REPO_ROOT}/scripts/pr-agent/review-handler.sh" ]]; then
     export DRY_RUN=true
     "${REPO_ROOT}/scripts/pr-agent/review-handler.sh" --pr-url "$TEST_PR_URL" --dry-run && \
       _pass "review-handler.sh dry-run" || _fail "review-handler.sh dry-run"
   else
     _skip "review-handler.sh not found"
   fi
   ```

**Files:**
| File | Action |
|------|--------|
| `scripts/pr-agent/test-dry-run.sh` | Modify |

---

### Step 7: Claude CLI in container image

**Changes to `images/ci-monitor.Dockerfile`** — add after line 8 (after `dnf clean all`):

```dockerfile
# Install Node.js and Claude Code CLI (required for review comment handler)
RUN dnf module enable -y nodejs:20 && \
    dnf install -y nodejs npm && \
    npm install -g @anthropic-ai/claude-code && \
    dnf clean all
```

**Also update `docs/prow-ci-operator-config.yaml`** `dockerfile_literal` block with the same addition.

**Note:** Adds ~200-400MB to the container image. The review handler gracefully degrades without it (`claude --version` check), so this step can be deferred.

**Alternative (lighter):** Use `npx` at runtime — avoids image bloat but adds ~30s startup latency per invocation.

**Files:**
| File | Action |
|------|--------|
| `images/ci-monitor.Dockerfile` | Modify |
| `docs/prow-ci-operator-config.yaml` | Modify (dockerfile_literal section) |

---

### Step 8: Report section in `entrypoint.sh`

**Changes to `scripts/pr-agent/entrypoint.sh`** — in `generate_status_report()`, after the "Fixes Applied" section (after line 666, before "Infrastructure flakes" at line 668):

```bash
    # Review comments addressed
    echo "### Review Comments Addressed"
    echo ""
    local review_entries
    review_entries=$(grep '"action":"review-addressed"' "$AUDIT_LOG" 2>/dev/null || true)
    if [[ -n "$review_entries" ]]; then
      local review_count
      review_count=$(echo "$review_entries" | wc -l)
      echo "- **${review_count}** review thread(s) addressed"
      echo ""
      echo "$review_entries" | while IFS= read -r entry; do
        local thread_type outcome
        thread_type=$(echo "$entry" | jq -r '.type')
        outcome=$(echo "$entry" | jq -r '.outcome')
        echo "- \`${thread_type}\`: ${outcome}"
      done
    else
      echo "- (none)"
    fi
    echo ""
```

**Files:**
| File | Action |
|------|--------|
| `scripts/pr-agent/entrypoint.sh` | Modify (`generate_status_report()`) |

---

## Safety Guardrails

The review handler inherits all existing guardrails from `safety.sh`:

| Guardrail | Mechanism | Effect |
|-----------|-----------|--------|
| File blocklist | `check_blocklist()` | Prevents modifying secrets, CI configs, RBAC |
| Commit limits | `check_commit_limit()` | Max 5 commits/PR, max 10 commits/run |
| Diff size | `check_diff_size()` | Max 500 lines changed per fix |
| Audit log | `audit_log()` | Every action logged to JSONL |
| Dry run | `DRY_RUN=true` | Full analysis without modifications |
| Claude tool restriction | `--allowedTools` | Whitelist of safe operations |
| Timeout | `timeout 300` | 5 min cap per Claude invocation |
| Permission mode | `bypassPermissions` | Auto-approve tool calls in CI |
| Duplicate prevention | `check_replied.py` | Prevents double-posting |
| Compilation verification | Claude prompt + skill | `go build` / `go vet` before commit |

**Claude's `--allowedTools` whitelist:**
```
Bash(git diff*), Bash(git add*), Bash(git commit*),
Bash(git log*), Bash(git status*), Bash(git stash*), Bash(go *), Bash(make *),
Bash(gh api*), Bash(gh pr comment*), Bash(python3*), Read, Edit
```

**Explicitly excluded:** `Write` (create new files), `git push --force`, `git push -f`, `git rebase`, `git reset --hard`, `rm`, `curl`, network access.

---

## Edge Cases

| Case | Handling |
|------|----------|
| Claude CLI not installed | Exit 0 with warning — no regression |
| No review comments on PR | Exit 0, "0 threads need attention" |
| All comments from bots | Exit 0, all filtered by `build_threads.py` |
| Duplicate reply detected | `check_replied.py` exit 1 -> skip thread |
| `check_replied.py` error (exit 2) | Fail safe — skip thread |
| Oversized comment (>5000 chars) | Filtered in `build_threads.py` Pass 1 |
| Orphaned inline comment | Filtered (`line == null AND original_line == null`). Stale-diff comments (`original_line != null`) kept |
| Commit limit reached | Log "commit limit reached", Claude still posts explanation-only replies |
| Claude invocation hangs | `timeout 300` kills after 5 min, continues to next thread |
| Claude invocation fails | `|| true` — logged, continues to next thread |
| Push triggers new CI cycle | Expected behavior. `check_replied.py` prevents duplicate handling on re-run |
| Concurrent Prow runs | `check_replied.py` provides best-effort dedup. Bounded consequence. |
| Thread with 10+ comments | Full thread passed to Claude — handles context naturally |
| Binary/image file review | Claude cannot process — posts "requires human attention" |
| `build_threads.py` fails | Exit 0 after logging error — no crash |
| `coderabbitai` comments | NOT skipped — kept for Claude to process (useful code review insights) |

---

## Testing Strategy

### 1. Static analysis
```bash
shellcheck scripts/pr-agent/review-handler.sh
python3 -m py_compile plugins/oape/skills/address-review-comments/build_threads.py
python3 -m py_compile plugins/oape/skills/address-review-comments/check_replied.py
```

### 2. Dry-run (no clone, no Claude, no API writes)
```bash
export GH_TOKEN="$(gh auth token)"
export RUNNER_TEMP=$(mktemp -d)
export DRY_RUN=true

scripts/pr-agent/review-handler.sh \
  --pr-url https://github.com/openshift/must-gather-operator/pull/<N> \
  --dry-run
```
Verify: fetches threads via `build_threads.py`, prints "DRY RUN: Would address N threads", exits 0.

### 3. Full test suite
```bash
scripts/pr-agent/test-dry-run.sh
```

### 4. Integration test (Prow rehearsal)
```bash
# 1. Point prow-ci-operator-config.yaml to this branch
# 2. Start with DRY_RUN=true
# 3. Create a test PR with intentional review comments
# 4. Run /pj-rehearse to validate end-to-end
# 5. Remove DRY_RUN and test on must-gather-operator first
```

---

## File Summary

| File | Action | Step |
|------|--------|------|
| `plugins/oape/skills/pr-agent-safety/SKILL.md` | Create | 1 |
| `plugins/oape/skills/address-review-comments/SKILL.md` | Create | 1b |
| `plugins/oape/skills/address-review-comments/check_replied.py` | Create | 1b |
| `plugins/oape/skills/address-review-comments/build_threads.py` | Create | 1b |
| `scripts/pr-agent/review-handler.sh` | Create (~200 lines) | 2 |
| `docs/prow-ci-operator-config.yaml` | Modify (add command + Dockerfile) | 3, 7 |
| `scripts/pr-agent/entrypoint.sh` | Modify (module integration + report) | 4, 8 |
| `scripts/pr-agent/safety.sh` | Modify (MAX_COMMITS_PER_PR 3->5) | 5 |
| `scripts/pr-agent/test-dry-run.sh` | Modify (shellcheck + dry-run) | 6 |
| `images/ci-monitor.Dockerfile` | Modify (add Node.js + Claude CLI) | 7 |

---

## Prow Integration — `/test oape-review-handler`

The review handler runs as a Prow presubmit job triggered by a PR comment command:

```
/test oape-review-handler
```

### How it works

1. User comments `/test oape-review-handler` on a PR in `openshift/must-gather-operator`
2. Prow triggers `pull-ci-openshift-must-gather-operator-master-oape-review-handler`
3. The job builds the `ci-monitor-agent` image (with Claude CLI)
4. Runs `review-handler.sh --pr-url "$PR_URL"` inside the container
5. Bot addresses review comments, pushes fixes, posts replies

### Config location

The Prow job is defined in a **separate** `openshift/release` PR (not part of the ci-monitor PR #80727):
- **ci-operator config:** `ci-operator/config/openshift/must-gather-operator/openshift-must-gather-operator-master.yaml`
- **Reference snippet:** `docs/prow-review-handler-config.yaml` (in this repo)

### Key properties

| Property | Value |
|----------|-------|
| `always_run` | `false` — manual trigger only via `/test oape-review-handler` |
| `optional` | `true` — does not block merge |
| Timeout | 1 hour |
| Image | `review-handler-agent` (separate from `ci-monitor-agent`) |
| Clone source | `main` branch of `openshift-eng/oape-ai-e2e` |
| Claude CLI | Installed via `npm install -g @anthropic-ai/claude-code` |
| `PLUGINS_DIR` | `/plugins/oape/skills` (container path) |

### Container image

The review handler uses its own `review-handler-agent` image (separate from `ci-monitor-agent`). It clones from `main` branch and includes Node.js + Claude CLI:

```dockerfile
FROM registry.access.redhat.com/ubi9/go-toolset
# ... base tools (git, make, jq, gh) ...
RUN dnf module enable -y nodejs:20 && \
    dnf install -y nodejs npm && \
    npm install -g @anthropic-ai/claude-code && \
    dnf clean all
# ... clone from main, install go tools ...
```

### Credentials (same as `oape-ci-monitor`)

- **GitHub App:** `openshift-app-platform-shift-github-bot` (push + comment permissions)
- **Vertex AI:** `oap-lts-claude-gcp-vertex-sa` (Claude via GCP)

### Rehearsal

From the `openshift/release` PR:
```
/pj-rehearse oape-review-handler
```

The rehearsal detection block automatically switches from `openshift/release` to a real `must-gather-operator` PR for validation.

---

## Rollout Plan

1. Merge [openshift-eng/oape-ai-e2e#63](https://github.com/openshift-eng/oape-ai-e2e/pull/63) to `main`
2. Open a **separate** `openshift/release` PR with the review handler Prow config (see `docs/prow-review-handler-config.yaml`)
3. `/pj-rehearse oape-review-handler` from the release PR
4. `/test oape-review-handler` on a real `must-gather-operator` PR with review comments
5. Monitor 1 week — review quality, false positives, CI cascade impact
6. Expand to other repos in `team-repos.csv`

---

## Known Limitations & Future Work

1. **CI cascade** — each pushed commit re-triggers all Prow presubmits. Mitigated by commit limit (5/PR). Future: batch multiple review fixes into a single commit.
2. **Post-commit guardrails** — `check_blocklist()` validation runs after Claude commits, reverting protected file modifications and oversized diffs before push. The safety SKILL.md provides prompt-level guidance; the post-commit check enforces it.
3. **No cumulative spend tracking** — if `--max-budget-usd` is added later, it would need per-run tracking across threads. Current bound is `timeout 300` (5 min) per thread.
4. **No GitHub API rate limiting** — heavily-reviewed PRs could hit rate limits. Future: add rate limit checking in `build_threads.py`.
