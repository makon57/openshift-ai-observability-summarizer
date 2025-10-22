# Loki Deployment Guide - Production Tested Configuration

## Overview

This Helm chart contains the **production-tested configuration** that successfully resolved multiple critical issues encountered during deployment in October 2025. This guide ensures you can replicate the exact working setup.

**✅ NEW in v2.1**: The Helm chart is now **complete and self-contained**, automatically creating all necessary components including LokiStack deployment, RBAC, and log forwarding configuration. No manual setup steps required!

## ✅ Current Working Configuration

### LokiStack Configuration

- **Size**: `1x.small`
- **Ingester Replicas**: `2` (CRITICAL - prevents ring coordination issues)
- **Storage**: Shared MinIO instance in `observability-hub` namespace
- **Schema Version**: `v13` (updated from v12)

### Authentication & Security

- **TLS**: Currently uses `insecureSkipVerify: true` for internal cluster communication
- **Authentication**: Uses `collector` service account token from `openshift-logging` namespace
- **RBAC**: Proper ClusterRoles for tenant access (`application`, `infrastructure`, `audit`)
- **MCP Server Access**: Configured with collector token mounting for log queries

### Retention Policies (Optimized for Storage)

- **Global**: 3 days (reduced from 7 days)
- **Application**: 3 days (reduced from 7 days)
- **Infrastructure**: 7 days (reduced from 14 days)
- **Audit**: 1 day (reduced from 3 days) - **CURRENTLY DISABLED**

### Log Collection Filtering

- **Application Logs**: All namespaces (comprehensive coverage)
- **Infrastructure Logs**: Filtered to `node` and `container` sources only
- **Audit Logs**: **DISABLED** due to extreme volume (93GB in 2 days)

### MCP Server Integration

- **Loki URL**: `https://logging-loki-gateway-http.observability-hub.svc.cluster.local:8080`
- **Tenant Paths**: `/api/logs/v1/{tenant}/loki/api/v1/`
- **Token Access**: Uses collector token at `/var/run/secrets/loki/collector-token`
- **Fallback**: Environment variable `LOKI_TOKEN` for local development

## 🚀 Installation Instructions

### Prerequisites

1. **OpenShift Logging Operator** installed and configured
2. **Shared MinIO instance** running in `observability-hub` namespace
3. **Sufficient storage** - recommend 100GB+ for MinIO

**Note**: Collector service account and RBAC are now automatically created by the Helm chart.

### OpenShift Logging Setup (Automated by Helm Chart)

**✅ NEW**: The Helm chart now automatically creates all necessary RBAC components, including:

- **Collector Service Account** in `openshift-logging` namespace
- **ClusterRoles** for log collection permissions
- **ClusterRoleBindings** for proper access
- **MCP Server RBAC** for log querying

**No manual RBAC setup required** - the chart handles everything automatically!

### Step 1: Verify Prerequisites

```bash
# Check OpenShift Logging Operator
oc get csv -n openshift-logging | grep logging

# Check MinIO instance
oc get pods -n observability-hub | grep minio

# Check collector service account (will be created by Helm chart)
oc get sa collector -n openshift-logging

# Check storage availability
kubectl exec -n observability-hub minio-observability-storage-0 -- df -h | grep "/data"
```

### Step 2: Deploy Loki Stack

```bash
# Deploy the complete Loki stack (includes LokiStack, RBAC, and log forwarding)
helm install loki-stack deploy/helm/observability/loki \
  --namespace observability-hub \
  --create-namespace

# The chart automatically creates:
# - LokiStack instance with MinIO storage
# - Collector service account and RBAC in openshift-logging namespace
# - ClusterLogForwarder for log collection
# - MCP server RBAC for log querying
# - MinIO credentials secret

# Wait for LokiStack to be ready
kubectl wait --for=condition=Ready lokistack/logging-loki -n observability-hub --timeout=600s
```

### Step 3: Verify Deployment

```bash
# Check all Loki pods are running (should see 8 pods)
kubectl get pods -n observability-hub | grep loki

# Verify LokiStack status
kubectl get lokistack logging-loki -n observability-hub

# Check ClusterLogForwarder status
kubectl get clusterlogforwarder logging-loki-forwarder -n openshift-logging

# Verify log collection is working
kubectl get pods -n openshift-logging | grep forwarder
```

### Step 4: Monitor Storage Usage

```bash
# Check MinIO storage usage (should be < 80%)
kubectl exec -n observability-hub minio-observability-storage-0 -- df -h | grep "/data"

# Monitor ingester status
kubectl get pods -n observability-hub | grep ingester
```

## 🔧 Configuration Options

### Enable Audit Logs (Use with Caution)

```yaml
# In values.yaml
clusterLogging:
  logForwarder:
    inputs:
      audit:
        enabled: true # Change from false
```

