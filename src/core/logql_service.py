#!/usr/bin/env python3
"""
Core LogQL Generation Service
Generates LogQL queries from natural language questions, similar to promql_service.py
"""

import os
import re
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
import logging
from common.pylogger import get_python_logger

# Initialize structured logger once - other modules should use logging.getLogger(__name__)
get_python_logger()

logger = logging.getLogger(__name__)


def generate_logql_from_question(question: str, namespace: Optional[str], start_ts: int, end_ts: int, is_fleet_wide: bool = False) -> List[str]:
    """
    Generate LogQL queries from natural language questions
    Similar to generate_promql_from_question but for logs
    """
    question_lower = question.lower()
    queries = []
    logger.info("Analyzing log question: %s", question)

    # Calculate time range duration for dynamic intervals
    duration_seconds = end_ts - start_ts
    duration_hours = duration_seconds / 3600

    # Smart interval selection based on time range
    if duration_hours <= 1:
        rate_interval = "5m"  # For 1 hour, use 5m intervals
    elif duration_hours <= 6:
        rate_interval = "15m"  # For up to 6 hours, use 15m intervals
    elif duration_hours <= 24:
        rate_interval = "1h"  # For up to a day, use 1h intervals
    else:
        rate_interval = "6h"   # For longer periods, use 6h intervals

    logger.info("Time range: %.1fh, interval=%s", duration_hours, rate_interval)
    logger.info("Scope: %s", "Fleet-wide" if is_fleet_wide else f"Namespace: {namespace}")

    # Base selector for namespace filtering
    if is_fleet_wide or not namespace:
        base_selector = '{job="application"}'
        namespace_filter = ""
    else:
        base_selector = f'{{namespace="{namespace}"}}'
        namespace_filter = f', namespace="{namespace}"'

    # ERROR AND ALERT PATTERNS
    if any(word in question_lower for word in ["error", "errors", "failed", "failure", "exception", "panic", "fatal", "critical"]):
        logger.info("Detected error-related query")

        # Error log patterns
        error_queries = [
            f'{base_selector} |~ "(?i)(error|failed|failure|exception|panic|fatal|critical)"',
            f'{base_selector} | json | level="error"',
            f'{base_selector} | logfmt | level="error"'
        ]

        # Add specific error patterns
        if "database" in question_lower or "db" in question_lower:
            error_queries.append(f'{base_selector} |~ "(?i)(database|db|sql).*error"')
        if "connection" in question_lower:
            error_queries.append(f'{base_selector} |~ "(?i)connection.*(error|failed|refused|timeout)"')
        if "timeout" in question_lower:
            error_queries.append(f'{base_selector} |~ "(?i)timeout"')
        if "authentication" in question_lower or "auth" in question_lower:
            error_queries.append(f'{base_selector} |~ "(?i)(auth|authentication).*(error|failed|denied)"')

        queries.extend(error_queries)

    # WARNING PATTERNS
    elif any(word in question_lower for word in ["warning", "warn", "warnings"]):
        logger.info("Detected warning-related query")
        queries.extend([
            f'{base_selector} | json | level="warning"',
            f'{base_selector} | logfmt | level="warn"',
            f'{base_selector} |~ "(?i)(warning|warn)"'
        ])

    # PERFORMANCE AND SLOW QUERIES
    elif any(word in question_lower for word in ["slow", "performance", "latency", "response time", "timeout"]):
        logger.info("Detected performance-related query")
        queries.extend([
            f'{base_selector} |~ "(?i)(slow|latency|timeout|took.*ms|took.*seconds)"',
            f'{base_selector} | json | duration > 1000',  # Assuming duration in ms
            f'{base_selector} |~ "response_time|response.*ms"'
        ])

    # HTTP/API PATTERNS
    elif any(word in question_lower for word in ["http", "api", "request", "response", "status", "endpoint"]):
        logger.info("Detected HTTP/API-related query")

        # HTTP status code patterns
        if "500" in question_lower or "server error" in question_lower:
            queries.append(f'{base_selector} |~ "(?i)(status.*5[0-9][0-9]|500|502|503|504)"')
        elif "400" in question_lower or "client error" in question_lower:
            queries.append(f'{base_selector} |~ "(?i)(status.*4[0-9][0-9]|400|401|403|404)"')
        else:
            queries.extend([
                f'{base_selector} | json | status_code >= 400',
                f'{base_selector} |~ "(?i)(GET|POST|PUT|DELETE|PATCH).*HTTP"',
                f'{base_selector} |~ "status.*[4-5][0-9][0-9]"'
            ])

    # AUTHENTICATION AND SECURITY
    elif any(word in question_lower for word in ["auth", "authentication", "login", "logout", "security", "unauthorized", "forbidden"]):
        logger.info("Detected authentication/security-related query")
        queries.extend([
            f'{base_selector} |~ "(?i)(auth|authentication|login|logout|security)"',
            f'{base_selector} |~ "(?i)(unauthorized|forbidden|denied|invalid.*token)"',
            f'{base_selector} | json | user != ""'  # Logs with user information
        ])

    # DATABASE PATTERNS
    elif any(word in question_lower for word in ["database", "db", "sql", "query", "connection"]):
        logger.info("Detected database-related query")
        queries.extend([
            f'{base_selector} |~ "(?i)(database|db|sql|mysql|postgres|mongodb)"',
            f'{base_selector} |~ "(?i)(connection.*pool|query.*time|transaction)"'
        ])

    # APPLICATION STARTUP/SHUTDOWN
    elif any(word in question_lower for word in ["startup", "start", "boot", "shutdown", "restart", "deploy"]):
        logger.info("Detected startup/deployment-related query")
        queries.extend([
            f'{base_selector} |~ "(?i)(starting|started|startup|boot|ready|listening)"',
            f'{base_selector} |~ "(?i)(shutdown|stopping|stopped|graceful)"',
            f'{base_selector} |~ "(?i)(deploy|deployment|version|build)"'
        ])

    # SPECIFIC SERVICE PATTERNS
    elif any(word in question_lower for word in ["service", "pod", "container"]):
        logger.info("Detected service/container-related query")

        # Extract service name if mentioned
        service_name = None
        service_patterns = [
            r'service\s+(\w+)',
            r'(\w+)\s+service',
            r'pod\s+(\w+)',
            r'container\s+(\w+)'
        ]

        for pattern in service_patterns:
            match = re.search(pattern, question_lower)
            if match:
                service_name = match.group(1)
                break

        if service_name:
            queries.extend([
                f'{{service_name="{service_name}"{namespace_filter}}}',
                f'{{app="{service_name}"{namespace_filter}}}',
                f'{{container="{service_name}"{namespace_filter}}}'
            ])
        else:
            queries.append(base_selector)

    # LOG VOLUME AND PATTERNS
    elif any(word in question_lower for word in ["volume", "count", "frequency", "rate", "how many", "total"]):
        logger.info("Detected log volume/counting query")
        queries.extend([
            f'sum by (namespace) (count_over_time({base_selector}[{rate_interval}]))',
            f'sum by (level) (count_over_time({base_selector}[{rate_interval}]))',
            f'sum by (service_name) (count_over_time({base_selector}[{rate_interval}]))'
        ])

    # RECENT LOGS (DEFAULT)
    else:
        logger.info("Using default recent logs query")
        queries.extend([
            base_selector,  # All logs for the namespace/scope
            f'{base_selector} | json | level != "debug"',  # Exclude debug logs
            f'{base_selector} | logfmt | level != "debug"'  # Alternative format
        ])

    # Add time-based queries if specific time mentioned
    if "last" in question_lower and any(unit in question_lower for unit in ["minute", "hour", "day"]):
        # Extract time duration
        time_match = re.search(r'last\s+(\d+)\s*(minute|hour|day)', question_lower)
        if time_match:
            amount = int(time_match.group(1))
            unit = time_match.group(2)

            if unit == "minute":
                interval = f"{amount}m"
            elif unit == "hour":
                interval = f"{amount}h"
            else:  # day
                interval = f"{amount * 24}h"

            # Add rate queries for the specific time range
            queries.append(f'rate({base_selector}[{interval}])')

    # Remove duplicates and empty queries
    queries = list(dict.fromkeys([q for q in queries if q.strip()]))

    logger.info("Generated %d LogQL queries", len(queries))
    for i, query in enumerate(queries, 1):
        logger.debug("LogQL Query %d: %s", i, query)

    return queries


