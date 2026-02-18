"""
Bash command execution tool.
"""

import logging
import os
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Maximum output size to prevent memory issues
MAX_OUTPUT_SIZE = 100_000  # 100KB


@dataclass
class BashResult:
    """Result from executing a bash command."""

    stdout: str
    stderr: str
    exit_code: int
    truncated: bool = False

    @property
    def output(self) -> str:
        """Combined output for tool result."""
        parts = []
        if self.stdout:
            parts.append(self.stdout)
        if self.stderr:
            parts.append(f"[stderr]\n{self.stderr}")
        parts.append(f"[exit code: {self.exit_code}]")
        return "\n".join(parts)

    @property
    def is_error(self) -> bool:
        return self.exit_code != 0


class BashTool:
    """
    Execute bash commands in a specified working directory.

    Security considerations:
    - Commands run with the same permissions as the server process
    - Working directory is validated before execution
    - Output is truncated to prevent memory exhaustion
    - Timeout prevents hanging commands
    """

    def __init__(
        self,
        working_dir: str,
        timeout: int = 300,
        allowed_commands: list[str] | None = None,
    ):
        """
        Initialize the bash tool.

        Args:
            working_dir: Directory to execute commands in.
            timeout: Maximum execution time in seconds (default 5 minutes).
            allowed_commands: Optional allowlist of command prefixes.
                             If None, all commands are allowed.
        """
        self.working_dir = os.path.abspath(working_dir)
        self.timeout = timeout
        self.allowed_commands = allowed_commands

        # Validate working directory exists
        if not os.path.isdir(self.working_dir):
            raise ValueError(f"Working directory does not exist: {self.working_dir}")

    def _is_command_allowed(self, command: str) -> bool:
        """Check if command is in the allowlist."""
        if self.allowed_commands is None:
            return True

        cmd_parts = command.strip().split()
        if not cmd_parts:
            return False

        base_cmd = cmd_parts[0]
        return any(
            base_cmd == allowed or base_cmd.startswith(allowed + " ")
            for allowed in self.allowed_commands
        )

    def execute(self, command: str) -> BashResult:
        """
        Execute a bash command.

        Args:
            command: The command to execute.

        Returns:
            BashResult with stdout, stderr, exit code.
        """
        logger.info(f"Executing: {command[:100]}...")

        # Check allowlist
        if not self._is_command_allowed(command):
            return BashResult(
                stdout="",
                stderr=f"Command not allowed: {command.split()[0]}",
                exit_code=1,
            )

        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=self.working_dir,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env={**os.environ, "HOME": os.environ.get("HOME", "/tmp")},
            )

            stdout = result.stdout
            stderr = result.stderr
            truncated = False

            # Truncate output if too large
            if len(stdout) > MAX_OUTPUT_SIZE:
                stdout = stdout[:MAX_OUTPUT_SIZE] + "\n...[output truncated]..."
                truncated = True
            if len(stderr) > MAX_OUTPUT_SIZE:
                stderr = stderr[:MAX_OUTPUT_SIZE] + "\n...[output truncated]..."
                truncated = True

            return BashResult(
                stdout=stdout,
                stderr=stderr,
                exit_code=result.returncode,
                truncated=truncated,
            )

        except subprocess.TimeoutExpired:
            logger.warning(f"Command timed out after {self.timeout}s: {command[:50]}")
            return BashResult(
                stdout="",
                stderr=f"Command timed out after {self.timeout} seconds",
                exit_code=124,  # Standard timeout exit code
            )

        except Exception as e:
            logger.error(f"Command execution error: {e}")
            return BashResult(
                stdout="",
                stderr=f"Execution error: {str(e)}",
                exit_code=1,
            )

