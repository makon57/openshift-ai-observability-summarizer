# Loki Integration for Infrastructure-First Logging

## Overview

Adds **infrastructure-first logging** to the AI observability summarizer, enabling complete root cause analysis by correlating logs with metrics and traces.

## Architecture

```
Metrics (Thanos) + Traces (Tempo) + Logs (Loki) → AI Summarizer → Enhanced Insights
```

**Before**: Alert shows "CPU high" + trace shows "slow DB calls" = **Missing WHY**
**After**: + Logs show "Connection pool exhausted, OOM" = **Complete root cause**

## Core Components

### 1. LokiStack Configuration

```yaml
# Required: Static tenant mode with explicit tenants
spec:
  tenants:
    mode: static
    authentication:
      - { tenantName: application, tenantId: application }
      - { tenantName: infrastructure, tenantId: infrastructure }
      - { tenantName: audit, tenantId: audit }
```

### 2. ClusterLogForwarder (Multi-Tenant)

```yaml
# Separates log types into different Loki tenants
outputs:
  - name: loki-application
    loki:
      url: https://logging-loki-gateway-http.openshift-logging.svc:8080/api/logs/v1/application/loki/api/v1/push
  - name: loki-infrastructure
    loki:
      url: https://logging-loki-gateway-http.openshift-logging.svc:8080/api/logs/v1/infrastructure/loki/api/v1/push
  - name: loki-audit
    loki:
      url: https://logging-loki-gateway-http.openshift-logging.svc:8080/api/logs/v1/audit/loki/api/v1/push

pipelines:
  - {
      name: app-to-loki,
      inputRefs: [application],
      outputRefs: [loki-application],
    }
  - {
      name: infra-to-loki,
      inputRefs: [infrastructure],
      outputRefs: [loki-infrastructure],
    }
  - { name: audit-to-loki, inputRefs: [audit], outputRefs: [loki-audit] }
```

### 3. Application Integration (`src/core/loki_service.py`)

```python
# Automatic log correlation in AI summaries
def generate_llm_summary(question, thanos_data, model_id, api_key, namespace, include_logs=True):
    # Fetches relevant logs and correlates with metrics/traces

# Multi-tenant log querying
def query_all_tenants(namespace, start_ts, end_ts, level="error"):
    # Returns comprehensive insights from all log types
```

## How It Works

### Log Collection Flow

```
OpenShift Nodes → Vector Collectors → ClusterLogForwarder → Loki Tenants → AI Analysis
```

1. **Vector collectors** gather logs from all cluster nodes
2. **ClusterLogForwarder** routes logs by type (app/infra/audit) to separate Loki tenants
3. **Loki Gateway** enforces tenant isolation and authentication
4. **AI Summarizer** queries relevant tenants and correlates with metrics/traces

### Query Flow

```python
# Example: Alert analysis with log correlation
summary = generate_llm_summary("Why is pod failing?", thanos_data, model_id, api_key, "my-namespace")

# Automatically queries:
# 1. Thanos for metrics (CPU, memory, alerts)
# 2. Tempo for traces (if configured)
# 3. Loki infrastructure tenant for error logs
# 4. Correlates all data for comprehensive insights
```

## Key Functions

```python
# Get recent errors for correlation
get_recent_logs_summary("namespace", hours=1)

# Tenant-specific queries
get_application_logs("namespace", start_ts, end_ts, level="error")
get_infrastructure_logs_for_namespace("namespace", start_ts, end_ts, level="warning")
get_audit_logs("namespace", start_ts, end_ts)

# Comprehensive analysis
query_all_tenants("namespace", start_ts, end_ts, level="error")
```

## Configuration

### Environment Variables

```bash
# Local development
export LOKI_URL="https://localhost:3100"
export LOKI_TOKEN="$(oc whoami -t)"

# In-cluster
export LOKI_URL="https://logging-loki-gateway-http.openshift-logging.svc.cluster.local:8080"
export LOKI_TOKEN="$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)"
```

### RBAC Requirements

```bash
# Apply logging permissions
oc adm policy add-cluster-role-to-user logging-collector-logs-writer -z collector -n openshift-logging
oc adm policy add-cluster-role-to-user collect-application-logs -z collector -n openshift-logging
oc adm policy add-cluster-role-to-user collect-infrastructure-logs -z collector -n openshift-logging
oc adm policy add-cluster-role-to-user collect-audit-logs -z collector -n openshift-logging
```

## Deployment

### Automated Setup

```bash
# Apply tenant-specific configuration
./scripts/apply-loki-tenant-fix.sh

# Test all tenants
python scripts/test-loki-tenants.py
```

### Manual Verification

```bash
# Test tenant connectivity
TOKEN=$(oc whoami -t)
curl -k -H "Authorization: Bearer $TOKEN" \
  "https://localhost:3100/api/logs/v1/infrastructure/loki/api/v1/labels"

# Check log ingestion
python tests/test_loki_integration.py
```

## Troubleshooting

**404 Errors from Collectors**: LokiStack needs `mode: static` with explicit tenant definitions
**No Logs Found**: Normal for quiet periods; check ClusterLogForwarder status
**Permission Denied**: Ensure RBAC permissions are applied to collector service account

## Benefits

- **Complete Observability**: Metrics + Traces + Logs in one AI analysis
- **Faster Resolution**: Automated correlation reduces manual investigation
- **Infrastructure Focus**: Platform-level insights for system health
- **Tenant Isolation**: Separate storage for different log types

## File Structure

```
src/core/loki_service.py          # Multi-tenant log querying
src/core/llm_summary_service.py   # Enhanced with log correlation
scripts/apply-loki-tenant-fix.sh  # Automated deployment
scripts/test-loki-tenants.py      # Comprehensive testing
cluster-log-forwarder-tenant-fix.yaml # Tenant configuration
```

This integration provides production-ready infrastructure-first logging with complete observability correlation through AI analysis.
