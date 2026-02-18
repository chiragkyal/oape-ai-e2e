"""
Tool executor that handles tool calls from the AI model.

Provides:
- Tool definitions in Anthropic format
- Tool execution routing
- Result formatting
"""

import logging
from typing import Any

from .bash import BashTool
from .file_ops import ReadFileTool, WriteFileTool, EditFileTool, GlobTool, GrepTool
from .web_fetch import WebFetchTool

logger = logging.getLogger(__name__)


# Tool definitions in Anthropic API format
TOOL_DEFINITIONS = [
    {
        "name": "bash",
        "description": (
            "Execute a bash command in the working directory. "
            "Use for: running git commands, make, go build, find, etc. "
            "Commands run with server permissions. Output is captured."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The bash command to execute.",
                }
            },
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": (
            "Read the contents of a file. Returns numbered lines. "
            "Use offset and limit for large files."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path (relative to working dir or absolute).",
                },
                "offset": {
                    "type": "integer",
                    "description": "Line number to start reading from (1-indexed).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of lines to read.",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "Write content to a file. Creates parent directories if needed. "
            "Overwrites existing content."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path (relative to working dir or absolute).",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file.",
                },
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": (
            "Edit a file by replacing text. The old_string must be unique "
            "in the file unless replace_all is true."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path.",
                },
                "old_string": {
                    "type": "string",
                    "description": "Text to find and replace.",
                },
                "new_string": {
                    "type": "string",
                    "description": "Replacement text.",
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "Replace all occurrences (default: false).",
                },
            },
            "required": ["path", "old_string", "new_string"],
        },
    },
    {
        "name": "glob",
        "description": (
            "Find files matching a glob pattern. "
            "Returns file paths relative to the search directory."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern (e.g., '**/*.go', '*_types.go').",
                },
                "directory": {
                    "type": "string",
                    "description": "Directory to search (default: working dir).",
                },
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "grep",
        "description": (
            "Search for a regex pattern in files. "
            "Returns matching lines with file paths and line numbers."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regex pattern to search for.",
                },
                "path": {
                    "type": "string",
                    "description": "File or directory to search (default: working dir).",
                },
                "glob_pattern": {
                    "type": "string",
                    "description": "Filter files by glob pattern (e.g., '*.go').",
                },
                "ignore_case": {
                    "type": "boolean",
                    "description": "Case-insensitive search (default: false).",
                },
                "context_lines": {
                    "type": "integer",
                    "description": "Lines of context before/after match.",
                },
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "web_fetch",
        "description": (
            "Fetch content from a URL (HTTP/HTTPS). "
            "Use for GitHub raw content, API docs, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch.",
                }
            },
            "required": ["url"],
        },
    },
]


class ToolResult:
    """Result from tool execution, compatible with vertex_client."""

    def __init__(self, tool_use_id: str, content: str, is_error: bool = False):
        self.tool_use_id = tool_use_id
        self.content = content
        self.is_error = is_error


class ToolExecutor:
    """
    Executes tools requested by the AI model.

    Initializes all tool implementations and routes tool calls
    to the appropriate handler.
    """

    def __init__(self, working_dir: str):
        """
        Initialize tool executor with working directory.

        Args:
            working_dir: Base directory for file operations and commands.
        """
        self.working_dir = working_dir

        # Initialize tools
        self.bash = BashTool(working_dir)
        self.read_file = ReadFileTool(working_dir)
        self.write_file = WriteFileTool(working_dir)
        self.edit_file = EditFileTool(working_dir)
        self.glob = GlobTool(working_dir)
        self.grep = GrepTool(working_dir)
        self.web_fetch = WebFetchTool()

    def execute(self, tool_name: str, tool_input: dict[str, Any]) -> ToolResult:
        """
        Execute a tool and return the result.

        Args:
            tool_name: Name of the tool to execute.
            tool_input: Input parameters for the tool.

        Returns:
            ToolResult with content and error status.
        """
        logger.info(f"Executing tool: {tool_name}")
        logger.debug(f"Tool input: {tool_input}")

        try:
            if tool_name == "bash":
                result = self.bash.execute(tool_input["command"])
                return ToolResult(
                    tool_use_id="",  # Will be set by caller
                    content=result.output,
                    is_error=result.is_error,
                )

            elif tool_name == "read_file":
                result = self.read_file.execute(
                    path=tool_input["path"],
                    offset=tool_input.get("offset"),
                    limit=tool_input.get("limit"),
                )
                return ToolResult(
                    tool_use_id="",
                    content=result.content,
                    is_error=result.is_error,
                )

            elif tool_name == "write_file":
                result = self.write_file.execute(
                    path=tool_input["path"],
                    content=tool_input["content"],
                )
                return ToolResult(
                    tool_use_id="",
                    content=result.content,
                    is_error=result.is_error,
                )

            elif tool_name == "edit_file":
                result = self.edit_file.execute(
                    path=tool_input["path"],
                    old_string=tool_input["old_string"],
                    new_string=tool_input["new_string"],
                    replace_all=tool_input.get("replace_all", False),
                )
                return ToolResult(
                    tool_use_id="",
                    content=result.content,
                    is_error=result.is_error,
                )

            elif tool_name == "glob":
                result = self.glob.execute(
                    pattern=tool_input["pattern"],
                    directory=tool_input.get("directory"),
                )
                return ToolResult(
                    tool_use_id="",
                    content=result.content,
                    is_error=result.is_error,
                )

            elif tool_name == "grep":
                result = self.grep.execute(
                    pattern=tool_input["pattern"],
                    path=tool_input.get("path"),
                    glob_pattern=tool_input.get("glob_pattern"),
                    ignore_case=tool_input.get("ignore_case", False),
                    context_lines=tool_input.get("context_lines", 0),
                )
                return ToolResult(
                    tool_use_id="",
                    content=result.content,
                    is_error=result.is_error,
                )

            elif tool_name == "web_fetch":
                result = self.web_fetch.execute(tool_input["url"])
                return ToolResult(
                    tool_use_id="",
                    content=result.content,
                    is_error=result.is_error,
                )

            else:
                return ToolResult(
                    tool_use_id="",
                    content=f"Unknown tool: {tool_name}",
                    is_error=True,
                )

        except KeyError as e:
            return ToolResult(
                tool_use_id="",
                content=f"Missing required parameter: {e}",
                is_error=True,
            )

        except Exception as e:
            logger.error(f"Tool execution error: {e}")
            return ToolResult(
                tool_use_id="",
                content=f"Tool execution error: {str(e)}",
                is_error=True,
            )


def create_tool_executor(working_dir: str) -> callable:
    """
    Create a tool executor function for use with VertexClient.

    Args:
        working_dir: Working directory for tools.

    Returns:
        A function that executes tools and returns ToolResult.
    """
    executor = ToolExecutor(working_dir)

    def execute_tool(tool_name: str, tool_input: dict) -> ToolResult:
        return executor.execute(tool_name, tool_input)

    return execute_tool

