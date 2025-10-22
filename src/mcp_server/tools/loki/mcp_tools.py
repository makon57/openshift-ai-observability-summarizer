"""MCP tool functions for Loki log analysis.

This module provides async MCP tools for interacting with Loki logs:
- query_loki_tool: Search logs by service, namespace, time range
- search_logs_tool: Search logs by content patterns
- analyze_error_logs_tool: Analyze error patterns in logs
- chat_loki_tool: Conversational interface for Loki log analysis
"""

import re
from typing import Dict, Any, List
from datetime import datetime, timedelta

from common.pylogger import get_python_logger
from core.logql_service import generate_logql_from_question, extract_log_patterns_from_question

from .query_tool import LokiQueryTool
from .error_handling import LogPatternDetector

logger = get_python_logger()


async def query_loki_tool(
    logql: str,
    start_time: str,
    end_time: str,
    limit: int = LokiQueryTool.DEFAULT_QUERY_LIMIT
) -> List[Dict[str, Any]]:
    """
    MCP tool function for querying Loki logs.

    Args:
        logql: LogQL query string (e.g., '{namespace="default", app="myapp"}' or '{app="myapp"} |= "error"')
        start_time: Start time in ISO format (e.g., "2024-01-01T00:00:00Z")
        end_time: End time in ISO format (e.g., "2024-01-01T23:59:59Z")
        limit: Maximum number of log entries to return (default: DEFAULT_QUERY_LIMIT)

    Returns:
        List of log entries with analysis
    """
    loki_tool = LokiQueryTool()
    result = await loki_tool.query_logs(logql, start_time, end_time, limit)

    if result["success"]:
        content = f"📋 **Loki Query Results**\n\n"
        content += f"**LogQL Query**: `{result['query']}`\n"
        content += f"**Time Range**: {result['time_range']}\n"
        content += f"**Found**: {result['total']} log entries\n\n"

        if result["logs"]:
            # Analyze log patterns
            error_count = 0
            warning_count = 0
            services = set()

            content += "**Log Analysis**:\n"
            for log_entry in result["logs"][:10]:  # Show first 10 entries
                timestamp = log_entry.get("timestamp", "unknown")
                level = log_entry.get("level", "unknown")
                message = log_entry.get("message", log_entry.get("log", ""))[:100]  # Truncate long messages

                # Count log levels
                if LogPatternDetector.is_error_log(log_entry):
                    error_count += 1
                elif LogPatternDetector.is_warning_log(log_entry):
                    warning_count += 1

                # Collect service information
                service_info = LogPatternDetector.extract_service_info(log_entry)
                services.add(service_info["service_name"])

                level_icon = {"error": "🚨", "warning": "⚠️", "info": "ℹ️", "debug": "🔍"}.get(level.lower(), "📝")
                content += f"{level_icon} **{timestamp}** [{level.upper()}] {message}...\n"

            if len(result["logs"]) > 10:
                content += f"... and {len(result['logs']) - 10} more log entries\n"

            # Summary statistics
            content += f"\n**Summary**:\n"
            content += f"- **Services**: {', '.join(services) if services else 'Unknown'}\n"
            content += f"- **Error logs**: {error_count}\n"
            content += f"- **Warning logs**: {warning_count}\n"
            content += f"- **Info/Debug logs**: {result['total'] - error_count - warning_count}\n"
        else:
            content += "No log entries found matching the query.\n"

        return [{"type": "text", "text": content}]
    else:
        error_content = result['error']

        # Add helpful deployment instructions for local development
        if "not reachable" in result['error'] or "not known" in result['error']:
            error_content += "\n\n💡 **Note**: To use Loki queries, deploy the MCP server to OpenShift where Loki is running.\n"
            error_content += "   Local development cannot access the Loki service in the observability-hub namespace.\n"

        return [{"type": "text", "text": error_content}]


