#!/usr/bin/env python3
"""
Core Loki Query Service
Handles log queries and correlation with metrics/traces
"""

import os
import requests
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import json

# Import configuration
from .config import VERIFY_SSL as verify

# Loki configuration
# For local development, use port-forward: oc port-forward -n openshift-logging svc/logging-loki-gateway-http 3100:8080
# For in-cluster deployment, use the service DNS name
LOKI_URL = os.getenv("LOKI_URL", "https://localhost:3100")
LOKI_TOKEN = os.getenv("LOKI_TOKEN", "")


def query_loki_logs(query: str, start_ts: int, end_ts: int, limit: int = 1000, tenant: str = "application") -> Dict[str, Any]:
    """
    Query Loki for logs within a time range for a specific tenant

    Args:
        query: LogQL query string
        start_ts: Start timestamp (Unix seconds)
        end_ts: End timestamp (Unix seconds)
        limit: Maximum number of log entries to return
        tenant: Loki tenant ("application", "infrastructure", or "audit")
    """
    print(f"🔍 Querying Loki tenant '{tenant}' with: {query}")
    print(f"⏰ Time range: {datetime.fromtimestamp(start_ts)} to {datetime.fromtimestamp(end_ts)}")

    headers = {"Authorization": f"Bearer {LOKI_TOKEN}"} if LOKI_TOKEN else {}

    try:
        # Convert timestamps to nanoseconds (Loki expects nanosecond timestamps)
        start_ns = start_ts * 1000000000
        end_ns = end_ts * 1000000000

        # Build tenant-specific URL
        tenant_url = f"{LOKI_URL}/api/logs/v1/{tenant}/loki/api/v1/query_range"

        # Query Loki
        response = requests.get(
            tenant_url,
            headers=headers,
            params={
                "query": query,
                "start": start_ns,
                "end": end_ns,
                "limit": limit,
                "direction": "backward"  # Most recent logs first
            },
            verify=False if "localhost" in LOKI_URL else verify,
            timeout=30
        )
        response.raise_for_status()

        data = response.json()

        if data.get("status") == "success":
            result_data = data.get("data", {})
            log_count = len(result_data.get("result", []))
            print(f"✅ Loki query successful - {log_count} log streams found")

            return {
                "query": query,
                "data": result_data,
                "status": "success",
                "log_count": log_count
            }
        else:
            print(f"❌ Loki query failed: {data.get('error', 'Unknown error')}")
            return {
                "query": query,
                "data": {},
                "status": "error",
                "error": data.get("error", "Unknown error")
            }

    except requests.exceptions.Timeout:
        print(f"⏰ Loki query timed out")
        return {
            "query": query,
            "data": {},
            "status": "timeout"
        }
    except requests.exceptions.RequestException as e:
        print(f"❌ Loki query failed: {e}")
        return {
            "query": query,
            "data": {},
            "status": "error",
            "error": str(e)
        }
    except Exception as e:
        print(f"❌ Loki query failed: {e}")
        return {
            "query": query,
            "data": {},
            "status": "error",
            "error": str(e)
        }


def get_infrastructure_logs_for_namespace(namespace: str, start_ts: int, end_ts: int, level: str = "error") -> Dict[str, Any]:
    """
    Get infrastructure logs for a specific namespace, filtered by log level
    """
    query = f'{{namespace="{namespace}", level="{level}"}}'
    return query_loki_logs(query, start_ts, end_ts, tenant="infrastructure")


def get_logs_around_alert_time(namespace: str, alert_time: datetime, window_minutes: int = 15, tenant: str = "infrastructure") -> Dict[str, Any]:
    """
    Get logs around the time an alert fired, useful for root cause analysis
    """
    start_time = alert_time - timedelta(minutes=window_minutes)
    end_time = alert_time + timedelta(minutes=window_minutes)

    start_ts = int(start_time.timestamp())
    end_ts = int(end_time.timestamp())

    # Query for error and warning logs around the alert time
    error_query = f'{{namespace="{namespace}", level=~"error|warning"}}'
    return query_loki_logs(error_query, start_ts, end_ts, tenant=tenant)


def get_pod_logs(namespace: str, pod_name: str, start_ts: int, end_ts: int, tenant: str = "application") -> Dict[str, Any]:
    """
    Get logs for a specific pod
    """
    query = f'{{namespace="{namespace}", pod="{pod_name}"}}'
    return query_loki_logs(query, start_ts, end_ts, tenant=tenant)


def search_logs_by_pattern(namespace: str, pattern: str, start_ts: int, end_ts: int, tenant: str = "application") -> Dict[str, Any]:
    """
    Search logs for a specific pattern (e.g., error messages, keywords)
    """
    query = f'{{namespace="{namespace}"}} |~ "{pattern}"'
    return query_loki_logs(query, start_ts, end_ts, tenant=tenant)


