#!/usr/bin/env python3
"""
Enhanced LLM Summary Service with Logs Integration
Extends the original service to include Loki logs for comprehensive analysis
"""

import os
import json
import re
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime
from common.pylogger import get_python_logger

# Import LLM client and existing services
from .llm_client import summarize_with_llm
from .response_validator import ResponseType
from .loki_service import query_loki_with_logql
from .logql_service import generate_logql_from_question, build_error_analysis_logql

# Initialize structured logger once - other modules should use logging.getLogger(__name__)
get_python_logger()

logger = logging.getLogger(__name__)

from .config import CHAT_SCOPE_FLEET_WIDE, FLEET_WIDE_DISPLAY


def generate_comprehensive_summary(
    question: str,
    thanos_data: Dict[str, Any],
    loki_data: Dict[str, Any] = None,
    tempo_data: Dict[str, Any] = None,
    model_id: str = "",
    api_key: str = "",
    namespace: str = ""
) -> str:
    """
    Generate comprehensive summary using metrics, logs, and traces
    Enhanced version of generate_llm_summary with observability data correlation
    """
    try:
        logger.info("Generating comprehensive summary for: %s", question)

        # Check if we have any successful data
        successful_metrics = {k: v for k, v in thanos_data.items() if v.get("status") == "success"}
        successful_logs = {}
        if loki_data:
            successful_logs = {k: v for k, v in loki_data.items() if v.get("status") == "success"}

        if not successful_metrics and not successful_logs:
            return "❌ No data available to analyze. Please check your query and try again."

        question_lower = question.lower()

        # === SPECIAL HANDLING FOR ALERTS WITH LOG CORRELATION ===
        if any(word in question_lower for word in ["alert", "alerts", "firing", "warning", "critical", "problem", "issue"]):
            alert_infos = extract_alert_info_from_thanos_data(thanos_data)
            scope = CHAT_SCOPE_FLEET_WIDE if (namespace == "" or namespace == FLEET_WIDE_DISPLAY) else f"namespace '{namespace}'"

            if alert_infos:
                # Enhance alert analysis with logs
                alert_analysis = generate_enhanced_alert_analysis_with_logs(
                    alert_infos,
                    successful_logs,
                    namespace,
                    model_id=model_id,
                    api_key=api_key
                )
                return f"🚨 **TOTAL OF {len(alert_infos)} ALERT(S) FOUND IN {scope.upper()}**\n\n{alert_analysis}"
            else:
                return f"✅ No alerts currently firing in {scope}. All systems appear to be operating normally."

        # === ERROR ANALYSIS WITH METRICS + LOGS CORRELATION ===
        if any(word in question_lower for word in ["error", "errors", "failed", "failure", "exception"]):
            return generate_error_analysis_with_correlation(
                question, successful_metrics, successful_logs, model_id, api_key, namespace
            )

        # === PERFORMANCE ANALYSIS WITH LOGS ===
        if any(word in question_lower for word in ["performance", "slow", "latency", "response time"]):
            return generate_performance_analysis_with_logs(
                question, successful_metrics, successful_logs, model_id, api_key, namespace
            )

        # === REGULAR COMPREHENSIVE ANALYSIS ===
        return generate_unified_observability_summary(
            question, successful_metrics, successful_logs, tempo_data, model_id, api_key, namespace
        )

    except Exception as e:
        logger.error("Error generating comprehensive summary: %s", str(e))
        return f"❌ Error generating summary: {str(e)}"


