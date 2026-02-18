"""
File operation tools: Read, Write, Edit, Glob, Grep.
"""

import fnmatch
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Limits
MAX_FILE_SIZE = 1_000_000  # 1MB
MAX_GLOB_RESULTS = 1000
MAX_GREP_RESULTS = 500


@dataclass
class FileResult:
    """Result from a file operation."""

    content: str
    is_error: bool = False


class ReadFileTool:
    """Read file contents."""

    def __init__(self, working_dir: str):
        self.working_dir = os.path.abspath(working_dir)

    def _resolve_path(self, path: str) -> str:
        """Resolve path relative to working directory."""
        if os.path.isabs(path):
            return path
        return os.path.join(self.working_dir, path)

    def execute(
        self,
        path: str,
        offset: int | None = None,
        limit: int | None = None,
    ) -> FileResult:
        """
        Read a file's contents.

        Args:
            path: File path (relative or absolute).
            offset: Line number to start reading from (1-indexed).
            limit: Number of lines to read.

        Returns:
            FileResult with file contents or error.
        """
        full_path = self._resolve_path(path)

        if not os.path.exists(full_path):
            return FileResult(
                content=f"File not found: {path}",
                is_error=True,
            )

        if not os.path.isfile(full_path):
            return FileResult(
                content=f"Not a file: {path}",
                is_error=True,
            )

        # Check file size
        file_size = os.path.getsize(full_path)
        if file_size > MAX_FILE_SIZE:
            return FileResult(
                content=f"File too large ({file_size} bytes). Max: {MAX_FILE_SIZE} bytes. "
                f"Use offset/limit parameters to read portions.",
                is_error=True,
            )

        try:
            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                if offset is not None or limit is not None:
                    lines = f.readlines()
                    start = (offset or 1) - 1  # Convert to 0-indexed
                    end = start + (limit or len(lines))
                    selected_lines = lines[start:end]

                    # Add line numbers
                    numbered = [
                        f"{start + i + 1:6}|{line.rstrip()}"
                        for i, line in enumerate(selected_lines)
                    ]
                    content = "\n".join(numbered)
                else:
                    lines = f.readlines()
                    # Add line numbers
                    numbered = [
                        f"{i + 1:6}|{line.rstrip()}" for i, line in enumerate(lines)
                    ]
                    content = "\n".join(numbered)

            return FileResult(content=content)

        except Exception as e:
            logger.error(f"Error reading file {path}: {e}")
            return FileResult(
                content=f"Error reading file: {str(e)}",
                is_error=True,
            )


class WriteFileTool:
    """Write content to a file."""

    def __init__(self, working_dir: str):
        self.working_dir = os.path.abspath(working_dir)

    def _resolve_path(self, path: str) -> str:
        """Resolve path relative to working directory."""
        if os.path.isabs(path):
            return path
        return os.path.join(self.working_dir, path)

    def execute(self, path: str, content: str) -> FileResult:
        """
        Write content to a file.

        Args:
            path: File path (relative or absolute).
            content: Content to write.

        Returns:
            FileResult with success message or error.
        """
        full_path = self._resolve_path(path)

        try:
            # Create parent directories if needed
            os.makedirs(os.path.dirname(full_path), exist_ok=True)

            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)

            return FileResult(content=f"Successfully wrote {len(content)} bytes to {path}")

        except Exception as e:
            logger.error(f"Error writing file {path}: {e}")
            return FileResult(
                content=f"Error writing file: {str(e)}",
                is_error=True,
            )


