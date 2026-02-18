---
description: Analyze an RFE and output EPIC, user stories, and their outcomes
argument-hint: <rfe-key>
---

## Name
oape:analyze-rfe

## Synopsis
```shell
/oape:analyze-rfe <rfe-key>
```

## Description

The `oape:analyze-rfe` command analyzes a Request for Enhancement (RFE) from Jira and generates a structured breakdown of Epics, user stories, and their outcomes. Use it to turn customer-driven RFEs into actionable implementation plans.

**Useful for:**
- Breaking down RFEs into implementable work items
- Planning sprints and releases from customer requests
- Creating epics and stories aligned with RFE scope
- Preparing for refinement or planning sessions

**Analysis includes:**
- RFE nature, description, business requirements, affected components
- One or more Epics with scope and acceptance criteria
- User stories in "As a... I want... So that..." format with acceptance criteria
- Outcomes (value each story delivers)
- Optional: workspace context from `context.md` files when present

## Implementation

This command invokes the `analyze-rfe` skill. The skill:

1. **Fetch RFE** — Retrieve the RFE from Jira (REST API with `JIRA_PERSONAL_TOKEN` or MCP if available)
2. **Parse** — Extract nature, description, desired behavior, affected components
3. **Gather workspace context** (optional) — Search for `context.md` (e.g. `docs/component-context/context.md`) and use component Purpose/Scope to enrich the breakdown
4. **Generate EPIC(s)** — Scope, objective, acceptance criteria
5. **Generate user stories** — Per epic, with acceptance criteria and outcomes
6. **Output** — Structured markdown report; optionally save to `.work/jira/analyze-rfe/<rfe-key>/breakdown.md`

See `plugins/oape/skills/analyze-rfe/SKILL.md` for step-by-step implementation.

## Arguments

- **$1 – rfe-key** *(required)*  
  Jira issue key (e.g. `RFE-1234`) or full URL (e.g. `https://issues.redhat.com/browse/RFE-1234`). The key is extracted from the URL if needed.

## Return Value

- **Markdown report** with RFE summary, EPIC(s), user stories, outcomes
- Optional file: `.work/jira/analyze-rfe/<rfe-key>/breakdown.md`

## Prerequisites

- **Jira access**: Set `JIRA_PERSONAL_TOKEN` (and optionally `JIRA_URL`, default `https://issues.redhat.com`). Create token at: https://issues.redhat.com/secure/ViewProfile.jspa?selectedTab=com.atlassian.pats.pats-plugin:jira-user-personal-access-tokens
- Read access to the RFE project

## Examples

```shell
/oape:analyze-rfe RFE-7841
/oape:analyze-rfe https://issues.redhat.com/browse/RFE-7841
```

## See Also

- `oape:review` — Code review against Jira requirements
- `oape:api-implement` — Generate controller code from enhancement proposal