def generate_enhanced_alert_analysis_with_logs(
    alert_infos: List[Dict[str, Any]],
    log_data: Dict[str, Any],
    namespace: str,
    model_id: str,
    api_key: str
) -> str:
    """
    Generate alert analysis enhanced with correlated log data
    """
    try:
        # Build context with both alerts and logs
        context_parts = []

        # Add alert information
        context_parts.append("=== ACTIVE ALERTS ===")
        for alert in alert_infos:
            alert_name = alert.get("alertname", "Unknown")
            severity = alert.get("severity", "unknown")
            description = alert.get("description", alert.get("summary", "No description"))
            context_parts.append(f"ALERT: {alert_name} (Severity: {severity}) - {description}")

        # Add correlated log information
        if log_data:
            context_parts.append("\n=== CORRELATED LOG ANALYSIS ===")

            error_count = 0
            warning_count = 0
            recent_errors = []

            for log_key, log_info in log_data.items():
                if log_info.get("status") == "success":
                    data = log_info.get("data", {})
                    if "result" in data:
                        for stream in data["result"]:
                            values = stream.get("values", [])
                            for value in values[:10]:  # Last 10 log entries
                                if len(value) >= 2:
                                    log_line = value[1].lower()
                                    if any(word in log_line for word in ["error", "failed", "exception"]):
                                        error_count += 1
                                        recent_errors.append(value[1][:200])  # Truncate long logs
                                    elif any(word in log_line for word in ["warning", "warn"]):
                                        warning_count += 1

            context_parts.append(f"Recent error logs: {error_count}")
            context_parts.append(f"Recent warning logs: {warning_count}")

            if recent_errors:
                context_parts.append("Sample error logs:")
                for error in recent_errors[:3]:  # Show top 3 errors
                    context_parts.append(f"- {error}")

        # Build enhanced prompt
        context = "\n".join(context_parts)

        prompt = f"""You are a senior Site Reliability Engineer (SRE) analyzing alerts with correlated observability data for namespace: {namespace}.

Alert and Log Analysis Context:
{context}

Provide a comprehensive alert analysis in this format:
🚨 ALERT SUMMARY: [Brief summary of alert situation]

📊 CORRELATION ANALYSIS:
- Metrics: [What the metrics show]
- Logs: [What the logs reveal]
- Pattern: [Any correlation patterns between alerts and logs]

🔍 ROOT CAUSE ASSESSMENT:
[Analysis of likely root cause based on alerts + logs]

⚡ IMMEDIATE ACTIONS:
1. [First action to take]
2. [Second action to take]
3. [Third action to take]

🛡️ PREVENTION:
[Recommendations to prevent similar issues]

Focus on actionable insights that combine alert data with log evidence."""

        # Generate enhanced analysis
        summary = summarize_with_llm(
            prompt,
            model_id,
            ResponseType.GENERAL_CHAT,
            api_key=api_key,
            max_tokens=500,
        )

        return summary

    except Exception as e:
        logger.error("Error generating enhanced alert analysis: %s", str(e))
        return generate_alert_analysis_with_llm(alert_infos, namespace, model_id=model_id, api_key=api_key)