async def search_logs_tool(
    search_terms: str,
    namespace: str = None,
    service_name: str = None,
    log_level: str = None,
    start_time: str = None,
    end_time: str = None,
    limit: int = 500
) -> List[Dict[str, Any]]:
    """
    MCP tool function for searching logs by content patterns.

    Args:
        search_terms: Text to search for in log messages
        namespace: Kubernetes namespace to filter by (optional)
        service_name: Service name to filter by (optional)
        log_level: Log level to filter by (error, warning, info, debug) (optional)
        start_time: Start time in ISO format (optional, defaults to last hour)
        end_time: End time in ISO format (optional, defaults to now)
        limit: Maximum number of log entries to return

    Returns:
        Filtered log entries with highlighted matches
    """
    # Default time range to last hour if not provided
    if not start_time or not end_time:
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(hours=1)
        start_time = start_dt.isoformat() + "Z"
        end_time = end_dt.isoformat() + "Z"

    # Build LogQL query
    label_filters = []
    if namespace:
        label_filters.append(f'namespace="{namespace}"')
    if service_name:
        label_filters.append(f'service_name="{service_name}"')

    base_selector = "{" + ", ".join(label_filters) + "}" if label_filters else '{job="application"}'

    # Add content filtering
    if search_terms:
        # Use case-insensitive regex search
        logql = f'{base_selector} |~ "(?i){re.escape(search_terms)}"'
    else:
        logql = base_selector

    # Add log level filtering
    if log_level:
        logql += f' | json | level="{log_level.lower()}"'

    logger.info(f"Searching logs with query: {logql}")

    loki_tool = LokiQueryTool()
    result = await loki_tool.query_logs(logql, start_time, end_time, limit)

    if result["success"]:
        content = f"🔍 **Log Search Results**\n\n"
        content += f"**Search Terms**: '{search_terms}'\n"
        content += f"**Filters**: Namespace={namespace or 'Any'}, Service={service_name or 'Any'}, Level={log_level or 'Any'}\n"
        content += f"**Time Range**: {result['time_range']}\n"
        content += f"**Found**: {result['total']} matching log entries\n\n"

        if result["logs"]:
            # Group logs by service for better organization
            logs_by_service = {}
            for log_entry in result["logs"]:
                service_info = LogPatternDetector.extract_service_info(log_entry)
                service = service_info["service_name"]
                if service not in logs_by_service:
                    logs_by_service[service] = []
                logs_by_service[service].append(log_entry)

            content += "**Matching Logs by Service**:\n\n"
            for service, logs in logs_by_service.items():
                content += f"### 🔧 **{service}** ({len(logs)} entries)\n"

                for log_entry in logs[:5]:  # Show first 5 per service
                    timestamp = log_entry.get("timestamp", "unknown")
                    level = log_entry.get("level", "unknown")
                    message = log_entry.get("message", log_entry.get("log", ""))

                    # Highlight search terms in message
                    if search_terms:
                        highlighted_message = re.sub(
                            f"({re.escape(search_terms)})",
                            r"**\1**",
                            message,
                            flags=re.IGNORECASE
                        )[:200]  # Truncate long messages
                    else:
                        highlighted_message = message[:200]

                    level_icon = {"error": "🚨", "warning": "⚠️", "info": "ℹ️", "debug": "🔍"}.get(level.lower(), "📝")
                    content += f"  {level_icon} **{timestamp}** {highlighted_message}...\n"

                if len(logs) > 5:
                    content += f"  ... and {len(logs) - 5} more entries for this service\n"
                content += "\n"
        else:
            content += "No log entries found matching the search criteria.\n"
            content += "\n**Suggestions**:\n"
            content += "- Try broader search terms\n"
            content += "- Expand the time range\n"
            content += "- Check if the service is generating logs\n"

        return [{"type": "text", "text": content}]
    else:
        return [{"type": "text", "text": f"Search failed: {result['error']}"}]


