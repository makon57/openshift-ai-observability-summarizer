"""Loki query tools for interacting with Loki log data."""

import httpx
import re
from typing import Dict, Any, List
from datetime import datetime, timedelta

from common.pylogger import get_python_logger

from .models import LogQueryResponse, LogDetailsResponse
from .error_handling import LokiErrorClassifier

logger = get_python_logger()


class LokiQueryTool:
    """Tool for querying Loki logs with async support."""

    # Configuration constants
    DEFAULT_QUERY_LIMIT = 1000  # Default limit for log queries
    DEFAULT_CHAT_QUERY_LIMIT = 500  # Default limit for chat tool queries
    REQUEST_TIMEOUT_SECONDS = 30.0  # HTTP request timeout

    # Default configuration values
    DEFAULT_LOKI_URL = "https://logging-loki-gateway-http.observability-hub.svc.cluster.local:8080"
    DEFAULT_NAMESPACE = "observability-hub"

    # Kubernetes service account token path
    K8S_SERVICE_ACCOUNT_TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    # For Loki tenant access, we need the collector token from openshift-logging
    COLLECTOR_TOKEN_PATH = "/var/run/secrets/loki/collector-token"
    DEV_FALLBACK_TOKEN = "dev-token"

    def __init__(self):
        # Loki configuration based on deploy/helm/observability/loki/values.yaml
        # Use environment variable for local development or OpenShift deployment
        import os
        self.loki_url = os.getenv("LOKI_URL", self.DEFAULT_LOKI_URL)
        self.namespace = self.DEFAULT_NAMESPACE

    def _get_service_account_token(self) -> str:
        """Get the service account token for Loki tenant authentication."""
        import os

        # First try environment variable (for local development)
        loki_token = os.getenv("LOKI_TOKEN")
        if loki_token:
            return loki_token

        # Try collector token path (for proper tenant access)
        try:
            with open(self.COLLECTOR_TOKEN_PATH, 'r') as f:
                return f.read().strip()
        except FileNotFoundError:
            pass

        # Fallback to default service account token
        try:
            with open(self.K8S_SERVICE_ACCOUNT_TOKEN_PATH, 'r') as f:
                return f.read().strip()
        except FileNotFoundError:
            return self.DEV_FALLBACK_TOKEN

    def _get_request_headers(self) -> Dict[str, str]:
        """
        Get HTTP headers for Loki API requests.

        Returns:
            Dict[str, str]: Headers including optional auth token
        """
        headers = {
            "Content-Type": "application/json"
        }

        # Add service account token if running in cluster
        try:
            token = self._get_service_account_token()
            if token and token != self.DEV_FALLBACK_TOKEN:
                headers["Authorization"] = f"Bearer {token}"
        except Exception as e:
            logger.debug(f"No service account token available: {e}")

        return headers

    def _convert_timestamps_to_nanoseconds(self, start_time: str, end_time: str) -> tuple[int, int]:
        """Convert ISO timestamps to nanoseconds for Loki API."""
        start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))

        start_ns = int(start_dt.timestamp() * 1_000_000_000)
        end_ns = int(end_dt.timestamp() * 1_000_000_000)

        return start_ns, end_ns

    def _parse_log_entries(self, result_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse Loki query results into structured log entries."""
        log_entries = []

        if "result" in result_data:
            for stream in result_data["result"]:
                stream_labels = stream.get("stream", {})
                values = stream.get("values", [])

                for value in values:
                    if len(value) >= 2:
                        timestamp_ns = int(value[0])
                        log_line = value[1]

                        # Convert nanosecond timestamp to ISO format
                        timestamp_dt = datetime.fromtimestamp(timestamp_ns / 1_000_000_000)

                        log_entry = {
                            "timestamp": timestamp_dt.isoformat() + "Z",
                            "timestamp_ns": timestamp_ns,
                            "log": log_line,
                            "labels": stream_labels
                        }

                        # Try to parse structured logs (JSON)
                        try:
                            import json
                            if log_line.strip().startswith('{') and log_line.strip().endswith('}'):
                                parsed_log = json.loads(log_line)
                                log_entry["parsed"] = parsed_log
                                # Extract common fields
                                log_entry["level"] = parsed_log.get("level", "unknown")
                                log_entry["message"] = parsed_log.get("message", parsed_log.get("msg", log_line))
                        except (json.JSONDecodeError, ValueError):
                            # Not JSON, treat as plain text
                            log_entry["message"] = log_line

                            # Try to extract log level from plain text
                            level_match = re.search(r'\b(DEBUG|INFO|WARN|WARNING|ERROR|FATAL|CRITICAL)\b', log_line, re.IGNORECASE)
                            if level_match:
                                log_entry["level"] = level_match.group(1).lower()
                            else:
                                log_entry["level"] = "unknown"

                        log_entries.append(log_entry)

        return log_entries

    async def query_logs(
        self,
        logql: str,
        start_time: str,
        end_time: str,
        limit: int = DEFAULT_QUERY_LIMIT
    ) -> Dict[str, Any]:
        """
        Query logs from Loki using LogQL syntax.

        Args:
            logql (str): LogQL query string. Supports:
                - Label filtering: '{namespace="default", app="myapp"}'
                - Log line filtering: '{app="myapp"} |= "error"'
                - JSON parsing: '{app="myapp"} | json | level="error"'
                - Regex matching: '{app="myapp"} |~ "(?i)error.*database"'
                - Metrics queries: 'rate({app="myapp"}[5m])'
            start_time (str): Start time in ISO 8601 format with timezone.
                Examples: "2024-01-01T10:00:00Z", "2024-01-01T10:00:00+00:00"
            end_time (str): End time in ISO 8601 format with timezone.
                Examples: "2024-01-01T11:00:00Z", "2024-01-01T11:00:00+00:00"
            limit (int, optional): Maximum number of log entries to return. Defaults to DEFAULT_QUERY_LIMIT (1000).

        Returns:
            Dict[str, Any]: Query result containing:
                - success (bool): Whether the query was successful
                - logs (List[Dict]): List of log entries if successful
                - query (str): The original LogQL query string
                - time_range (str): Formatted time range
                - error (str): Error message if unsuccessful
        """
        try:
            start_ns, end_ns = self._convert_timestamps_to_nanoseconds(start_time, end_time)
            headers = self._get_request_headers()

            # Use Loki query_range API with tenant-specific path
            # Default to application tenant for MCP queries
            tenant = "application"  # Can be made configurable later
            query_url = f"{self.loki_url}/api/logs/v1/{tenant}/loki/api/v1/query_range"

            # Build query parameters
            params = {
                "query": logql,
                "start": start_ns,
                "end": end_ns,
                "limit": limit,
                "direction": "backward"  # Most recent logs first
            }

            async with httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT_SECONDS, verify=False) as client:
                logger.info(f"Querying Loki API: {query_url}")
                logger.info(f"LogQL query: {logql}")
                logger.info(f"Query parameters: start={start_time}, end={end_time}, limit={limit}")

                response = await client.get(query_url, params=params, headers=headers)

                if response.status_code == 200:
                    loki_data = response.json()
                    logger.info(f"Loki API response status: {response.status_code}")

                    if loki_data.get("status") == "success":
                        result_data = loki_data.get("data", {})

                        # Parse log entries
                        log_entries = self._parse_log_entries(result_data)

                        logger.info(f"Query results: {len(log_entries)} log entries")
                        if log_entries:
                            logger.info(f"Sample log levels: {[entry.get('level', 'unknown') for entry in log_entries[:3]]}")

                        return LogQueryResponse(
                            success=True,
                            query=logql,
                            logs=log_entries,
                            total=len(log_entries),
                            time_range=f"{start_time} to {end_time}",
                            api_endpoint=query_url,
                            result_type=result_data.get("resultType", "streams")
                        ).to_dict()
                    else:
                        error_msg = loki_data.get("error", "Unknown Loki error")
                        logger.error(f"Loki query failed: {error_msg}")
                        return LogQueryResponse(
                            success=False,
                            query=logql,
                            error=f"Loki query failed: {error_msg}",
                            api_endpoint=query_url
                        ).to_dict()
                else:
                    logger.error(f"Loki API query failed: HTTP {response.status_code}")
                    logger.error(f"Response text: {response.text}")
                    return LogQueryResponse(
                        success=False,
                        query=logql,
                        error=f"Loki API query failed: HTTP {response.status_code} - {response.text}",
                        api_endpoint=query_url
                    ).to_dict()

        except Exception as e:
            logger.error(f"Loki query error: {e}")
            error_msg = str(e)

            # Use robust error classification
            error_type = LokiErrorClassifier.classify_error(error_msg)
            user_friendly_msg = LokiErrorClassifier.get_user_friendly_message(error_type, self.loki_url)

            return LogQueryResponse(
                success=False,
                query=logql,
                error=user_friendly_msg,
                loki_url=self.loki_url,
                error_type=error_type.value
            ).to_dict()

    async def get_log_labels(self, start_time: str = None, end_time: str = None) -> Dict[str, Any]:
        """Get available log labels from Loki."""
        try:
            # Use tenant-specific labels endpoint
            tenant = "application"  # Can be made configurable later
            labels_url = f"{self.loki_url}/api/logs/v1/{tenant}/loki/api/v1/labels"
            headers = self._get_request_headers()

            params = {}
            if start_time and end_time:
                start_ns, end_ns = self._convert_timestamps_to_nanoseconds(start_time, end_time)
                params["start"] = start_ns
                params["end"] = end_ns

            async with httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT_SECONDS, verify=False) as client:
                logger.info(f"Getting available labels from: {labels_url}")
                response = await client.get(labels_url, params=params, headers=headers)

                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "success":
                        labels = data.get("data", [])
                        logger.info(f"Found {len(labels)} available labels: {labels}")
                        return LogDetailsResponse(
                            success=True,
                            data=labels
                        ).to_dict()
                    else:
                        error_msg = data.get("error", "Unknown error")
                        logger.error(f"Failed to get labels: {error_msg}")
                        return LogDetailsResponse(
                            success=False,
                            error=error_msg
                        ).to_dict()
                else:
                    logger.error(f"Failed to get labels: HTTP {response.status_code} - {response.text}")
                    return LogDetailsResponse(
                        success=False,
                        error=f"HTTP {response.status_code}: {response.text}"
                    ).to_dict()

        except Exception as e:
            logger.error(f"Error getting available labels: {e}")
            return LogDetailsResponse(
                success=False,
                error=str(e)
            ).to_dict()

    async def get_label_values(self, label_name: str, start_time: str = None, end_time: str = None) -> Dict[str, Any]:
        """Get values for a specific label from Loki."""
        try:
            # Use tenant-specific label values endpoint
            tenant = "application"  # Can be made configurable later
            values_url = f"{self.loki_url}/api/logs/v1/{tenant}/loki/api/v1/label/{label_name}/values"
            headers = self._get_request_headers()

            params = {}
            if start_time and end_time:
                start_ns, end_ns = self._convert_timestamps_to_nanoseconds(start_time, end_time)
                params["start"] = start_ns
                params["end"] = end_ns

            async with httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT_SECONDS, verify=False) as client:
                logger.info(f"Getting values for label '{label_name}' from: {values_url}")
                response = await client.get(values_url, params=params, headers=headers)

                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "success":
                        values = data.get("data", [])
                        logger.info(f"Found {len(values)} values for label '{label_name}': {values[:10]}")  # Log first 10
                        return LogDetailsResponse(
                            success=True,
                            data=values
                        ).to_dict()
                    else:
                        error_msg = data.get("error", "Unknown error")
                        logger.error(f"Failed to get label values: {error_msg}")
                        return LogDetailsResponse(
                            success=False,
                            error=error_msg
                        ).to_dict()
                else:
                    logger.error(f"Failed to get label values: HTTP {response.status_code} - {response.text}")
                    return LogDetailsResponse(
                        success=False,
                        error=f"HTTP {response.status_code}: {response.text}"
                    ).to_dict()

        except Exception as e:
            logger.error(f"Error getting label values: {e}")
            return LogDetailsResponse(
                success=False,
                error=str(e)
            ).to_dict()

    async def query_log_volume(
        self,
        namespace: str = None,
        service: str = None,
        start_time: str = None,
        end_time: str = None,
        interval: str = "5m"
    ) -> Dict[str, Any]:
        """Query log volume metrics using LogQL aggregation."""
        try:
            # Build LogQL query for log volume
            if namespace and service:
                base_query = f'{{namespace="{namespace}", service_name="{service}"}}'
            elif namespace:
                base_query = f'{{namespace="{namespace}"}}'
            elif service:
                base_query = f'{{service_name="{service}"}}'
            else:
                base_query = '{job="application"}'

            # Create volume query
            volume_query = f'sum by (namespace, service_name) (count_over_time({base_query}[{interval}]))'

            logger.info(f"Querying log volume with: {volume_query}")

            return await self.query_logs(volume_query, start_time, end_time, limit=100)

        except Exception as e:
            logger.error(f"Log volume query error: {e}")
            return LogQueryResponse(
                success=False,
                query=volume_query if 'volume_query' in locals() else "unknown",
                error=str(e)
            ).to_dict()
