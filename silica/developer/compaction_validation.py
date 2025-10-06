#!/usr/bin/env python3
"""
Validation utilities for conversation compaction.

This module provides functions to validate conversation structure and
ensure compacted conversations maintain API compatibility.
"""

from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from enum import Enum


class ValidationLevel(Enum):
    """Severity level of a validation issue."""

    ERROR = "ERROR"  # Will cause API errors
    WARNING = "WARNING"  # May cause issues
    INFO = "INFO"  # Informational only


@dataclass
class ValidationIssue:
    """Represents a validation issue found in a conversation."""

    level: ValidationLevel
    message: str
    location: Optional[str] = None  # Message index or specific location
    details: Optional[Dict[str, Any]] = None


@dataclass
class ValidationReport:
    """Report of conversation validation."""

    is_valid: bool
    issues: List[ValidationIssue]
    message_count: int
    tool_use_count: int
    tool_result_count: int
    
    def has_errors(self) -> bool:
        """Check if there are any ERROR level issues."""
        return any(issue.level == ValidationLevel.ERROR for issue in self.issues)
    
    def has_warnings(self) -> bool:
        """Check if there are any WARNING level issues."""
        return any(issue.level == ValidationLevel.WARNING for issue in self.issues)
    
    def summary(self) -> str:
        """Generate a human-readable summary of the validation report."""
        error_count = sum(1 for i in self.issues if i.level == ValidationLevel.ERROR)
        warning_count = sum(1 for i in self.issues if i.level == ValidationLevel.WARNING)
        info_count = sum(1 for i in self.issues if i.level == ValidationLevel.INFO)
        
        status = "VALID" if self.is_valid else "INVALID"
        summary = f"Validation Status: {status}\n"
        summary += f"Total Messages: {self.message_count}\n"
        summary += f"Tool Use Blocks: {self.tool_use_count}\n"
        summary += f"Tool Result Blocks: {self.tool_result_count}\n"
        summary += f"Issues: {error_count} errors, {warning_count} warnings, {info_count} info\n"
        
        return summary
    
    def detailed_report(self) -> str:
        """Generate a detailed report of all issues."""
        report = self.summary()
        
        if self.issues:
            report += "\n=== Issues ===\n"
            for issue in self.issues:
                report += f"\n[{issue.level.value}] {issue.message}\n"
                if issue.location:
                    report += f"  Location: {issue.location}\n"
                if issue.details:
                    report += f"  Details: {issue.details}\n"
        
        return report


