"""
Context loader for OAPE commands.

Loads skill files and command instructions from the plugins directory
to construct the system prompt for the AI model.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Base paths - handle both local dev and Docker deployments
SERVER_DIR = Path(__file__).resolve().parent
REPO_ROOT = SERVER_DIR.parent

# In Docker, plugins are at /plugins/oape, root files at /
# In local dev, they're at repo_root/plugins/oape
if (Path("/plugins/oape")).exists():
    # Docker deployment
    PLUGINS_DIR = Path("/plugins/oape")
    ROOT_FILES_DIR = Path("/")
else:
    # Local development
    PLUGINS_DIR = REPO_ROOT / "plugins" / "oape"
    ROOT_FILES_DIR = REPO_ROOT

COMMANDS_DIR = PLUGINS_DIR / "commands"
SKILLS_DIR = PLUGINS_DIR / "skills"

# Command name to filename mapping
COMMAND_FILES = {
    "init": "init.md",
    "api-generate": "api-generate.md",
    "api-generate-tests": "api-generate-tests.md",
    "api-implement": "api-implement.md",
    "e2e-generate": "e2e-generate.md",
    "review": "review.md",
    "implement-review-fixes": "implement-review-fixes.md",
}

# Skills to load for each command (or all commands)
COMMON_SKILLS = [
    "effective-go/SKILL.md",
]

COMMAND_SKILLS = {
    "e2e-generate": [
        "e2e-test-generator/SKILL.md",
    ],
    "api-generate": [],
    "api-generate-tests": [],
    "api-implement": [],
    "init": [],
    "review": [],
    "implement-review-fixes": [],
}


def read_file_safe(path: Path) -> str:
    """Read a file safely, returning empty string if not found."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning(f"File not found: {path}")
        return ""
    except Exception as e:
        logger.error(f"Error reading {path}: {e}")
        return ""


def load_base_context() -> str:
    """Load the base context from AGENTS.md or CLAUDE.md."""
    # Try AGENTS.md first, then CLAUDE.md
    for filename in ["AGENTS.md", "CLAUDE.md"]:
        path = ROOT_FILES_DIR / filename
        content = read_file_safe(path)
        if content:
            logger.info(f"Loaded base context from {filename}")
            return content

    logger.warning("No base context file found (AGENTS.md or CLAUDE.md)")
    return ""


def load_team_repos() -> str:
    """Load the team-repos.csv for repository information."""
    path = ROOT_FILES_DIR / "team-repos.csv"
    content = read_file_safe(path)
    if content:
        return f"\n\n## Team Repositories\n\n```csv\n{content}\n```\n"
    return ""


def load_skill(skill_path: str) -> str:
    """Load a skill file from the skills directory."""
    path = SKILLS_DIR / skill_path
    content = read_file_safe(path)
    if content:
        logger.info(f"Loaded skill: {skill_path}")
        return f"\n\n---\n\n# Skill: {skill_path}\n\n{content}"
    return ""


def load_command_instructions(command: str) -> str:
    """Load the command-specific instructions."""
    filename = COMMAND_FILES.get(command)
    if not filename:
        logger.error(f"Unknown command: {command}")
        return ""

    path = COMMANDS_DIR / filename
    content = read_file_safe(path)
    if content:
        logger.info(f"Loaded command instructions: {filename}")
        return f"\n\n---\n\n# Command Instructions: {command}\n\n{content}"
    return ""


def load_e2e_fixtures() -> str:
    """Load e2e test generator fixtures for the e2e-generate command."""
    # Fixtures can be in either location depending on repo structure
    fixtures_dir = PLUGINS_DIR / "e2e-test-generator" / "fixtures"
    if not fixtures_dir.exists():
        # Try alternative location
        fixtures_dir = PLUGINS_DIR.parent / "e2e-test-generator" / "fixtures"
    if not fixtures_dir.exists():
        return ""

    parts = []
    for fixture_file in fixtures_dir.glob("*.md"):
        content = read_file_safe(fixture_file)
        if content:
            parts.append(f"\n\n### Fixture: {fixture_file.name}\n\n{content}")

    # Also load example files
    for example_file in fixtures_dir.glob("*.example"):
        content = read_file_safe(example_file)
        if content:
            parts.append(
                f"\n\n### Example: {example_file.name}\n\n```\n{content}\n```"
            )

    if parts:
        return "\n\n---\n\n# E2E Test Generator Fixtures\n" + "".join(parts)
    return ""


def load_context(command: str) -> str:
    """
    Load the full context for a specific command.

    This combines:
    1. Base context (AGENTS.md)
    2. Team repositories info
    3. Common skills (effective-go)
    4. Command-specific skills
    5. Command instructions
    6. Additional fixtures (for e2e-generate)

    Args:
        command: The command name (e.g., "api-implement", "e2e-generate")

    Returns:
        Combined system prompt string.
    """
    parts = []

    # 1. Base context
    base = load_base_context()
    if base:
        parts.append(base)

    # 2. Team repos
    repos = load_team_repos()
    if repos:
        parts.append(repos)

    # 3. Common skills
    for skill_path in COMMON_SKILLS:
        skill_content = load_skill(skill_path)
        if skill_content:
            parts.append(skill_content)

    # 4. Command-specific skills
    command_skills = COMMAND_SKILLS.get(command, [])
    for skill_path in command_skills:
        skill_content = load_skill(skill_path)
        if skill_content:
            parts.append(skill_content)

    # 5. Command instructions
    cmd_instructions = load_command_instructions(command)
    if cmd_instructions:
        parts.append(cmd_instructions)

    # 6. E2E fixtures (for e2e-generate command)
    if command == "e2e-generate":
        fixtures = load_e2e_fixtures()
        if fixtures:
            parts.append(fixtures)

    # Combine all parts
    full_context = "\n".join(parts)

    # Add execution instructions at the end
    full_context += f"""

---

# Execution Context

You are now executing the `{command}` command. Follow the instructions above precisely.

- Execute each phase in order
- Use the provided tools (bash, read_file, write_file, etc.) as needed
- If any precheck fails, STOP and report the failure
- Provide clear output at each step
- End with a summary of what was accomplished
"""

    logger.info(
        f"Loaded context for command '{command}': {len(full_context)} characters"
    )
    return full_context


def get_available_commands() -> list[str]:
    """Return list of available command names."""
    return list(COMMAND_FILES.keys())


def validate_command(command: str) -> bool:
    """Check if a command is valid."""
    return command in COMMAND_FILES