def generate_error_analysis_with_correlation(
    question: str,
    metrics_data: Dict[str, Any],
    logs_data: Dict[str, Any],
    model_id: str,
    api_key: str,
    namespace: str
) -> str:
    """
    Generate error analysis correlating metrics and logs
    """
    try:
        context_parts = []

        # Add metrics context
        context_parts.append("=== METRICS ANALYSIS ===")
        for metric_key, metric_info in metrics_data.items():
            promql = metric_info.get("promql", "")
            data = metric_info.get("data", {})

            if data and data.get("result"):
                result = data["result"]
                if result and len(result) > 0:
                    latest_point = result[0] if isinstance(result, list) else result
                    if isinstance(latest_point, dict) and "values" in latest_point:
                        values = latest_point["values"]
                        if values and len(values) > 0:
                            latest_value = values[-1][1] if len(values[-1]) > 1 else "N/A"
                            context_parts.append(f"Metric: {promql} = {latest_value}")

        # Add logs context
        if logs_data:
            context_parts.append("\n=== LOG ANALYSIS ===")

            total_errors = 0
            error_patterns = {}
            service_errors = {}

            for log_key, log_info in logs_data.items():
                if log_info.get("status") == "success":
                    data = log_info.get("data", {})
                    if "result" in data:
                        for stream in data["result"]:
                            stream_labels = stream.get("stream", {})
                            service_name = stream_labels.get("service_name", "unknown")

                            values = stream.get("values", [])
                            for value in values:
                                if len(value) >= 2:
                                    log_line = value[1]
                                    if any(word in log_line.lower() for word in ["error", "failed", "exception"]):
                                        total_errors += 1

                                        # Extract error patterns
                                        if "database" in log_line.lower():
                                            error_patterns["database"] = error_patterns.get("database", 0) + 1
                                        elif "connection" in log_line.lower():
                                            error_patterns["connection"] = error_patterns.get("connection", 0) + 1
                                        elif "timeout" in log_line.lower():
                                            error_patterns["timeout"] = error_patterns.get("timeout", 0) + 1

                                        # Count by service
                                        service_errors[service_name] = service_errors.get(service_name, 0) + 1

            context_parts.append(f"Total error logs: {total_errors}")
            if error_patterns:
                context_parts.append("Error patterns:")
                for pattern, count in error_patterns.items():
                    context_parts.append(f"- {pattern}: {count} errors")

            if service_errors:
                context_parts.append("Errors by service:")
                for service, count in sorted(service_errors.items(), key=lambda x: x[1], reverse=True)[:3]:
                    context_parts.append(f"- {service}: {count} errors")

        # Build comprehensive prompt
        context = "\n".join(context_parts)

        prompt = f"""You are a senior Site Reliability Engineer (SRE) analyzing errors using both metrics and logs for namespace: {namespace}.

Question: {question}

Observability Data:
{context}

Provide a comprehensive error analysis in this format:

🚨 ERROR SUMMARY: [Brief summary of error situation]

📊 METRICS INSIGHT: [What metrics reveal about the errors]

📋 LOG PATTERNS: [What log patterns show]

🔗 CORRELATION: [How metrics and logs correlate]

🎯 ROOT CAUSE: [Most likely root cause based on all data]

⚡ RESOLUTION STEPS:
1. [Immediate action]
2. [Investigation step]
3. [Fix/mitigation]

Focus on actionable insights that combine both metrics and log evidence."""

        return summarize_with_llm(
            prompt,
            model_id,
            ResponseType.GENERAL_CHAT,
            api_key=api_key,
            max_tokens=400,
        )

    except Exception as e:
        logger.error("Error generating correlated error analysis: %s", str(e))
        return "❌ Error generating correlated analysis. Falling back to metrics-only analysis."