def validate_message_structure(messages: List[Dict[str, Any]]) -> ValidationReport:
    """Validate the structure of a conversation's messages.
    
    Checks for:
    - Tool use and tool result pairing
    - Valid message roles
    - Proper message alternation (user/assistant)
    - Complete tool use blocks (no dangling tool_use without tool_result)
    
    Args:
        messages: List of message dictionaries
        
    Returns:
        ValidationReport with validation results
    """
    issues = []
    tool_use_count = 0
    tool_result_count = 0
    
    # Track tool use blocks that need results
    pending_tool_uses = {}  # tool_id -> (message_index, tool_name)
    
    for idx, message in enumerate(messages):
        role = message.get("role")
        content = message.get("content", [])
        
        # Validate role
        if role not in ["user", "assistant"]:
            issues.append(ValidationIssue(
                level=ValidationLevel.ERROR,
                message=f"Invalid message role: {role}",
                location=f"message[{idx}]"
            ))
        
        # Check alternation
        if idx > 0:
            prev_role = messages[idx - 1].get("role")
            if role == prev_role:
                issues.append(ValidationIssue(
                    level=ValidationLevel.WARNING,
                    message=f"Non-alternating messages: {prev_role} -> {role}",
                    location=f"messages[{idx-1}] -> messages[{idx}]"
                ))
        
        # Process content blocks
        if isinstance(content, list):
            for block_idx, block in enumerate(content):
                if not isinstance(block, dict):
                    continue
                
                block_type = block.get("type")
                
                if block_type == "tool_use":
                    tool_use_count += 1
                    tool_id = block.get("id")
                    tool_name = block.get("name")
                    
                    if not tool_id:
                        issues.append(ValidationIssue(
                            level=ValidationLevel.ERROR,
                            message="Tool use block missing 'id' field",
                            location=f"message[{idx}].content[{block_idx}]"
                        ))
                    elif tool_id in pending_tool_uses:
                        issues.append(ValidationIssue(
                            level=ValidationLevel.ERROR,
                            message=f"Duplicate tool_use id: {tool_id}",
                            location=f"message[{idx}].content[{block_idx}]"
                        ))
                    else:
                        pending_tool_uses[tool_id] = (idx, tool_name)
                    
                    if not tool_name:
                        issues.append(ValidationIssue(
                            level=ValidationLevel.ERROR,
                            message="Tool use block missing 'name' field",
                            location=f"message[{idx}].content[{block_idx}]"
                        ))
                
                elif block_type == "tool_result":
                    tool_result_count += 1
                    tool_use_id = block.get("tool_use_id")
                    
                    if not tool_use_id:
                        issues.append(ValidationIssue(
                            level=ValidationLevel.ERROR,
                            message="Tool result block missing 'tool_use_id' field",
                            location=f"message[{idx}].content[{block_idx}]"
                        ))
                    elif tool_use_id not in pending_tool_uses:
                        issues.append(ValidationIssue(
                            level=ValidationLevel.ERROR,
                            message=f"Tool result references unknown tool_use_id: {tool_use_id}",
                            location=f"message[{idx}].content[{block_idx}]",
                            details={"tool_use_id": tool_use_id}
                        ))
                    else:
                        # Mark this tool use as having a result
                        del pending_tool_uses[tool_use_id]
    
    # Check for incomplete tool uses (tool_use without tool_result)
    if pending_tool_uses:
        for tool_id, (msg_idx, tool_name) in pending_tool_uses.items():
            # Only consider it an error if it's not the last assistant message
            # (which might be in progress)
            is_last_message = msg_idx == len(messages) - 1
            last_is_assistant = messages[-1].get("role") == "assistant" if messages else False
            
            if is_last_message and last_is_assistant:
                issues.append(ValidationIssue(
                    level=ValidationLevel.INFO,
                    message=f"Incomplete tool use (in progress): {tool_name} (id: {tool_id})",
                    location=f"message[{msg_idx}]",
                    details={"tool_id": tool_id, "tool_name": tool_name}
                ))
            else:
                issues.append(ValidationIssue(
                    level=ValidationLevel.ERROR,
                    message=f"Tool use without result: {tool_name} (id: {tool_id})",
                    location=f"message[{msg_idx}]",
                    details={"tool_id": tool_id, "tool_name": tool_name}
                ))
    
    # Conversation is valid if there are no ERROR level issues
    is_valid = not any(issue.level == ValidationLevel.ERROR for issue in issues)
    
    return ValidationReport(
        is_valid=is_valid,
        issues=issues,
        message_count=len(messages),
        tool_use_count=tool_use_count,
        tool_result_count=tool_result_count
    )