def build_error_analysis_logql(namespace: Optional[str] = None, service_name: Optional[str] = None, time_range: str = "1h") -> List[str]:
    """
    Build LogQL queries specifically for error analysis
    """
    queries = []

    # Base selector
    if namespace and service_name:
        base_selector = f'{{namespace="{namespace}", service_name="{service_name}"}}'
    elif namespace:
        base_selector = f'{{namespace="{namespace}"}}'
    elif service_name:
        base_selector = f'{{service_name="{service_name}"}}'
    else:
        base_selector = '{job="application"}'

    # Error detection queries
    queries.extend([
        # Structured logging errors
        f'{base_selector} | json | level="error"',
        f'{base_selector} | logfmt | level="error"',

        # Pattern-based error detection
        f'{base_selector} |~ "(?i)(error|failed|failure|exception|panic|fatal|critical)"',

        # HTTP errors
        f'{base_selector} | json | status_code >= 400',
        f'{base_selector} |~ "status.*[4-5][0-9][0-9]"',

        # Error rate over time
        f'sum by (level) (rate({base_selector} | json | level="error" [{time_range}]))',

        # Error count by service
        f'sum by (service_name) (count_over_time({base_selector} | json | level="error" [{time_range}]))'
    ])

    return queries


def build_performance_analysis_logql(namespace: Optional[str] = None, service_name: Optional[str] = None, time_range: str = "1h") -> List[str]:
    """
    Build LogQL queries specifically for performance analysis
    """
    queries = []

    # Base selector
    if namespace and service_name:
        base_selector = f'{{namespace="{namespace}", service_name="{service_name}"}}'
    elif namespace:
        base_selector = f'{{namespace="{namespace}"}}'
    elif service_name:
        base_selector = f'{{service_name="{service_name}"}}'
    else:
        base_selector = '{job="application"}'

    # Performance-related queries
    queries.extend([
        # Slow requests
        f'{base_selector} |~ "(?i)(slow|latency|timeout|took.*ms|response.*time)"',

        # Duration-based filtering (assuming structured logs with duration field)
        f'{base_selector} | json | duration > 1000',  # > 1 second
        f'{base_selector} | json | response_time > 1000',

        # Request rate
        f'sum by (service_name) (rate({base_selector} | json | method != "" [{time_range}]))',

        # Average response time (if available in structured logs)
        f'avg by (service_name) (rate({base_selector} | json | unwrap duration [{time_range}]))',

        # P95 response time
        f'quantile(0.95, sum by (service_name) (rate({base_selector} | json | unwrap duration [{time_range}])))'
    ])

    return queries


