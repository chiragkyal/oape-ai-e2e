"""Workflow state and file-based state exchange between agents."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class WorkflowState:
    """Shared state across the entire workflow run."""

    ep_url: str
    repo_short_name: str = ""
    repo_url: str = ""
    base_branch: str = ""
    repo_local_path: str = ""
    api_types_path: str = ""
    api_summary_md: str = ""
    pr_urls: dict[str, str] = field(default_factory=dict)  # label -> PR URL


def make_workdir(label: str) -> Path:
    """Create a per-agent working directory under .oape-work/."""
    base = Path.cwd() / ".oape-work" / label
    base.mkdir(parents=True, exist_ok=True)
    return base


def write_state_summary(workdir: Path, filename: str, content: str) -> Path:
    """Write a state-exchange .md file into the agent's workdir."""
    p = workdir / filename
    p.write_text(content, encoding="utf-8")
    return p


def read_state_summary(path: Path) -> str:
    """Read a state-exchange .md file."""
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""