### Enable Proper TLS Validation

```yaml
# In values.yaml
clusterLogging:
  logForwarder:
    tls:
      insecureSkipVerify: false # Change from true
```

### Adjust Retention Policies

```yaml
# In values.yaml
lokiStack:
  limits:
    global:
      retention:
        days: 7 # Increase if you have more storage
```

## 📊 Monitoring & Maintenance

### Key Metrics to Monitor

1. **Storage Usage**: Keep MinIO below 80% capacity
2. **Ingester Health**: Both ingesters should be `1/1 Running`
3. **Log Ingestion Rate**: Monitor per-tenant rates
4. **ClusterLogForwarder Status**: Should be `Ready: True`

### Regular Maintenance Tasks

```bash
# Weekly storage check
kubectl exec -n observability-hub minio-observability-storage-0 -- df -h

# Check for failed pods
kubectl get pods -n observability-hub | grep -v Running

# Verify log collection status
kubectl get clusterlogforwarder -n openshift-logging -o yaml | grep -A 5 "conditions:"
```

## 🚨 Critical Issues Encountered & Solutions

### Issue 1: Storage Crisis - MinIO 99% Full

**Problem**: MinIO storage reached 99% capacity, causing all ingesters to fail with `XMinioStorageFull` errors.

**Root Cause**: Audit logs consumed 93GB in 2 days (96% of total storage).

**Solution**:

1. **Immediate**: Manually deleted audit log directory from MinIO
2. **Temporary**: Disabled audit log collection
3. **Long-term**: Reduced retention policies across all tenants
4. **Result**: Storage usage dropped from 99% to 5%, then stabilized at ~18%

**Prevention**:

```bash
# Monitor storage regularly
kubectl exec -n observability-hub minio-observability-storage-0 -- df -h | grep "/data"

# Keep audit logs disabled unless absolutely necessary
# If enabled, use very short retention (1 day max)
```

### Issue 2: Ingester Ring Coordination Failures

**Problem**: Single ingester couldn't handle load and kept failing with ring coordination errors.

**Symptoms**:

- `logging-loki-ingester-0` showing `0/1 Running`
- Logs: "at least 2 live replicas required"
- Readiness probe failing with 503 status

**Solution**:

1. **Scaled ingesters to 2 replicas** for high availability
2. **Updated LokiStack template** to prevent single points of failure
3. **Verified ring membership** was healthy

**Configuration**:

```yaml
lokiStack:
  template:
    ingester:
      replicas: 2 # CRITICAL - never use 1 replica
```

### Issue 3: Ingester Stuck on WAL Recovery

**Problem**: After storage crisis, ingester-1 was stuck "recovering from checkpoint" with 87GB of WAL data.

**Symptoms**:

- Ingester showing `0/1 Running` for hours
- Logs: "recovering from checkpoint"
- Readiness probe failing

**Solution**:

1. **Deleted the problematic ingester pod**
2. **Deleted the WAL PVC** to clear checkpoint data
3. **Allowed fresh PVC creation** on pod restart
4. **Result**: Ingester started cleanly in seconds

**Prevention**:

```bash
# If ingester stuck on recovery, check WAL size
kubectl exec logging-loki-ingester-X -n observability-hub -- du -sh /tmp/wal

# If > 10GB, consider clearing WAL PVC
kubectl delete pvc wal-logging-loki-ingester-X -n observability-hub
```

### Issue 4: Namespace Filtering Complexity

**Problem**: Initial namespace filtering was too restrictive and complex to configure correctly.

**Evolution**:

1. **Started with**: Specific namespace lists for applications
2. **Encountered**: Syntax errors with infrastructure filtering
3. **Learned**: Infrastructure only supports `node` and `container` sources
4. **Final Solution**: All namespaces for applications, minimal sources for infrastructure

**Working Configuration**:

```yaml
inputs:
  application:
    allNamespaces: true # Comprehensive coverage
  infrastructure:
    sources: [node, container] # Minimal but sufficient
  audit:
    enabled: false # Disabled due to volume
```

### Issue 5: Authentication Token Confusion

**Problem**: Multiple service accounts and tokens caused confusion about which to use.

**Tokens Encountered**:

- `logging-loki-gateway-token` (gateway internal use)
- `loki-log-forwarder-token` (insufficient permissions)
- `collector-token` (correct choice)

**Solution**: Use `collector` service account token which has proper ClusterRoleBindings for tenant access.

**MCP Server Configuration**:

```python
# Priority order for token access:
1. LOKI_TOKEN environment variable (dev)
2. /var/run/secrets/loki/collector-token (production)
3. /var/run/secrets/kubernetes.io/serviceaccount/token (fallback)
```

### Issue 6: ClusterLogForwarder Validation Failures