async def analyze_error_logs_tool(
    namespace: str = None,
    service_name: str = None,
    start_time: str = None,
    end_time: str = None,
    limit: int = 200
) -> List[Dict[str, Any]]:
    """
    MCP tool function for analyzing error patterns in logs.

    Args:
        namespace: Kubernetes namespace to analyze (optional)
        service_name: Service name to analyze (optional)
        start_time: Start time in ISO format (optional, defaults to last 2 hours)
        end_time: End time in ISO format (optional, defaults to now)
        limit: Maximum number of log entries to analyze

    Returns:
        Analysis of error patterns with insights and recommendations
    """
    # Default time range to last 2 hours if not provided
    if not start_time or not end_time:
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(hours=2)
        start_time = start_dt.isoformat() + "Z"
        end_time = end_dt.isoformat() + "Z"

    # Build LogQL query for error logs
    label_filters = []
    if namespace:
        label_filters.append(f'namespace="{namespace}"')
    if service_name:
        label_filters.append(f'service_name="{service_name}"')

    base_selector = "{" + ", ".join(label_filters) + "}" if label_filters else '{job="application"}'

    # Query for error logs
    error_logql = f'{base_selector} | json | level="error"'

    logger.info(f"Analyzing error logs with query: {error_logql}")

    loki_tool = LokiQueryTool()
    result = await loki_tool.query_logs(error_logql, start_time, end_time, limit)

    if result["success"]:
        logs = result.get("logs", [])

        content = f"🚨 **Error Log Analysis**\n\n"
        content += f"**Scope**: Namespace={namespace or 'All'}, Service={service_name or 'All'}\n"
        content += f"**Time Range**: {result['time_range']}\n"
        content += f"**Error Count**: {len(logs)} error log entries\n\n"

        if logs:
            # Analyze error patterns
            error_types = {}
            services_with_errors = {}
            error_timeline = {}

            for log_entry in logs:
                # Classify error type
                error_type = LogPatternDetector.extract_error_type(log_entry)
                error_types[error_type] = error_types.get(error_type, 0) + 1

                # Track services with errors
                service_info = LogPatternDetector.extract_service_info(log_entry)
                service = service_info["service_name"]
                services_with_errors[service] = services_with_errors.get(service, 0) + 1

                # Create timeline (by hour)
                timestamp = log_entry.get("timestamp", "")
                if timestamp:
                    hour = timestamp[:13]  # YYYY-MM-DDTHH
                    error_timeline[hour] = error_timeline.get(hour, 0) + 1

            # Error type analysis
            content += "## 📊 **Error Type Analysis**\n\n"
            for error_type, count in sorted(error_types.items(), key=lambda x: x[1], reverse=True):
                percentage = (count / len(logs)) * 100
                content += f"- **{error_type.title()}**: {count} errors ({percentage:.1f}%)\n"

            # Services with most errors
            content += f"\n## 🔧 **Services with Errors**\n\n"
            for service, count in sorted(services_with_errors.items(), key=lambda x: x[1], reverse=True)[:5]:
                percentage = (count / len(logs)) * 100
                content += f"- **{service}**: {count} errors ({percentage:.1f}%)\n"

            # Recent error samples
            content += f"\n## 🔍 **Recent Error Samples**\n\n"
            recent_errors = sorted(logs, key=lambda x: x.get("timestamp", ""), reverse=True)[:5]

            for i, error_log in enumerate(recent_errors, 1):
                timestamp = error_log.get("timestamp", "unknown")
                message = error_log.get("message", error_log.get("log", ""))[:150]
                service_info = LogPatternDetector.extract_service_info(error_log)

                content += f"**{i}. {service_info['service_name']}** - {timestamp}\n"
                content += f"   ```\n   {message}...\n   ```\n"

            # Error timeline
            if len(error_timeline) > 1:
                content += f"\n## ⏰ **Error Timeline** (by hour)\n\n"
                for hour in sorted(error_timeline.keys())[-6:]:  # Last 6 hours
                    count = error_timeline[hour]
                    bar = "█" * min(count // 5, 20)  # Simple bar chart
                    content += f"- **{hour}:00**: {count} errors {bar}\n"

            # Recommendations
            content += f"\n## 💡 **Recommendations**\n\n"

            if error_types.get("database", 0) > len(logs) * 0.3:
                content += "- **Database Issues**: High number of database errors detected. Check database connectivity and performance.\n"

            if error_types.get("connection", 0) > len(logs) * 0.2:
                content += "- **Connection Problems**: Multiple connection errors found. Verify network connectivity and service discovery.\n"

            if error_types.get("timeout", 0) > len(logs) * 0.2:
                content += "- **Timeout Issues**: Consider increasing timeout values or optimizing slow operations.\n"

            if len(services_with_errors) == 1:
                service_name = list(services_with_errors.keys())[0]
                content += f"- **Single Service Impact**: All errors are from **{service_name}**. Focus investigation on this service.\n"
            elif len(services_with_errors) > 5:
                content += "- **Widespread Issues**: Multiple services affected. Check for infrastructure or shared dependency problems.\n"

            content += f"- **Investigate Top Error**: Focus on **{list(error_types.keys())[0]}** errors as they represent the majority.\n"
            content += "- **Use trace correlation**: Cross-reference error timestamps with distributed traces for deeper analysis.\n"

        else:
            content += "✅ **No error logs found in the specified time range and scope.**\n\n"
            content += "This indicates:\n"
            content += "- Services are operating normally\n"
            content += "- Error logs may be using different log levels or formats\n"
            content += "- Consider expanding the time range or scope\n"

        return [{"type": "text", "text": content}]
    else:
        return [{"type": "text", "text": f"Error analysis failed: {result['error']}"}]


def extract_time_range_from_question(question: str) -> str:
    """Extract time range from user question for log analysis"""
    question_lower = question.lower()

    # Check for specific time ranges (same as tempo tools)
    if "last 24 hours" in question_lower or "last 24h" in question_lower or "yesterday" in question_lower:
        return "last 24h"
    elif "last week" in question_lower or "last 7 days" in question_lower:
        return "last 7d"
    elif "last month" in question_lower or "last 30 days" in question_lower:
        return "last 30d"
    elif "last 2 hours" in question_lower or "last 2h" in question_lower:
        return "last 2h"
    elif "last 6 hours" in question_lower or "last 6h" in question_lower:
        return "last 6h"
    elif "last 12 hours" in question_lower or "last 12h" in question_lower:
        return "last 12h"
    elif "last hour" in question_lower or "last 1h" in question_lower:
        return "last 1h"
    elif "last 30 minutes" in question_lower or "last 30m" in question_lower:
        return "last 30m"
    elif "last 15 minutes" in question_lower or "last 15m" in question_lower:
        return "last 15m"
    elif "last 5 minutes" in question_lower or "last 5m" in question_lower:
        return "last 5m"
    else:
        # Default to 2 hours for log analysis (shorter than traces due to volume)
        return "last 2h"


async def chat_loki_tool(question: str) -> List[Dict[str, Any]]:
    """
    MCP tool function for conversational Loki log analysis.

    This tool provides a conversational interface for analyzing logs, allowing users to ask
    questions about log patterns, errors, performance issues, and application behavior.

    Args:
        question: Natural language question about logs (e.g., "Show me error logs from last hour",
                 "What services are logging warnings today?", "Find database errors yesterday")

    Returns:
        Conversational analysis of logs with insights and recommendations
    """
    loki_tool = LokiQueryTool()

    try:
        # Extract time range from the question
        extracted_time_range = extract_time_range_from_question(question)
        logger.info(f"Extracted time range from question: {extracted_time_range}")

        # Parse time range to get start and end times
        now = datetime.now()
        if extracted_time_range.startswith("last "):
            duration_str = extracted_time_range[5:]  # Remove "last "
            if duration_str.endswith("h"):
                hours = int(duration_str[:-1])
                start_time = now - timedelta(hours=hours)
            elif duration_str.endswith("d"):
                days = int(duration_str[:-1])
                start_time = now - timedelta(days=days)
            elif duration_str.endswith("m"):
                minutes = int(duration_str[:-1])
                start_time = now - timedelta(minutes=minutes)
            else:
                # Default to 2 hours
                start_time = now - timedelta(hours=2)
        else:
            # Default to 2 hours
            start_time = now - timedelta(hours=2)

        end_time = now

        # Convert to ISO format
        start_iso = start_time.isoformat() + "Z"
        end_iso = end_time.isoformat() + "Z"

        # Analyze the question and generate appropriate LogQL queries
        question_lower = question.lower()

        # Extract patterns from the question
        patterns = extract_log_patterns_from_question(question)

        # Generate LogQL queries based on the question
        logql_queries = generate_logql_from_question(
            question,
            patterns.get("service_name"),
            int(start_time.timestamp()),
            int(end_time.timestamp())
        )

        if not logql_queries:
            # Fallback to basic query
            logql_queries = ['{job="application"}']

        # Use the first (most relevant) query
        primary_query = logql_queries[0]

        logger.info(f"Executing Loki query: '{primary_query}' for time range {start_iso} to {end_iso}")
        result = await loki_tool.query_logs(primary_query, start_iso, end_iso, limit=LokiQueryTool.DEFAULT_CHAT_QUERY_LIMIT)

        if result["success"]:
            logs = result.get("logs", [])

            # Generate conversational analysis
            content = f"📋 **Loki Chat Analysis**\n\n"
            content += f"**Question**: {question}\n"
            content += f"**Time Range**: {extracted_time_range}\n"
            content += f"**LogQL Query**: `{primary_query}`\n"
            content += f"**Found**: {len(logs)} log entries\n\n"

            if logs:
                # Analyze log patterns
                error_logs = []
                warning_logs = []
                services = {}
                log_levels = {}

                for log_entry in logs:
                    # Classify logs
                    if LogPatternDetector.is_error_log(log_entry):
                        error_logs.append(log_entry)
                    elif LogPatternDetector.is_warning_log(log_entry):
                        warning_logs.append(log_entry)

                    # Count by service
                    service_info = LogPatternDetector.extract_service_info(log_entry)
                    service = service_info["service_name"]
                    services[service] = services.get(service, 0) + 1

                    # Count by log level
                    level = log_entry.get("level", "unknown")
                    log_levels[level] = log_levels.get(level, 0) + 1

                # Generate insights
                content += "## 📊 **Analysis Results**\n\n"

                # Service activity
                if services:
                    content += "**Service Activity**:\n"
                    for service, count in sorted(services.items(), key=lambda x: x[1], reverse=True)[:5]:
                        content += f"- **{service}**: {count} log entries\n"
                    content += "\n"

                # Log level distribution
                if log_levels:
                    content += "**Log Level Distribution**:\n"
                    for level, count in sorted(log_levels.items(), key=lambda x: x[1], reverse=True):
                        level_icon = {"error": "🚨", "warning": "⚠️", "info": "ℹ️", "debug": "🔍"}.get(level.lower(), "📝")
                        percentage = (count / len(logs)) * 100
                        content += f"- {level_icon} **{level.title()}**: {count} ({percentage:.1f}%)\n"
                    content += "\n"

                # Error analysis
                if error_logs:
                    content += f"## 🚨 **Error Analysis** ({len(error_logs)} errors found)\n\n"

                    # Group errors by type
                    error_types = {}
                    for error_log in error_logs:
                        error_type = LogPatternDetector.extract_error_type(error_log)
                        error_types[error_type] = error_types.get(error_type, 0) + 1

                    content += "**Error Types**:\n"
                    for error_type, count in sorted(error_types.items(), key=lambda x: x[1], reverse=True):
                        content += f"- **{error_type.title()}**: {count} errors\n"

                    # Show recent errors
                    content += "\n**Recent Errors**:\n"
                    recent_errors = sorted(error_logs, key=lambda x: x.get("timestamp", ""), reverse=True)[:3]
                    for i, error_log in enumerate(recent_errors, 1):
                        service_info = LogPatternDetector.extract_service_info(error_log)
                        message = error_log.get("message", error_log.get("log", ""))[:100]
                        content += f"{i}. **{service_info['service_name']}**: {message}...\n"
                    content += "\n"

                # Warning analysis
                if warning_logs:
                    content += f"## ⚠️ **Warning Analysis** ({len(warning_logs)} warnings found)\n\n"

                    # Show recent warnings
                    recent_warnings = sorted(warning_logs, key=lambda x: x.get("timestamp", ""), reverse=True)[:3]
                    for i, warning_log in enumerate(recent_warnings, 1):
                        service_info = LogPatternDetector.extract_service_info(warning_log)
                        message = warning_log.get("message", warning_log.get("log", ""))[:100]
                        content += f"{i}. **{service_info['service_name']}**: {message}...\n"
                    content += "\n"

                # Recommendations
                content += "## 💡 **Recommendations**\n\n"

                if error_logs:
                    error_rate = len(error_logs) / len(logs) * 100
                    if error_rate > 10:
                        content += f"- **High Error Rate**: {error_rate:.1f}% of logs are errors - investigate immediately\n"
                    content += f"- **Focus on {list(error_types.keys())[0] if error_types else 'unknown'} errors** as they are most common\n"

                if len(services) == 1:
                    service_name = list(services.keys())[0]
                    content += f"- **Single Service**: All logs from **{service_name}** - focus investigation here\n"
                elif len(services) > 10:
                    content += "- **Multiple Services**: Many services active - check for system-wide issues\n"

                content += "- **Correlate with metrics**: Check corresponding Prometheus metrics for these services\n"
                content += "- **Trace correlation**: Use distributed tracing to understand request flows\n"

                # Sample log entries for context
                content += f"\n## 📝 **Sample Log Entries**\n\n"
                sample_logs = logs[:3]
                for i, log_entry in enumerate(sample_logs, 1):
                    timestamp = log_entry.get("timestamp", "unknown")
                    level = log_entry.get("level", "unknown")
                    message = log_entry.get("message", log_entry.get("log", ""))[:150]
                    service_info = LogPatternDetector.extract_service_info(log_entry)

                    level_icon = {"error": "🚨", "warning": "⚠️", "info": "ℹ️", "debug": "🔍"}.get(level.lower(), "📝")
                    content += f"**{i}. {service_info['service_name']}** - {timestamp}\n"
                    content += f"   {level_icon} [{level.upper()}] {message}...\n\n"

            else:
                content += "No log entries found for the specified criteria.\n\n"
                content += "**Suggestions**:\n"
                content += "- Try a broader time range\n"
                content += "- Check if services are actively logging\n"
                content += "- Verify LogQL query syntax\n"
                content += "- Ensure services have proper log forwarding configured\n"

            return [{"type": "text", "text": content}]
        else:
            error_content = f"Failed to analyze logs: {result['error']}\n\n"
            error_content += "**Troubleshooting**:\n"
            error_content += "- Check if Loki is accessible\n"
            error_content += "- Verify authentication credentials\n"
            error_content += "- Try a different time range\n"
            error_content += "- Ensure log forwarding is configured\n"

            return [{"type": "text", "text": error_content}]

    except Exception as e:
        logger.error(f"Loki chat error: {e}")
        error_content = f"Error during Loki chat analysis: {str(e)}\n\n"
        error_content += "**Troubleshooting**:\n"
        error_content += "- Check Loki connectivity\n"
        error_content += "- Verify time range format\n"
        error_content += "- Try a simpler question\n"

        return [{"type": "text", "text": error_content}]
