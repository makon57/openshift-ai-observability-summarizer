# Loki Deployment Notes

## Current Working Configuration

This Helm chart reflects the production-tested configuration that successfully resolved multiple critical issues in October 2025.

### ✅ Issues Resolved

1. **Storage Crisis**: MinIO usage reduced from 99% to 69%
2. **Ingester Ring Issues**: Set to 2 replicas for high availability
3. **Log Volume Management**: Implemented namespace filtering
4. **Retention Optimization**: Reduced retention periods for sustainability

### 📊 Current Settings

#### LokiStack Configuration

- **Size**: `1x.small`
- **Ingester Replicas**: `2` (critical for avoiding ring issues)
- **Storage**: Uses shared MinIO instance

#### Retention Policies

- **Global**: 3 days (reduced from 7)
- **Application**: 3 days (reduced from 7)
- **Infrastructure**: 7 days (reduced from 14)
- **Audit**: 1 day (reduced from 3, currently disabled)

#### Log Collection Filtering

- **Application Logs**: All namespaces (comprehensive coverage)
- **Infrastructure Logs**: Filtered to `node` and `container` sources only
- **Audit Logs**: **DISABLED** (due to high volume - can be re-enabled)

### 🚀 Deployment Instructions

1. **Prerequisites**:

   - OpenShift Logging Operator installed
   - Shared MinIO instance running in `observability-hub` namespace
   - `collector` service account exists in `openshift-logging` namespace

2. **Deploy**:

   ```bash
   helm install loki-stack deploy/helm/observability/loki \
     --namespace observability-hub \
     --create-namespace
   ```

3. **Verify**:

   ```bash
   # Check LokiStack status
   kubectl get lokistack logging-loki -n observability-hub

   # Check all pods are running
   kubectl get pods -n observability-hub | grep loki

   # Verify log forwarding
   kubectl get clusterlogforwarder logging-loki-forwarder -n openshift-logging
   ```

### ⚠️ Important Notes

- **Audit Logs**: Currently disabled due to volume. To re-enable, set `clusterLogging.logForwarder.inputs.audit.enabled: true`
- **Storage Monitoring**: Monitor MinIO usage regularly - should stay below 80%
- **Ingester Replicas**: Keep at 2 minimum to avoid ring coordination issues
- **WAL Cleanup**: If ingesters get stuck on startup, may need to clear WAL PVCs

### 🔧 Troubleshooting

#### Storage Full Issues

1. Check MinIO usage: `kubectl exec -n observability-hub minio-observability-storage-0 -- df -h`
2. Review retention policies if usage > 80%
3. Consider disabling audit logs temporarily

#### Ingester Issues

1. Check ingester readiness: `kubectl exec logging-loki-ingester-X -n observability-hub -- curl -k https://localhost:3101/ready`
2. If stuck on "recovering from checkpoint", may need to clear WAL PVC
3. Ensure 2 replicas are configured for ring stability

#### Log Collection Issues

1. Check ClusterLogForwarder status: `kubectl get clusterlogforwarder -n openshift-logging`
2. Verify collector pods are running: `kubectl get pods -n openshift-logging | grep forwarder`
3. Check RBAC permissions for `collector` service account

### 📈 Monitoring

Monitor these key metrics:

- MinIO storage usage (keep < 80%)
- Ingester pod status (both should be 1/1 Running)
- Log ingestion rates per tenant
- ClusterLogForwarder validation status

Last Updated: October 16, 2025
Configuration Version: v1.0 (Production Tested)