**Problem**: ClusterLogForwarder showing validation failures and "collector not ready".

**Causes**:

- Unused audit output (not referenced by pipeline)
- Custom input syntax errors
- Missing service account permissions

**Solution**:

1. **Removed unused audit pipeline** when audit disabled
2. **Fixed input syntax** for application and infrastructure
3. **Verified RBAC permissions** for collector service account

### Issue 7: Compactor Waiting 2 Hours

**Problem**: After storage cleanup, compactor waited 2 hours before starting cleanup operations.

**Solution**: Restart compactor pod to trigger immediate cleanup without waiting period.

```bash
kubectl delete pod logging-loki-compactor-0 -n observability-hub
```

## 🔍 Troubleshooting Guide

### Storage Issues

```bash
# Check MinIO usage
kubectl exec -n observability-hub minio-observability-storage-0 -- df -h

# If > 80%, check log sizes
kubectl exec -n observability-hub minio-observability-storage-0 -- du -sh /data/loki/*

# Emergency: disable audit logs
kubectl patch clusterlogforwarder logging-loki-forwarder -n openshift-logging --type='merge' -p='{"spec":{"pipelines":[{"name":"application-logs","inputRefs":["application-all-namespaces"],"outputRefs":["loki-application"]},{"name":"infrastructure-logs","inputRefs":["infrastructure-minimal"],"outputRefs":["loki-infrastructure"]}]}}'
```

### Ingester Issues

```bash
# Check ingester readiness
kubectl exec logging-loki-ingester-X -n observability-hub -- curl -k -s https://localhost:3101/ready

# If stuck on recovery, check WAL size
kubectl exec logging-loki-ingester-X -n observability-hub -- du -sh /tmp/wal

# Force restart if needed
kubectl delete pod logging-loki-ingester-X -n observability-hub
```

### Log Collection Issues

```bash
# Check ClusterLogForwarder status
kubectl get clusterlogforwarder logging-loki-forwarder -n openshift-logging -o yaml | grep -A 10 "conditions:"

# Check forwarder pods (created by ClusterLogForwarder)
kubectl get pods -n openshift-logging | grep forwarder

# Verify collector service account exists
oc get sa collector -n openshift-logging

# Check collector RBAC permissions
kubectl auth can-i create application.loki.grafana.com --as=system:serviceaccount:openshift-logging:collector
kubectl auth can-i get pods --as=system:serviceaccount:openshift-logging:collector
kubectl auth can-i get nodes --as=system:serviceaccount:openshift-logging:collector

# If collector SA missing, redeploy the Helm chart:
helm upgrade loki-stack deploy/helm/observability/loki \
  --namespace observability-hub \
  --set rbac.collector.create=true

# The chart will automatically create all necessary RBAC components
```

## 📈 Performance Characteristics

### Tested Load Capacity

- **Application Logs**: All namespaces, ~500 logs/sec sustained
- **Infrastructure Logs**: Node + container sources, ~500 logs/sec sustained
- **Storage Growth**: ~2-3GB/day with current filtering
- **Query Performance**: Sub-second for recent logs, 2-5s for historical

### Resource Usage

- **LokiStack Size**: 1x.small handles current load comfortably
- **MinIO Storage**: 100GB sufficient for 2+ weeks retention
- **Memory**: Ingesters use ~2GB each under normal load
- **CPU**: Low usage except during compaction cycles

## 🎯 Success Metrics

After implementing all fixes:

- ✅ **Storage Usage**: Stable at 18% (down from 99%)
- ✅ **All Loki Components**: 8/8 pods running healthy
- ✅ **Log Collection**: Both application and infrastructure working
- ✅ **MCP Integration**: Log queries working for summarization
- ✅ **System Stability**: No ingester failures for 24+ hours
- ✅ **Query Performance**: Sub-second response times

---

## 📦 Helm Chart Components

The complete Loki stack now includes these templates:

- **`Chart.yaml`** - Helm chart metadata and dependencies
- **`templates/_helpers.tpl`** - Template helper functions for consistent labeling
- **`templates/lokistack.yaml`** - LokiStack CRD deployment with multitenant configuration
- **`templates/minio-secrets.yaml`** - MinIO S3 credentials for storage backend
- **`templates/clusterlogforwarder.yaml`** - Log forwarding configuration
- **`templates/rbac.yaml`** - Core RBAC for log collection service accounts
- **`templates/collector-rbac.yaml`** - Collector service account and permissions
- **`templates/mcp-rbac.yaml`** - MCP server access to collector tokens
- **`values.yaml`** - Complete configuration with MCP server integration

---

**Last Updated**: October 22, 2025
**Configuration Version**: v2.1 (Complete Helm Chart)
**Tested Environment**: OpenShift 4.x with OpenShift Logging 5.x