def validate_compacted_messages(
    compacted_messages: List[Dict[str, Any]],
    original_messages: List[Dict[str, Any]],
    preserved_turns: int = 2
) -> ValidationReport:
    """Validate that compacted messages preserve the most recent turns.
    
    Args:
        compacted_messages: The compacted conversation
        original_messages: The original conversation
        preserved_turns: Number of recent turns that should be preserved
        
    Returns:
        ValidationReport with validation results
    """
    issues = []
    
    # First, validate the structure of compacted messages
    structure_report = validate_message_structure(compacted_messages)
    issues.extend(structure_report.issues)
    
    # Check if the compacted messages preserve the last N turns
    # A "turn" is a user message + assistant response
    if len(original_messages) < preserved_turns * 2:
        issues.append(ValidationIssue(
            level=ValidationLevel.INFO,
            message=f"Original conversation too short to validate {preserved_turns} preserved turns",
            details={
                "original_message_count": len(original_messages),
                "required_for_validation": preserved_turns * 2
            }
        ))
    else:
        # Get the last N turns from original
        expected_preserved = original_messages[-(preserved_turns * 2):]
        
        # Get the last N turns from compacted (skip the summary message)
        # The compacted messages should have: [summary_message, ...preserved_messages...]
        if len(compacted_messages) > 1:
            actual_preserved = compacted_messages[-(preserved_turns * 2):]
            
            # Check if they match
            if len(actual_preserved) != len(expected_preserved):
                issues.append(ValidationIssue(
                    level=ValidationLevel.WARNING,
                    message=f"Preserved message count mismatch: expected {len(expected_preserved)}, got {len(actual_preserved)}",
                    details={
                        "expected_count": len(expected_preserved),
                        "actual_count": len(actual_preserved)
                    }
                ))
            else:
                # Deep comparison (simplified - just check roles and content types)
                for i, (expected, actual) in enumerate(zip(expected_preserved, actual_preserved)):
                    if expected.get("role") != actual.get("role"):
                        issues.append(ValidationIssue(
                            level=ValidationLevel.ERROR,
                            message=f"Role mismatch in preserved message {i}",
                            location=f"preserved_message[{i}]",
                            details={
                                "expected_role": expected.get("role"),
                                "actual_role": actual.get("role")
                            }
                        ))
        else:
            issues.append(ValidationIssue(
                level=ValidationLevel.WARNING,
                message="Compacted messages too short to contain preserved turns",
                details={"compacted_count": len(compacted_messages)}
            ))
    
    # Check that the first message contains "Conversation Summary" or similar
    if compacted_messages:
        first_msg = compacted_messages[0]
        content = first_msg.get("content", "")
        
        # Convert content to string for checking
        content_str = ""
        if isinstance(content, str):
            content_str = content
        elif isinstance(content, list):
            content_str = " ".join(
                block.get("text", "") for block in content if isinstance(block, dict)
            )
        
        if "summary" not in content_str.lower() and "compacted" not in content_str.lower():
            issues.append(ValidationIssue(
                level=ValidationLevel.WARNING,
                message="First message doesn't appear to be a compaction summary",
                location="compacted_messages[0]"
            ))
    
    is_valid = not any(issue.level == ValidationLevel.ERROR for issue in issues)
    
    return ValidationReport(
        is_valid=is_valid,
        issues=issues,
        message_count=len(compacted_messages),
        tool_use_count=structure_report.tool_use_count,
        tool_result_count=structure_report.tool_result_count
    )


def validate_api_compatibility(messages: List[Dict[str, Any]]) -> ValidationReport:
    """Validate that messages are compatible with Anthropic API requirements.
    
    This is a stricter validation specifically for API compatibility.
    
    Args:
        messages: List of message dictionaries
        
    Returns:
        ValidationReport with validation results
    """
    # Start with structure validation
    report = validate_message_structure(messages)
    
    # Add additional API-specific checks
    issues = list(report.issues)
    
    # Check that conversation starts with user message
    if messages and messages[0].get("role") != "user":
        issues.append(ValidationIssue(
            level=ValidationLevel.ERROR,
            message="Conversation must start with a user message",
            location="messages[0]"
        ))
    
    # Check that conversation ends with either user message or complete assistant message
    if messages:
        last_msg = messages[-1]
        last_role = last_msg.get("role")
        
        if last_role == "assistant":
            # Check if it has incomplete tool use
            content = last_msg.get("content", [])
            if isinstance(content, list):
                has_tool_use = any(
                    isinstance(block, dict) and block.get("type") == "tool_use"
                    for block in content
                )
                if has_tool_use:
                    # This is allowed - API can be called with incomplete tool_use
                    # The next message would provide tool_results
                    pass
    
    is_valid = not any(issue.level == ValidationLevel.ERROR for issue in issues)
    
    return ValidationReport(
        is_valid=is_valid,
        issues=issues,
        message_count=report.message_count,
        tool_use_count=report.tool_use_count,
        tool_result_count=report.tool_result_count
    )