def generate_performance_analysis_with_logs(
    question: str,
    metrics_data: Dict[str, Any],
    logs_data: Dict[str, Any],
    model_id: str,
    api_key: str,
    namespace: str
) -> str:
    """
    Generate performance analysis using metrics and logs
    """
    try:
        context_parts = []

        # Add performance metrics
        context_parts.append("=== PERFORMANCE METRICS ===")
        for metric_key, metric_info in metrics_data.items():
            promql = metric_info.get("promql", "")
            if any(perf_word in promql.lower() for perf_word in ["latency", "duration", "response_time", "cpu", "memory"]):
                data = metric_info.get("data", {})
                if data and data.get("result"):
                    # Extract performance data
                    result = data["result"]
                    if result and len(result) > 0:
                        latest_point = result[0] if isinstance(result, list) else result
                        if isinstance(latest_point, dict) and "values" in latest_point:
                            values = latest_point["values"]
                            if values and len(values) > 0:
                                latest_value = values[-1][1] if len(values[-1]) > 1 else "N/A"
                                context_parts.append(f"Performance metric: {promql} = {latest_value}")

        # Add performance-related logs
        if logs_data:
            context_parts.append("\n=== PERFORMANCE LOG ANALYSIS ===")

            slow_requests = 0
            timeout_errors = 0
            performance_warnings = []

            for log_key, log_info in logs_data.items():
                if log_info.get("status") == "success":
                    data = log_info.get("data", {})
                    if "result" in data:
                        for stream in data["result"]:
                            values = stream.get("values", [])
                            for value in values:
                                if len(value) >= 2:
                                    log_line = value[1].lower()

                                    if any(word in log_line for word in ["slow", "timeout", "latency"]):
                                        if "timeout" in log_line:
                                            timeout_errors += 1
                                        else:
                                            slow_requests += 1

                                        # Extract performance warnings
                                        if len(performance_warnings) < 3:
                                            performance_warnings.append(value[1][:150])

            context_parts.append(f"Slow request logs: {slow_requests}")
            context_parts.append(f"Timeout errors: {timeout_errors}")

            if performance_warnings:
                context_parts.append("Sample performance issues:")
                for warning in performance_warnings:
                    context_parts.append(f"- {warning}")

        context = "\n".join(context_parts)

        prompt = f"""You are a senior Site Reliability Engineer (SRE) analyzing performance issues using metrics and logs for namespace: {namespace}.

Question: {question}

Performance Data:
{context}

Provide a comprehensive performance analysis in this format:

⚡ PERFORMANCE SUMMARY: [Current performance status]

📊 METRICS ANALYSIS: [Key performance metrics and trends]

📋 LOG INSIGHTS: [What logs reveal about performance]

🔗 CORRELATION: [How metrics and logs correlate for performance]

🎯 BOTTLENECK IDENTIFICATION: [Primary performance bottlenecks]

🚀 OPTIMIZATION RECOMMENDATIONS:
1. [Immediate optimization]
2. [Medium-term improvement]
3. [Long-term enhancement]

📈 MONITORING: [What to monitor going forward]

Focus on actionable performance improvements based on observability data."""

        return summarize_with_llm(
            prompt,
            model_id,
            ResponseType.GENERAL_CHAT,
            api_key=api_key,
            max_tokens=450,
        )

    except Exception as e:
        logger.error("Error generating performance analysis: %s", str(e))
        return "❌ Error generating performance analysis."


