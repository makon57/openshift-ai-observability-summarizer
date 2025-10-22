"""Error handling and classification for Loki operations."""

from enum import Enum
from typing import Dict, Any


class LokiErrorType(Enum):
    """Classification of Loki-related errors."""
    CONNECTION_REFUSED = "connection_refused"
    DNS_RESOLUTION_FAILED = "dns_resolution_failed"
    HTTP_ERROR = "http_error"
    TIMEOUT = "timeout"
    AUTHENTICATION_FAILED = "authentication_failed"
    SERVICE_UNAVAILABLE = "service_unavailable"
    QUERY_SYNTAX_ERROR = "query_syntax_error"
    RATE_LIMITED = "rate_limited"
    UNKNOWN = "unknown"


class LokiErrorClassifier:
    """Classifies and provides user-friendly messages for Loki errors."""

    ERROR_PATTERNS = {
        LokiErrorType.CONNECTION_REFUSED: [
            "connection refused",
            "connection reset",
            "no route to host"
        ],
        LokiErrorType.DNS_RESOLUTION_FAILED: [
            "name or service not known",
            "nodename nor servname provided",
            "temporary failure in name resolution",
            "no address associated with hostname"
        ],
        LokiErrorType.HTTP_ERROR: [
            "http 4",
            "http 5",
            "bad request",
            "internal server error"
        ],
        LokiErrorType.TIMEOUT: [
            "timeout",
            "timed out",
            "deadline exceeded"
        ],
        LokiErrorType.AUTHENTICATION_FAILED: [
            "unauthorized",
            "authentication failed",
            "invalid credentials",
            "access denied"
        ],
        LokiErrorType.SERVICE_UNAVAILABLE: [
            "service unavailable",
            "bad gateway",
            "gateway timeout"
        ],
        LokiErrorType.QUERY_SYNTAX_ERROR: [
            "parse error",
            "syntax error",
            "invalid query",
            "bad logql"
        ],
        LokiErrorType.RATE_LIMITED: [
            "rate limit",
            "too many requests",
            "quota exceeded"
        ]
    }

    @classmethod
    def classify_error(cls, error_message: str) -> LokiErrorType:
        """
        Classify an error message into a specific error type.

        Args:
            error_message: The error message to classify

        Returns:
            LokiErrorType: The classified error type
        """
        error_lower = error_message.lower()

        for error_type, patterns in cls.ERROR_PATTERNS.items():
            if any(pattern in error_lower for pattern in patterns):
                return error_type

        return LokiErrorType.UNKNOWN

    @classmethod
    def get_user_friendly_message(cls, error_type: LokiErrorType, loki_url: str) -> str:
        """
        Get a user-friendly error message for the given error type.

        Args:
            error_type: The classified error type
            loki_url: The Loki URL that was being accessed

        Returns:
            str: User-friendly error message with troubleshooting tips
        """
        messages = {
            LokiErrorType.CONNECTION_REFUSED: f"Loki service refused connection at {loki_url}. Check if Loki is running in the observability-hub namespace.",
            LokiErrorType.DNS_RESOLUTION_FAILED: f"Loki service not reachable at {loki_url}. This is expected when running locally. Deploy to OpenShift to access Loki.",
            LokiErrorType.HTTP_ERROR: f"HTTP error accessing Loki at {loki_url}. Check if the service is properly configured.",
            LokiErrorType.TIMEOUT: f"Request to Loki timed out at {loki_url}. The service may be overloaded or unreachable.",
            LokiErrorType.AUTHENTICATION_FAILED: f"Authentication failed when accessing Loki at {loki_url}. Check your credentials.",
            LokiErrorType.SERVICE_UNAVAILABLE: f"Loki service is temporarily unavailable at {loki_url}. Please try again later.",
            LokiErrorType.QUERY_SYNTAX_ERROR: f"LogQL query syntax error. Check your query syntax and try again.",
            LokiErrorType.RATE_LIMITED: f"Rate limit exceeded for Loki at {loki_url}. Please reduce query frequency.",
            LokiErrorType.UNKNOWN: f"Unexpected error accessing Loki at {loki_url}"
        }

        return messages.get(error_type, messages[LokiErrorType.UNKNOWN])


class LogPatternDetector:
    """Detects patterns and issues in log entries."""

    @staticmethod
    def is_error_log(log_entry: Dict[str, Any]) -> bool:
        """Detect if a log entry represents an error."""
        # Check structured log level
        if log_entry.get("level", "").lower() in ["error", "fatal", "critical"]:
            return True

        # Check log message for error patterns
        message = log_entry.get("message", log_entry.get("log", "")).lower()
        error_patterns = [
            "error", "failed", "failure", "exception", "panic",
            "fatal", "critical", "crashed", "abort"
        ]

        return any(pattern in message for pattern in error_patterns)

    @staticmethod
    def is_warning_log(log_entry: Dict[str, Any]) -> bool:
        """Detect if a log entry represents a warning."""
        # Check structured log level
        if log_entry.get("level", "").lower() in ["warning", "warn"]:
            return True

        # Check log message for warning patterns
        message = log_entry.get("message", log_entry.get("log", "")).lower()
        warning_patterns = ["warning", "warn", "deprecated", "slow", "retry"]

        return any(pattern in message for pattern in warning_patterns)

    @staticmethod
    def extract_error_type(log_entry: Dict[str, Any]) -> str:
        """Extract the type of error from a log entry."""
        message = log_entry.get("message", log_entry.get("log", "")).lower()

        error_types = {
            "database": ["database", "db", "sql", "mysql", "postgres", "mongodb"],
            "connection": ["connection", "connect", "socket", "network"],
            "timeout": ["timeout", "timed out", "deadline exceeded"],
            "authentication": ["auth", "authentication", "login", "credentials"],
            "http": ["http", "api", "request", "response", "status"],
            "memory": ["memory", "oom", "out of memory", "heap"],
            "disk": ["disk", "filesystem", "storage", "space"],
            "permission": ["permission", "access", "denied", "forbidden"]
        }

        for error_type, keywords in error_types.items():
            if any(keyword in message for keyword in keywords):
                return error_type

        return "unknown"

    @staticmethod
    def extract_service_info(log_entry: Dict[str, Any]) -> Dict[str, str]:
        """Extract service information from log entry labels."""
        labels = log_entry.get("labels", {})

        return {
            "namespace": labels.get("namespace", "unknown"),
            "service_name": labels.get("service_name", labels.get("app", "unknown")),
            "pod_name": labels.get("pod_name", labels.get("pod", "unknown")),
            "container": labels.get("container", "unknown")
        }