def extract_log_patterns_from_question(question: str) -> Dict[str, Any]:
    """
    Extract specific patterns and filters from user questions
    """
    question_lower = question.lower()

    patterns = {
        "log_level": None,
        "service_name": None,
        "error_types": [],
        "time_range": None,
        "search_terms": []
    }

    # Extract log level
    if "error" in question_lower:
        patterns["log_level"] = "error"
    elif "warning" in question_lower or "warn" in question_lower:
        patterns["log_level"] = "warning"
    elif "info" in question_lower:
        patterns["log_level"] = "info"
    elif "debug" in question_lower:
        patterns["log_level"] = "debug"

    # Extract service name
    service_match = re.search(r'(?:service|app|pod|container)\s+(\w+)', question_lower)
    if service_match:
        patterns["service_name"] = service_match.group(1)

    # Extract error types
    error_types = []
    if "database" in question_lower or "db" in question_lower:
        error_types.append("database")
    if "connection" in question_lower:
        error_types.append("connection")
    if "timeout" in question_lower:
        error_types.append("timeout")
    if "authentication" in question_lower or "auth" in question_lower:
        error_types.append("authentication")
    patterns["error_types"] = error_types

    # Extract time range
    time_match = re.search(r'last\s+(\d+)\s*(minute|hour|day|week)', question_lower)
    if time_match:
        amount = int(time_match.group(1))
        unit = time_match.group(2)
        patterns["time_range"] = f"{amount}{unit[0]}"  # e.g., "1h", "30m"

    # Extract search terms (quoted strings or specific keywords)
    search_terms = re.findall(r'"([^"]*)"', question)
    if not search_terms:
        # Look for specific technical terms
        technical_terms = ["http", "api", "sql", "json", "xml", "tcp", "ssl", "tls"]
        search_terms = [term for term in technical_terms if term in question_lower]
    patterns["search_terms"] = search_terms

    return patterns
