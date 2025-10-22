"""Loki tools package for MCP server integration."""

# Import all MCP tool functions
from .mcp_tools import (
    query_loki_tool,
    search_logs_tool,
    analyze_error_logs_tool,
    chat_loki_tool,
)

# Import supporting classes for advanced usage
from .query_tool import LokiQueryTool
from .models import LogQueryResponse, LogDetailsResponse, LogAnalysisResult
from .error_handling import LokiErrorClassifier, LogPatternDetector

# Export all public interfaces
__all__ = [
    # MCP tool functions
    "query_loki_tool",
    "search_logs_tool",
    "analyze_error_logs_tool",
    "chat_loki_tool",

    # Supporting classes
    "LokiQueryTool",
    "LogQueryResponse",
    "LogDetailsResponse",
    "LogAnalysisResult",
    "LokiErrorClassifier",
    "LogPatternDetector",
]
