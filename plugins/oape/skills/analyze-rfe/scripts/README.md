# analyze-rfe scripts

Scripts used by the `/oape:analyze-rfe` skill.

## fetch_rfe.py

Fetches an RFE (or any Jira issue) from Jira via REST API. Used for **Step 1: Fetch the RFE**.

**Prerequisites**
- `JIRA_PERSONAL_TOKEN` (required)
- `JIRA_URL` (optional, default: `https://issues.redhat.com`)
- Python 3 and `requests`: `pip install requests`

**Usage**
```bash
# From repo root or from this scripts directory
export JIRA_PERSONAL_TOKEN="your_token"
python3 plugins/oape/skills/analyze-rfe/scripts/fetch_rfe.py RFE-7841
# Or with custom fields
python3 plugins/oape/skills/analyze-rfe/scripts/fetch_rfe.py RFE-7841 summary,description,components,status
```

**Output**: JSON for the issue (to stdout). Errors and setup instructions go to stderr.

The skill can run this script when executing Step 1, or use curl/requests inline; the script provides consistent error handling and token checks.