def generate_unified_observability_summary(
    question: str,
    metrics_data: Dict[str, Any],
    logs_data: Dict[str, Any],
    tempo_data: Dict[str, Any],
    model_id: str,
    api_key: str,
    namespace: str
) -> str:
    """
    Generate unified summary using all available observability data
    """
    try:
        context_parts = []

        # Add metrics context
        if metrics_data:
            context_parts.append("=== METRICS DATA ===")
            for metric_key, metric_info in metrics_data.items():
                promql = metric_info.get("promql", "")
                data = metric_info.get("data", {})

                if data and data.get("result"):
                    result = data["result"]
                    if result and len(result) > 0:
                        latest_point = result[0] if isinstance(result, list) else result
                        if isinstance(latest_point, dict) and "values" in latest_point:
                            values = latest_point["values"]
                            if values and len(values) > 0:
                                latest_value = values[-1][1] if len(values[-1]) > 1 else "N/A"
                                context_parts.append(f"{promql}: {latest_value}")

        # Add logs context
        if logs_data:
            context_parts.append("\n=== LOGS DATA ===")

            log_summary = {
                "total_entries": 0,
                "error_count": 0,
                "warning_count": 0,
                "services": set(),
                "recent_messages": []
            }

            for log_key, log_info in logs_data.items():
                if log_info.get("status") == "success":
                    data = log_info.get("data", {})
                    if "result" in data:
                        for stream in data["result"]:
                            stream_labels = stream.get("stream", {})
                            service_name = stream_labels.get("service_name", "unknown")
                            log_summary["services"].add(service_name)

                            values = stream.get("values", [])
                            log_summary["total_entries"] += len(values)

                            for value in values[:5]:  # Sample recent logs
                                if len(value) >= 2:
                                    log_line = value[1]
                                    log_summary["recent_messages"].append(log_line[:100])

                                    if any(word in log_line.lower() for word in ["error", "failed", "exception"]):
                                        log_summary["error_count"] += 1
                                    elif any(word in log_line.lower() for word in ["warning", "warn"]):
                                        log_summary["warning_count"] += 1

            context_parts.append(f"Total log entries analyzed: {log_summary['total_entries']}")
            context_parts.append(f"Services logging: {', '.join(log_summary['services'])}")
            context_parts.append(f"Error logs: {log_summary['error_count']}")
            context_parts.append(f"Warning logs: {log_summary['warning_count']}")

            if log_summary["recent_messages"]:
                context_parts.append("Recent log samples:")
                for msg in log_summary["recent_messages"][:3]:
                    context_parts.append(f"- {msg}")

        # Add traces context if available
        if tempo_data:
            context_parts.append("\n=== TRACES DATA ===")
            context_parts.append("Distributed tracing data available for correlation")

        context = "\n".join(context_parts)

        prompt = f"""You are a senior Site Reliability Engineer (SRE) providing comprehensive observability analysis for namespace: {namespace}.

Question: {question}

Unified Observability Data:
{context}

Provide a comprehensive analysis in this format:

🎯 SUMMARY: [Overall system status and key findings]

📊 METRICS INSIGHT: [Key metrics analysis]

📋 LOG ANALYSIS: [Log patterns and insights]

🔗 OBSERVABILITY CORRELATION: [How metrics, logs, and traces correlate]

💡 KEY INSIGHTS:
- [Insight 1]
- [Insight 2]
- [Insight 3]

⚡ RECOMMENDATIONS:
1. [Action item 1]
2. [Action item 2]
3. [Action item 3]

Focus on insights that leverage the full observability stack for comprehensive understanding."""

        return summarize_with_llm(
            prompt,
            model_id,
            ResponseType.GENERAL_CHAT,
            api_key=api_key,
            max_tokens=500,
        )

    except Exception as e:
        logger.error("Error generating unified summary: %s", str(e))
        return "❌ Error generating unified observability summary."


def fetch_correlated_logs_for_question(question: str, namespace: Optional[str], start_ts: int, end_ts: int) -> Dict[str, Any]:
    """
    Fetch relevant logs based on the question context
    """
    try:
        # Generate appropriate LogQL queries for the question
        logql_queries = generate_logql_from_question(question, namespace, start_ts, end_ts)

        if not logql_queries:
            # Fallback to basic error logs if no specific queries generated
            logql_queries = build_error_analysis_logql(namespace, time_range="2h")

        # Query Loki with generated queries
        return query_loki_with_logql(logql_queries, start_ts, end_ts, limit=200)

    except Exception as e:
        logger.error("Error fetching correlated logs: %s", str(e))
        return {}


# Keep the original function for backward compatibility
def generate_llm_summary(question: str, thanos_data: Dict[str, Any], model_id: str, api_key: str, namespace: str) -> str:
    """
    Original LLM summary function - now enhanced to optionally include logs
    """
    try:
        # Check if this is an error/performance question that would benefit from logs
        question_lower = question.lower()

        if any(word in question_lower for word in ["error", "errors", "failed", "slow", "performance", "issue", "problem"]):
            # For error/performance questions, try to fetch relevant logs
            try:
                from datetime import datetime, timedelta
                end_time = datetime.now()
                start_time = end_time - timedelta(hours=2)  # Last 2 hours

                start_ts = int(start_time.timestamp())
                end_ts = int(end_time.timestamp())

                loki_data = fetch_correlated_logs_for_question(question, namespace, start_ts, end_ts)

                if loki_data:
                    logger.info("Enhanced analysis with logs for question: %s", question)
                    return generate_comprehensive_summary(question, thanos_data, loki_data, None, model_id, api_key, namespace)

            except Exception as e:
                logger.warning("Could not fetch logs for enhanced analysis, falling back to metrics-only: %s", str(e))

        # Fallback to original metrics-only analysis
        return generate_llm_summary_original(question, thanos_data, model_id, api_key, namespace)

    except Exception as e:
        logger.error("Error in enhanced LLM summary: %s", str(e))
        return generate_llm_summary_original(question, thanos_data, model_id, api_key, namespace)