def extract_log_insights(log_result: Dict[str, Any]) -> List[str]:
    """
    Extract meaningful insights from Loki log query results
    """
    insights = []

    if log_result.get("status") != "success":
        return ["❌ Log query failed or returned no data"]

    data = log_result.get("data", {})
    results = data.get("result", [])

    if not results:
        return ["ℹ️ No logs found for the specified criteria"]

    total_logs = 0
    error_patterns = {}

    for result in results:
        stream = result.get("stream", {})
        values = result.get("values", [])

        total_logs += len(values)

        # Extract pod/container info
        pod = stream.get("pod", "unknown")
        container = stream.get("container", "unknown")

        # Analyze log entries for patterns
        for timestamp, log_line in values:
            log_lower = log_line.lower()

            # Common error patterns
            if "error" in log_lower or "exception" in log_lower:
                key = f"errors_in_{pod}_{container}"
                error_patterns[key] = error_patterns.get(key, 0) + 1
            elif "failed" in log_lower or "timeout" in log_lower:
                key = f"failures_in_{pod}_{container}"
                error_patterns[key] = error_patterns.get(key, 0) + 1
            elif "warning" in log_lower or "warn" in log_lower:
                key = f"warnings_in_{pod}_{container}"
                error_patterns[key] = error_patterns.get(key, 0) + 1

    insights.append(f"📊 Found {total_logs} log entries across {len(results)} log streams")

    # Report error patterns
    if error_patterns:
        insights.append("🚨 Error patterns detected:")
        for pattern, count in sorted(error_patterns.items(), key=lambda x: x[1], reverse=True)[:5]:
            insights.append(f"   • {pattern}: {count} occurrences")

    return insights


def get_recent_logs_summary(namespace: str, hours: int = 1) -> Dict[str, Any]:
    """
    Get a summary of recent logs for correlation with metrics
    """
    end_time = datetime.now()
    start_time = end_time - timedelta(hours=hours)

    start_ts = int(start_time.timestamp())
    end_ts = int(end_time.timestamp())

    # Get error and warning logs
    result = get_infrastructure_logs_for_namespace(namespace, start_ts, end_ts, level="error|warning")
    insights = extract_log_insights(result)

    return {
        "namespace": namespace,
        "time_range": f"{start_time.strftime('%Y-%m-%d %H:%M')} - {end_time.strftime('%Y-%m-%d %H:%M')}",
        "raw_result": result,
        "insights": insights,
        "status": result.get("status", "unknown")
    }


def correlate_logs_with_alert(alert_data: Dict[str, Any], namespace: str) -> Dict[str, Any]:
    """
    Correlate alert information with relevant logs for enhanced root cause analysis
    """
    alert_time = alert_data.get("activeAt", alert_data.get("startsAt"))
    if isinstance(alert_time, str):
        try:
            alert_time = datetime.fromisoformat(alert_time.replace('Z', '+00:00'))
        except:
            alert_time = datetime.now()
    elif not isinstance(alert_time, datetime):
        alert_time = datetime.now()

    # Get logs around alert time (default to infrastructure for alerts)
    log_result = get_logs_around_alert_time(namespace, alert_time, tenant="infrastructure")
    insights = extract_log_insights(log_result)

    return {
        "alert": alert_data.get("labels", {}).get("alertname", "Unknown Alert"),
        "namespace": namespace,
        "alert_time": alert_time.isoformat(),
        "log_insights": insights,
        "raw_logs": log_result,
        "correlation_status": log_result.get("status", "unknown")
    }


# Additional tenant-specific convenience functions
def get_application_logs(namespace: str, start_ts: int, end_ts: int, level: str = "error") -> Dict[str, Any]:
    """
    Get application logs for a specific namespace
    """
    query = f'{{namespace="{namespace}", level="{level}"}}'
    return query_loki_logs(query, start_ts, end_ts, tenant="application")


def get_audit_logs(namespace: str, start_ts: int, end_ts: int) -> Dict[str, Any]:
    """
    Get audit logs for a specific namespace
    """
    query = f'{{namespace="{namespace}"}}'
    return query_loki_logs(query, start_ts, end_ts, tenant="audit")


def query_all_tenants(namespace: str, start_ts: int, end_ts: int, level: str = "error") -> Dict[str, Any]:
    """
    Query all three tenants and combine results for comprehensive log analysis
    """
    results = {}

    # Query each tenant
    for tenant in ["application", "infrastructure", "audit"]:
        try:
            query = f'{{namespace="{namespace}", level="{level}"}}'
            result = query_loki_logs(query, start_ts, end_ts, tenant=tenant)
            results[tenant] = result
        except Exception as e:
            results[tenant] = {
                "status": "error",
                "error": str(e),
                "data": {}
            }

    # Combine insights
    all_insights = []
    total_logs = 0

    for tenant, result in results.items():
        if result.get("status") == "success":
            insights = extract_log_insights(result)
            all_insights.extend([f"[{tenant.upper()}] {insight}" for insight in insights])
            total_logs += result.get("log_count", 0)

    return {
        "namespace": namespace,
        "tenants": results,
        "combined_insights": all_insights,
        "total_logs": total_logs,
        "time_range": f"{datetime.fromtimestamp(start_ts)} to {datetime.fromtimestamp(end_ts)}"
    }
