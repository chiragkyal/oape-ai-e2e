#!/usr/bin/env python3
"""
Fetch RFE issue from Jira using REST API.
Used by the analyze-rfe skill for Step 1 (Fetch the RFE).
Requires: JIRA_PERSONAL_TOKEN, optional JIRA_URL (default https://issues.redhat.com).
"""

import json
import os
import sys
from typing import Optional, List, Dict

try:
    import requests
except ImportError:
    print("Error: requests library not installed", file=sys.stderr)
    print("Install with: pip install requests", file=sys.stderr)
    sys.exit(1)


class JiraClient:
    """Simple Jira REST API client."""

    def __init__(self):
        self.base_url = os.getenv("JIRA_URL", "https://issues.redhat.com")
        self.token = os.getenv("JIRA_PERSONAL_TOKEN")

        if not self.token:
            self._print_setup_instructions()
            sys.exit(1)

        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        })

    def _print_setup_instructions(self):
        print("\n" + "="*70, file=sys.stderr)
        print("ERROR: JIRA_PERSONAL_TOKEN not configured", file=sys.stderr)
        print("="*70, file=sys.stderr)
        print("\nRequired Setup:", file=sys.stderr)
        print("\n1. Get Jira Personal Access Token:", file=sys.stderr)
        print("   https://issues.redhat.com/secure/ViewProfile.jspa?selectedTab=com.atlassian.pats.pats-plugin:jira-user-personal-access-tokens", file=sys.stderr)
        print("\n2. Set environment variable:", file=sys.stderr)
        print('   export JIRA_PERSONAL_TOKEN="your_token_here"', file=sys.stderr)
        print("\n3. Verify it works:", file=sys.stderr)
        print('   curl -H "Authorization: Bearer $JIRA_PERSONAL_TOKEN" \\', file=sys.stderr)
        print('        "https://issues.redhat.com/rest/api/2/myself"', file=sys.stderr)
        print("="*70 + "\n", file=sys.stderr)

    def get_issue(self, issue_key: str, fields: Optional[List[str]] = None) -> Dict:
        """
        Fetch a single issue with optional field filtering.

        Args:
            issue_key: Jira issue key (e.g., RFE-1234)
            fields: List of fields to fetch (None = default set for RFE analysis)

        Returns:
            Issue data as dict
        """
        if fields is None:
            fields = [
                "summary",
                "description",
                "components",
                "labels",
                "status",
                "created",
                "updated",
                "reporter",
                "assignee",
                "issuelinks",
                "issuetype",
                "customfield_12316840",
                "customfield_12319940",
            ]

        url = f"{self.base_url}/rest/api/2/issue/{issue_key}"
        params = {"fields": ",".join(fields)}

        try:
            response = self.session.get(url, params=params, timeout=30)

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 401:
                print(f"\nError: Authentication failed (HTTP 401)", file=sys.stderr)
                print(f"Your JIRA_PERSONAL_TOKEN may be invalid or expired.", file=sys.stderr)
                self._print_setup_instructions()
                sys.exit(1)
            elif response.status_code == 403:
                print(f"\nError: Access denied (HTTP 403)", file=sys.stderr)
                print(f"You need read permissions for issue: {issue_key}", file=sys.stderr)
                sys.exit(1)
            elif response.status_code == 404:
                print(f"\nError: Issue {issue_key} not found (HTTP 404)", file=sys.stderr)
                print(f"Verify: {self.base_url}/browse/{issue_key}", file=sys.stderr)
                sys.exit(1)
            else:
                print(f"\nError: HTTP {response.status_code}", file=sys.stderr)
                print(response.text, file=sys.stderr)
                sys.exit(1)

        except requests.exceptions.Timeout:
            print(f"\nError: Request timeout", file=sys.stderr)
            sys.exit(1)
        except requests.exceptions.ConnectionError as e:
            print(f"\nError: Connection failed: {e}", file=sys.stderr)
            sys.exit(1)
        except requests.exceptions.RequestException as e:
            print(f"\nError: Failed to fetch issue: {e}", file=sys.stderr)
            sys.exit(1)

    def search_issues(self, jql: str, fields: Optional[List[str]] = None,
                     max_results: int = 50) -> Dict:
        """Search for issues using JQL."""
        url = f"{self.base_url}/rest/api/2/search"
        payload = {
            "jql": jql,
            "maxResults": max_results,
            "fields": fields or ["key", "summary", "status", "created"]
        }
        try:
            response = self.session.post(url, json=payload, timeout=30)
            if response.status_code == 200:
                return response.json()
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"\nError: Failed to search: {e}", file=sys.stderr)
            sys.exit(1)


def main():
    if len(sys.argv) < 2:
        print("Usage: fetch_rfe.py <issue-key> [field1,field2,...]", file=sys.stderr)
        print("  fetch_rfe.py RFE-1234", file=sys.stderr)
        sys.exit(1)

    issue_key = sys.argv[1]
    fields = sys.argv[2].split(",") if len(sys.argv) > 2 else None

    client = JiraClient()
    issue_data = client.get_issue(issue_key, fields=fields)
    print(json.dumps(issue_data, indent=2))


if __name__ == "__main__":
    main()
