"""
Vertex AI client for Claude models with tool execution support.

This module provides a high-level interface to interact with Claude models
on Google Cloud Vertex AI, including automatic tool execution loops.
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from anthropic import AnthropicVertex

logger = logging.getLogger(__name__)


class ToolResult(Protocol):
    """Protocol for tool results."""

    tool_use_id: str
    content: str
    is_error: bool


@dataclass
class ConversationMessage:
    """A message in the conversation for streaming/logging."""

    type: str  # "user", "assistant", "tool_use", "tool_result", "text", "thinking"
    content: Any
    tool_name: str | None = None
    tool_use_id: str | None = None
    is_error: bool = False


@dataclass
class AgentResult:
    """Final result from running the agent."""

    output: str
    success: bool
    error: str | None = None
    conversation: list[ConversationMessage] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class VertexClient:
    """
    Client for interacting with Claude models on Vertex AI.

    Handles:
    - API calls to Vertex AI
    - Tool execution loops
    - Conversation state management
    - Streaming callbacks
    """

    def __init__(
        self,
        project_id: str | None = None,
        region: str | None = None,
        model: str | None = None,
        max_tokens: int = 8192,
    ):
        """
        Initialize the Vertex AI client.

        Args:
            project_id: GCP project ID. Defaults to ANTHROPIC_VERTEX_PROJECT_ID env var.
            region: GCP region. Defaults to CLOUD_ML_REGION env var.
            model: Model name. Defaults to ANTHROPIC_MODEL env var or claude-3-5-sonnet-v2@20241022.
            max_tokens: Maximum tokens in response.
        """
        self.project_id = project_id or os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID")
        self.region = region or os.environ.get("CLOUD_ML_REGION", "us-east5")
        self.model = model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5@20250929")
        self.max_tokens = max_tokens

        if not self.project_id:
            raise ValueError(
                "project_id must be provided or set via ANTHROPIC_VERTEX_PROJECT_ID"
            )

        self.client = AnthropicVertex(
            project_id=self.project_id,
            region=self.region,
        )

    async def run(
        self,
        prompt: str,
        system_prompt: str,
        tools: list[dict],
        tool_executor: Callable[[str, dict], ToolResult],
        on_message: Callable[[ConversationMessage], None] | None = None,
        max_iterations: int = 100,
    ) -> AgentResult:
        """
        Run a conversation with the model, executing tools as needed.

        Args:
            prompt: The user's initial prompt.
            system_prompt: System instructions (your MD files content).
            tools: List of tool definitions in Anthropic format.
            tool_executor: Function that executes tools and returns results.
            on_message: Optional callback for streaming messages.
            max_iterations: Maximum tool execution iterations to prevent infinite loops.

        Returns:
            AgentResult with the final output and conversation history.
        """
        messages = [{"role": "user", "content": prompt}]
        conversation: list[ConversationMessage] = []
        total_input_tokens = 0
        total_output_tokens = 0

        def emit(msg: ConversationMessage) -> None:
            """Add message to conversation and call callback if set."""
            conversation.append(msg)
            if on_message:
                on_message(msg)

        # Emit the initial user message
        emit(ConversationMessage(type="user", content=prompt))

        for iteration in range(max_iterations):
            logger.info(f"Iteration {iteration + 1}/{max_iterations}")

            try:
                # Make API call (run in thread pool since anthropic SDK is sync)
                response = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self.client.messages.create(
                        model=self.model,
                        max_tokens=self.max_tokens,
                        system=system_prompt,
                        messages=messages,
                        tools=tools if tools else None,
                    ),
                )
            except Exception as e:
                logger.error(f"API call failed: {e}")
                return AgentResult(
                    output="",
                    success=False,
                    error=str(e),
                    conversation=conversation,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                )

            # Track token usage
            total_input_tokens += response.usage.input_tokens
            total_output_tokens += response.usage.output_tokens

            # Process response content blocks
            assistant_content = []
            tool_uses = []
            text_parts = []

            for block in response.content:
                if block.type == "text":
                    text_parts.append(block.text)
                    emit(ConversationMessage(type="text", content=block.text))
                    assistant_content.append({"type": "text", "text": block.text})

                elif block.type == "tool_use":
                    tool_uses.append(block)
                    emit(
                        ConversationMessage(
                            type="tool_use",
                            content=block.input,
                            tool_name=block.name,
                            tool_use_id=block.id,
                        )
                    )
                    assistant_content.append(
                        {
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                        }
                    )

                elif hasattr(block, "thinking"):
                    # Extended thinking block (if enabled)
                    emit(ConversationMessage(type="thinking", content=block.thinking))

            # Add assistant response to messages
            messages.append({"role": "assistant", "content": assistant_content})

            # Check if we're done (no tool uses and stop reason is end_turn)
            if response.stop_reason == "end_turn" and not tool_uses:
                logger.info("Conversation complete (end_turn)")
                return AgentResult(
                    output="\n".join(text_parts),
                    success=True,
                    conversation=conversation,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                )

            # Execute tools and collect results
            if tool_uses:
                tool_results = []
                for tool_use in tool_uses:
                    logger.info(f"Executing tool: {tool_use.name}")
                    try:
                        result = tool_executor(tool_use.name, tool_use.input)
                        emit(
                            ConversationMessage(
                                type="tool_result",
                                content=result.content,
                                tool_use_id=tool_use.id,
                                is_error=result.is_error,
                            )
                        )
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_use.id,
                                "content": result.content,
                                "is_error": result.is_error,
                            }
                        )
                    except Exception as e:
                        logger.error(f"Tool execution failed: {e}")
                        error_msg = f"Tool execution error: {str(e)}"
                        emit(
                            ConversationMessage(
                                type="tool_result",
                                content=error_msg,
                                tool_use_id=tool_use.id,
                                is_error=True,
                            )
                        )
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_use.id,
                                "content": error_msg,
                                "is_error": True,
                            }
                        )

                # Add tool results to messages
                messages.append({"role": "user", "content": tool_results})

            # If stop reason is not tool_use and no tools, we're done
            if response.stop_reason != "tool_use":
                logger.info(f"Conversation complete (stop_reason={response.stop_reason})")
                return AgentResult(
                    output="\n".join(text_parts),
                    success=True,
                    conversation=conversation,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                )

        # Max iterations reached
        logger.warning(f"Max iterations ({max_iterations}) reached")
        return AgentResult(
            output="\n".join(text_parts) if text_parts else "",
            success=False,
            error=f"Max iterations ({max_iterations}) reached without completion",
            conversation=conversation,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
        )

