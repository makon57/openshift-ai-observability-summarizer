#!/usr/bin/env python3
"""
Test script for Loki integration with the observability summarizer
"""

import sys
import os
from datetime import datetime, timedelta

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from core.loki_service import (
    get_recent_logs_summary,
    get_infrastructure_logs_for_namespace,
    query_loki_logs
)

def test_loki_connection():
    """Test basic Loki connectivity"""
    print("🔍 Testing Loki connection...")
    
    # Test a simple query for logs in observability-hub namespace
    end_time = datetime.now()
    start_time = end_time - timedelta(hours=1)
    
    start_ts = int(start_time.timestamp())
    end_ts = int(end_time.timestamp())
    
    result = query_loki_logs('{namespace="observability-hub"}', start_ts, end_ts, limit=10)
    
    print(f"Status: {result.get('status')}")
    if result.get('status') == 'success':
        print(f"✅ Loki connection successful!")
        print(f"Log count: {result.get('log_count', 0)}")
    else:
        print(f"❌ Loki connection failed: {result.get('error', 'Unknown error')}")
    
    return result

def test_log_summary():
    """Test the log summary functionality"""
    print("\n🔍 Testing log summary for observability-hub namespace...")
    
    summary = get_recent_logs_summary("observability-hub", hours=1)
    
    print(f"Status: {summary.get('status')}")
    print(f"Time range: {summary.get('time_range')}")
    
    insights = summary.get('insights', [])
    if insights:
        print("Insights found:")
        for insight in insights:
            print(f"  • {insight}")
    else:
        print("No insights generated")
    
    return summary

def test_infrastructure_logs():
    """Test infrastructure log queries"""
    print("\n🔍 Testing infrastructure logs for openshift-logging namespace...")
    
    end_time = datetime.now()
    start_time = end_time - timedelta(hours=1)
    
    start_ts = int(start_time.timestamp())
    end_ts = int(end_time.timestamp())
    
    result = get_infrastructure_logs_for_namespace("openshift-logging", start_ts, end_ts, level="error")
    
    print(f"Status: {result.get('status')}")
    if result.get('status') == 'success':
        print(f"Log count: {result.get('log_count', 0)}")
        print("✅ Infrastructure log query successful!")
    else:
        print(f"❌ Infrastructure log query failed: {result.get('error', 'Unknown error')}")
    
    return result

if __name__ == "__main__":
    print("🚀 Starting Loki integration tests...\n")
    
    # Test 1: Basic connection
    test_loki_connection()
    
    # Test 2: Log summary
    test_log_summary()
    
    # Test 3: Infrastructure logs
    test_infrastructure_logs()
    
    print("\n✅ Loki integration tests completed!")