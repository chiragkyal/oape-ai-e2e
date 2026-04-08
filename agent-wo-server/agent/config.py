"""Constants and ClaudeAgentOptions factory."""

from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions

# ---------------------------------------------------------------------------
# Paths (resolved relative to project root, two levels up from this file)
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OAPE_PLUGIN_PATH = PROJECT_ROOT / "plugins" / "oape"
TEAM_REPOS_CSV = PROJECT_ROOT / "team-repos.csv"

# ---------------------------------------------------------------------------
# Defaults (can be overridden via CLI flags)
# ---------------------------------------------------------------------------

POLL_INTERVAL_SECS = 60
MAX_CI_WAIT_MINS = 120
MAX_AGENT_TURNS = 200

# ---------------------------------------------------------------------------
# Agent options factory
# ---------------------------------------------------------------------------


def make_agent_options(
    cwd: str,
    system_prompt_append: str = "",
    max_turns: int | None = None,
) -> ClaudeAgentOptions:
    """Create ClaudeAgentOptions with the oape plugin loaded and full tool access."""
    return ClaudeAgentOptions(
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": system_prompt_append,
        },
        permission_mode="bypassPermissions",
        cwd=cwd,
        setting_sources=["project"],
        plugins=[{"type": "local", "path": str(OAPE_PLUGIN_PATH)}],
        allowed_tools=[
            "Bash",
            "Read",
            "Write",
            "Edit",
            "Glob",
            "Grep",
            "WebFetch",
            "WebSearch",
            "Skill",
            "Task",
        ],
        max_turns=max_turns or MAX_AGENT_TURNS,
    )
