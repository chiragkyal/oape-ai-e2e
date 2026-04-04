"""Utility functions for message parsing, repo resolution, and agent I/O."""

import re
import sys

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)

from .config import TEAM_REPOS_CSV


def resolve_repo(ep_url: str) -> tuple[str, str, str]:
    """
    Prompt the user to pick the target operator repository from team-repos.csv.

    Returns:
        (repo_short_name, repo_url, base_branch)
    """
    rows: list[dict[str, str]] = []
    with open(TEAM_REPOS_CSV) as f:
        headers = f.readline().strip().split(",")
        for line in f:
            parts = line.strip().split(",")
            if len(parts) >= len(headers):
                rows.append(dict(zip(headers, parts)))

    if not rows:
        print("ERROR: team-repos.csv is empty or malformed.")
        sys.exit(1)

    print("\n--- Available target repositories ---")
    for i, row in enumerate(rows, 1):
        print(f"  [{i}] {row['repo_url']}  (base: {row['base_branch']})")

    choice = input(
        "\nEnter the number of the target repository (or the repo short name): "
    ).strip()

    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(rows):
            r = rows[idx]
            short = r["repo_url"].rstrip(".git").split("/")[-1]
            return short, r["repo_url"], r["base_branch"]

    # Try matching by short name substring
    for r in rows:
        short = r["repo_url"].rstrip(".git").split("/")[-1]
        if choice.lower() in short.lower():
            return short, r["repo_url"], r["base_branch"]

    print(f"ERROR: Could not resolve repository for input '{choice}'")
    sys.exit(1)


def extract_text(messages: list) -> str:
    """Pull all text content from a list of SDK messages."""
    parts: list[str] = []
    for msg in messages:
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    parts.append(block.text)
    return "\n".join(parts)


def extract_pr_url(text: str) -> str | None:
    """Extract the first GitHub PR URL from text."""
    m = re.search(r"https://github\.com/[^\s)]+/pull/\d+", text)
    return m.group(0) if m else None


async def collect_response(client: ClaudeSDKClient) -> list:
    """
    Drain all messages from a ClaudeSDKClient response, printing progress
    to stdout as they arrive.

    Returns the full list of messages.
    """
    messages: list = []
    async for msg in client.receive_response():
        messages.append(msg)
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    preview = block.text[:200]
                    if len(block.text) > 200:
                        preview += "..."
                    print(f"  [agent] {preview}")
                elif isinstance(block, ToolUseBlock):
                    print(f"  [tool]  {block.name}")
        elif isinstance(msg, ResultMessage):
            cost = msg.total_cost_usd or 0
            print(
                f"  [done]  turns={msg.num_turns}  cost=${cost:.4f}  "
                f"duration={msg.duration_ms / 1000:.1f}s"
            )
    return messages