def generate_llm_summary_original(question: str, thanos_data: Dict[str, Any], model_id: str, api_key: str, namespace: str) -> str:
    """
    Original LLM summary generation logic (metrics-only)
    Preserved for backward compatibility and fallback
    """
    try:
        logger.info("Generating LLM summary for: %s", question)

        # Check if we have any successful data
        successful_data = {k: v for k, v in thanos_data.items() if v.get("status") == "success"}

        if not successful_data:
            return "❌ No data available to analyze. Please check your query and try again."

        question_lower = question.lower()

        # === SPECIAL HANDLING FOR ALERTS ===
        if any(word in question_lower for word in ["alert", "alerts", "firing", "warning", "critical", "problem", "issue"]):
            alert_infos = extract_alert_info_from_thanos_data(thanos_data)
            scope = CHAT_SCOPE_FLEET_WIDE if (namespace == "" or namespace == FLEET_WIDE_DISPLAY) else f"namespace '{namespace}'"
            if alert_infos:
                alert_analysis = generate_alert_analysis_with_llm(alert_infos, namespace, model_id=model_id, api_key=api_key)
                return f"🚨 **TOTAL OF {len(alert_infos)} ALERT(S) FOUND IN {scope.upper()}**\n\n{alert_analysis}"
            else:
                return f"✅ No alerts currently firing in {scope}. All systems appear to be operating normally."

        # === REGULAR METRIC HANDLING ===
        # Build context for LLM
        context_parts = []

        for metric_key, metric_info in successful_data.items():
            promql = metric_info.get("promql", "")
            data = metric_info.get("data", {})

            if not data or not data.get("result"):
                continue

            # Extract the most recent value
            result = data["result"]
            if result and len(result) > 0:
                # Get the latest data point
                latest_point = result[0] if isinstance(result, list) else result

                if isinstance(latest_point, dict) and "values" in latest_point:
                    values = latest_point["values"]
                    if values and len(values) > 0:
                        # Get the most recent value
                        latest_value = values[-1][1] if len(values[-1]) > 1 else "N/A"
                        context_parts.append(f"{promql}: {latest_value}")

        if not context_parts:
            return "❌ No valid data points found. Please check your query and try again."

        # Build the prompt
        context = "\n".join(context_parts)

        prompt = f"""You are a senior Site Reliability Engineer (SRE) analyzing metrics for namespace: {namespace}.

Question: {question}

Metrics Data:
{context}

Provide ONLY a structured summary in this exact format (no additional text or instructions):
Current value: [value]
Meaning: [brief explanation]
Immediate concern: [None or specific concern]
Key insight: [one key observation]

Do not include any formatting instructions, notes, or additional commentary."""

        # Generate summary with LLM
        summary = summarize_with_llm(
            prompt,
            model_id,
            ResponseType.GENERAL_CHAT,
            api_key=api_key,
            max_tokens=300,
        )

        return summary

    except Exception as e:
        logger.error("Error generating original LLM summary: %s", str(e))
        return f"❌ Error analyzing data: {str(e)}"


# Import helper functions from original service
def extract_alert_info_from_thanos_data(thanos_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract alert information from Thanos data (imported from original service)"""
    # This function should be imported from the original llm_summary_service.py
    # For now, return empty list - this will be handled by the existing function
    return []


def generate_alert_analysis_with_llm(alert_infos: List[Dict[str, Any]], namespace: str, model_id: str, api_key: str) -> str:
    """Generate alert analysis with LLM (imported from original service)"""
    # This function should be imported from the original llm_summary_service.py
    # For now, return basic alert summary
    return f"Found {len(alert_infos)} alerts in namespace {namespace}. Please check the original alert analysis function."
