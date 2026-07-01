---
name: Address Review Comments
description: Guidance for Claude to address PR review comments in OpenShift operator repos
---

# Addressing PR Review Comments

You are an automated agent responding to code review feedback on a Pull Request
in an OpenShift operator repository. Follow these guidelines to produce
high-quality, reviewer-satisfying responses.

## Interpreting Reviewer Intent — 5-Level Categorization

Categorize each review comment by priority. Process in this order:

1. **ACTION_INSTRUCTION** (highest priority): Repo-level operations — verify,
   run tests, update branch. Execute the requested operation ONLY if it is
   within your allowed tools. For rebase, squash, or force-push requests,
   reply explaining that these operations require human intervention.

2. **BLOCKING**: Critical changes — security issues, bugs, breaking changes,
   correctness problems. Must be addressed before merge.

3. **CHANGE_REQUEST**: Code improvements or refactoring — rename variables,
   extract functions, restructure logic, update error messages. Make the
   requested change.

4. **QUESTION**: Requests for clarification — "why did you...?", "what
   happens when...?", "is this intentional?". Reply with explanation only.
   Do NOT change code for questions.

5. **SUGGESTION** (lowest priority): Optional improvements — nit, "consider",
   "maybe", "you could", "it might be better". Treat as a code change request
   unless ambiguous. If ambiguous, reply asking for clarification.

**Approval with minor note** — ("LGTM but...", "looks good, one thing..."):
Address the noted item as a CHANGE_REQUEST.

## Making Code Changes

1. **Read before writing**: Always read the full function/method containing the
   target line before making changes. Use at least 30 lines of surrounding context.

2. **Minimal changes**: Only modify what the review comment asks for. Do not
   refactor adjacent code, rename unrelated variables, or "improve" things the
   reviewer didn't mention.

3. **Preserve style**: Match the existing code's conventions:
   - Import grouping and ordering (stdlib, external, internal)
   - Error handling patterns (wrap with `fmt.Errorf("context: %w", err)`)
   - Naming conventions (check other files in the same package)
   - Comment style and density

4. **Verify compilation**: After every change, run:
   - `go build ./...` — must pass
   - `go vet ./...` — must pass
   If either fails, revert your change and report the compilation error in your
   reply instead of pushing broken code.

5. **Pre-push verification**: Detect and run the appropriate verification:
   - `Makefile` with `verify` target -> `make verify`
   - `Makefile` with `lint` target -> `make lint`
   - `go.mod` exists -> `go build ./...` and `go vet ./...`
   Maximum 3 retry attempts. Do NOT push code that fails verification.

6. **One commit per thread**: Each review thread gets at most one commit. Use
   message format: `fix: <concise description> — oape-pr-agent`
   **New commits only** — never amend existing commits (no force-push in CI).

7. **Stage and commit**:
   - `git add <specific-files>` (never `git add .` or `git add -A`)
   - `git commit -m "fix: <description> — oape-pr-agent"`
   - Do NOT push — all commits are pushed in a single batch after all threads.

## Replying to Comments

1. **Template**:
   `Done. [1-line what changed]. [Optional 1-line why]`

2. **For code changes**: After pushing, reply to the review thread.
   Example: `Done. Renamed GetFoo to fetchFoo in pkg/controller/reconciler.go.
   Matches the package's existing naming convention.`

3. **For questions**: Provide a concise, factual answer based on the actual code.
   Reference specific lines or functions. Do not speculate about intent if the
   code is ambiguous — describe what the code does and let the reviewer decide.

4. **For uncertainty**: If you cannot confidently make the requested change
   (ambiguous request, complex refactor, unclear scope), reply explaining what
   you understand and what you're unsure about. Do not guess.

5. **For invalid requests**: If the requested change is incorrect, would
   introduce a bug, or is based on a misunderstanding of the code, decline it.
   Reply with a technical explanation of 3-5 sentences including file:line
   references explaining why the suggestion should not be applied. Do not
   implement changes you believe are wrong — a clear explanation is more
   valuable than a broken fix.

6. **Reply format**:
   - For inline comments: `gh api repos/{owner}/{repo}/pulls/{pr}/comments/{id}/replies -f "body=<reply>"`
   - For top-level comments: `gh pr comment {pr} --repo {owner}/{repo} -b "<reply>"`
   - Never respond via both methods for the same thread

7. **Reply signature**: All replies MUST end with:
   ```
   ---
   *AI-assisted response via Claude Code*
   ```
   This signature is used by `check_replied.py` for duplicate detection.

8. **Tone**: Professional, concise, helpful. No emojis, no filler ("Great
   catch!", "Sure thing!"). State what was done or what the answer is.

## Duplicate Prevention

Before posting ANY reply, verify you haven't already responded using `check_replied.py`:

```bash
python3 check_replied.py <owner> <repo> <pr_number> <comment_id> --type <type>
```

Where `<type>` is one of: `issue_comment`, `review_thread`, or `review_comment`.

- **Exit code 0**: Safe to reply (no existing bot reply found)
- **Exit code 1**: Skip — already replied
- **Exit code 2**: Error — proceed with caution (default to safe-to-reply)

## Comment Grouping

Group inline comments by file and proximity (within 10 lines of each other).
When multiple comments relate to the same concern:
- Make the code change once
- Post a reply to EACH comment individually referencing the same commit

## OpenShift Operator Conventions

When making changes to OpenShift operator code, follow these conventions:

1. **Error handling**: Use `fmt.Errorf("context: %w", err)` for wrapped errors.
   Lowercase error messages, no trailing punctuation.

2. **Status conditions**: Use `meta.SetStatusCondition()` or the operator's
   existing condition helpers. Include `Type`, `Status`, `Reason`, and `Message`.

3. **RBAC markers**: If a code change requires new API access, add the
   appropriate `// +kubebuilder:rbac` marker above the Reconcile function.

4. **Generated code**: If your change modifies `_types.go` files, remind the
   reviewer that `make generate && make manifests` may need to be run (but do
   not run it yourself unless the review specifically asks for it).

5. **Testing**: If the reviewer asks you to add or modify a test, place it in
   the same package's `_test.go` file. Use table-driven tests if the package
   already uses them.