class EditFileTool:
    """Edit a file using search and replace."""

    def __init__(self, working_dir: str):
        self.working_dir = os.path.abspath(working_dir)

    def _resolve_path(self, path: str) -> str:
        """Resolve path relative to working directory."""
        if os.path.isabs(path):
            return path
        return os.path.join(self.working_dir, path)

    def execute(
        self,
        path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> FileResult:
        """
        Edit a file by replacing text.

        Args:
            path: File path.
            old_string: Text to find.
            new_string: Text to replace with.
            replace_all: If True, replace all occurrences.

        Returns:
            FileResult with success message or error.
        """
        full_path = self._resolve_path(path)

        if not os.path.exists(full_path):
            return FileResult(
                content=f"File not found: {path}",
                is_error=True,
            )

        try:
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Check if old_string exists
            if old_string not in content:
                return FileResult(
                    content=f"String not found in file: {old_string[:100]}...",
                    is_error=True,
                )

            # Count occurrences
            count = content.count(old_string)

            if not replace_all and count > 1:
                return FileResult(
                    content=f"String found {count} times. Use replace_all=true to replace all, "
                    f"or provide more context to make the match unique.",
                    is_error=True,
                )

            # Perform replacement
            if replace_all:
                new_content = content.replace(old_string, new_string)
                replaced_count = count
            else:
                new_content = content.replace(old_string, new_string, 1)
                replaced_count = 1

            with open(full_path, "w", encoding="utf-8") as f:
                f.write(new_content)

            return FileResult(
                content=f"Successfully replaced {replaced_count} occurrence(s) in {path}"
            )

        except Exception as e:
            logger.error(f"Error editing file {path}: {e}")
            return FileResult(
                content=f"Error editing file: {str(e)}",
                is_error=True,
            )


class GlobTool:
    """Find files matching a glob pattern."""

    def __init__(self, working_dir: str):
        self.working_dir = os.path.abspath(working_dir)

    def execute(self, pattern: str, directory: str | None = None) -> FileResult:
        """
        Find files matching a glob pattern.

        Args:
            pattern: Glob pattern (e.g., "**/*.go").
            directory: Directory to search in (default: working_dir).

        Returns:
            FileResult with matching file paths.
        """
        search_dir = directory or self.working_dir
        if not os.path.isabs(search_dir):
            search_dir = os.path.join(self.working_dir, search_dir)

        if not os.path.isdir(search_dir):
            return FileResult(
                content=f"Directory not found: {search_dir}",
                is_error=True,
            )

        try:
            # Use pathlib for recursive glob
            base = Path(search_dir)

            # Ensure pattern supports recursive matching
            if not pattern.startswith("**/") and "**" not in pattern:
                pattern = "**/" + pattern

            matches = list(base.glob(pattern))

            # Filter out directories, keep only files
            files = [str(m.relative_to(base)) for m in matches if m.is_file()]

            # Sort and limit
            files.sort()
            if len(files) > MAX_GLOB_RESULTS:
                files = files[:MAX_GLOB_RESULTS]
                truncated = f"\n...[truncated, showing {MAX_GLOB_RESULTS} of {len(matches)}]"
            else:
                truncated = ""

            if not files:
                return FileResult(content=f"No files match pattern: {pattern}")

            return FileResult(content="\n".join(files) + truncated)

        except Exception as e:
            logger.error(f"Error in glob {pattern}: {e}")
            return FileResult(
                content=f"Error in glob: {str(e)}",
                is_error=True,
            )


class GrepTool:
    """Search file contents using regex."""

    def __init__(self, working_dir: str):
        self.working_dir = os.path.abspath(working_dir)

    def execute(
        self,
        pattern: str,
        path: str | None = None,
        glob_pattern: str | None = None,
        ignore_case: bool = False,
        context_lines: int = 0,
    ) -> FileResult:
        """
        Search for a pattern in files.

        Args:
            pattern: Regex pattern to search for.
            path: Specific file or directory to search.
            glob_pattern: Glob pattern to filter files (e.g., "*.go").
            ignore_case: Case-insensitive search.
            context_lines: Number of context lines before/after match.

        Returns:
            FileResult with matching lines.
        """
        search_path = path or self.working_dir
        if not os.path.isabs(search_path):
            search_path = os.path.join(self.working_dir, search_path)

        try:
            flags = re.IGNORECASE if ignore_case else 0
            regex = re.compile(pattern, flags)
        except re.error as e:
            return FileResult(
                content=f"Invalid regex pattern: {str(e)}",
                is_error=True,
            )

        results = []
        files_searched = 0

        def search_file(filepath: str) -> list[str]:
            """Search a single file and return matching lines."""
            matches = []
            try:
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()

                for i, line in enumerate(lines):
                    if regex.search(line):
                        rel_path = os.path.relpath(filepath, self.working_dir)

                        if context_lines > 0:
                            # Include context
                            start = max(0, i - context_lines)
                            end = min(len(lines), i + context_lines + 1)
                            for j in range(start, end):
                                prefix = ":" if j == i else "-"
                                matches.append(
                                    f"{rel_path}{prefix}{j + 1}{prefix}{lines[j].rstrip()}"
                                )
                            matches.append("--")
                        else:
                            matches.append(f"{rel_path}:{i + 1}:{line.rstrip()}")

            except Exception:
                pass  # Skip files that can't be read

            return matches

        if os.path.isfile(search_path):
            # Search single file
            results.extend(search_file(search_path))
            files_searched = 1
        else:
            # Search directory
            base = Path(search_path)
            file_pattern = glob_pattern or "**/*"
            if not file_pattern.startswith("**/"):
                file_pattern = "**/" + file_pattern

            for filepath in base.glob(file_pattern):
                if filepath.is_file() and not any(
                    part.startswith(".") for part in filepath.parts
                ):
                    # Skip hidden files/directories and common excludes
                    rel = str(filepath.relative_to(base))
                    if any(
                        x in rel
                        for x in ["vendor/", "node_modules/", ".git/", "_output/"]
                    ):
                        continue

                    results.extend(search_file(str(filepath)))
                    files_searched += 1

                    if len(results) > MAX_GREP_RESULTS:
                        break

        if not results:
            return FileResult(
                content=f"No matches found for pattern: {pattern} "
                f"(searched {files_searched} files)"
            )

        truncated = ""
        if len(results) > MAX_GREP_RESULTS:
            results = results[:MAX_GREP_RESULTS]
            truncated = f"\n...[truncated to {MAX_GREP_RESULTS} results]"

        return FileResult(content="\n".join(results) + truncated)

