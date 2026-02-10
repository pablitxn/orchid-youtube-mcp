# Deployment Strategy

## Overview

The YouTube RAG Server is designed for cloud-native deployment using:
- **Containerization**: Docker for packaging
- **Orchestration**: Kubernetes for deployment
- **GitOps**: ArgoCD for continuous deployment
- **Environments**: dev, staging, prod with progressive rollout

---

## Container Strategy

### Dockerfile

```dockerfile
# Build stage
FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN pip install poetry==1.7.1

# Copy dependency files
COPY pyproject.toml poetry.lock ./

# Export dependencies to requirements.txt
RUN poetry export -f requirements.txt --output requirements.txt --without-hashes

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Runtime stage
FROM python:3.11-slim as runtime

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY src/ ./src/
COPY config/ ./config/

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health')"

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "src.adapters.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Multi-Architecture Build

```yaml
# .github/workflows/build.yml
name: Build and Push

on:
  push:
    branches: [main]
    tags: ['v*']

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up QEMU
        uses: docker/setup-qemu-action@v3

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Login to Registry
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          context: .
          platforms: linux/amd64,linux/arm64
          push: true
          tags: |
            ghcr.io/${{ github.repository }}:${{ github.sha }}
            ghcr.io/${{ github.repository }}:latest
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

---

## Kubernetes Manifests

### Directory Structure

```
k8s/
├── base/
│   ├── kustomization.yaml
│   ├── namespace.yaml
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── configmap.yaml
│   ├── hpa.yaml
│   └── pdb.yaml
└── overlays/
    ├── dev/
    │   ├── kustomization.yaml
    │   ├── configmap-patch.yaml
    │   └── deployment-patch.yaml
    ├── staging/
    │   ├── kustomization.yaml
    │   ├── configmap-patch.yaml
    │   └── deployment-patch.yaml
    └── prod/
        ├── kustomization.yaml
        ├── configmap-patch.yaml
        ├── deployment-patch.yaml
        └── ingress.yaml
```

### Base Manifests

#### kustomization.yaml

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

namespace: youtube-rag

resources:
  - namespace.yaml
  - deployment.yaml
  - service.yaml
  - configmap.yaml
  - hpa.yaml
  - pdb.yaml

commonLabels:
  app: youtube-rag-server
  app.kubernetes.io/name: youtube-rag-server
  app.kubernetes.io/component: api
```

#### namespace.yaml

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: youtube-rag
  labels:
    name: youtube-rag
```

#### deployment.yaml

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: youtube-rag-server
spec:
  replicas: 2
  selector:
    matchLabels:
      app: youtube-rag-server
  template:
    metadata:
      labels:
        app: youtube-rag-server
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8000"
        prometheus.io/path: "/metrics"
    spec:
      serviceAccountName: youtube-rag-server
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        fsGroup: 1000

      containers:
        - name: api
          image: ghcr.io/org/youtube-rag-server:latest
          imagePullPolicy: Always

          ports:
            - name: http
              containerPort: 8000
              protocol: TCP

          envFrom:
            - configMapRef:
                name: youtube-rag-config
            - secretRef:
                name: youtube-rag-secrets

          resources:
            requests:
              memory: "512Mi"
              cpu: "250m"
            limits:
              memory: "2Gi"
              cpu: "1000m"

          livenessProbe:
            httpGet:
              path: /health/live
              port: http
            initialDelaySeconds: 10
            periodSeconds: 15
            timeoutSeconds: 5
            failureThreshold: 3

          readinessProbe:
            httpGet:
              path: /health/ready
              port: http
            initialDelaySeconds: 5
            periodSeconds: 10
            timeoutSeconds: 5
            failureThreshold: 3

          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop:
                - ALL

          volumeMounts:
            - name: tmp
              mountPath: /tmp
            - name: config
              mountPath: /app/config
              readOnly: true

      volumes:
        - name: tmp
          emptyDir: {}
        - name: config
          configMap:
            name: youtube-rag-config-files

      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              podAffinityTerm:
                labelSelector:
                  matchLabels:
                    app: youtube-rag-server
                topologyKey: kubernetes.io/hostname

      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: topology.kubernetes.io/zone
          whenUnsatisfiable: ScheduleAnyway
          labelSelector:
            matchLabels:
              app: youtube-rag-server
```

#### service.yaml

```yaml
apiVersion: v1
kind: Service
metadata:
  name: youtube-rag-server
spec:
  type: ClusterIP
  ports:
    - name: http
      port: 80
      targetPort: http
      protocol: TCP
  selector:
    app: youtube-rag-server
```

#### configmap.yaml

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: youtube-rag-config
data:
  YOUTUBE_RAG__APP__NAME: "youtube-rag-server"
  YOUTUBE_RAG__APP__ENVIRONMENT: "dev"
  YOUTUBE_RAG__SERVER__HOST: "0.0.0.0"
  YOUTUBE_RAG__SERVER__PORT: "8000"
  YOUTUBE_RAG__VECTOR_DB__HOST: "qdrant"
  YOUTUBE_RAG__VECTOR_DB__PORT: "6333"
  YOUTUBE_RAG__DOCUMENT_DB__HOST: "mongodb"
  YOUTUBE_RAG__DOCUMENT_DB__PORT: "27017"
  YOUTUBE_RAG__BLOB_STORAGE__ENDPOINT: "minio:9000"
```

#### hpa.yaml

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: youtube-rag-server
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: youtube-rag-server
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 80
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Percent
          value: 10
          periodSeconds: 60
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
        - type: Percent
          value: 100
          periodSeconds: 15
        - type: Pods
          value: 4
          periodSeconds: 15
      selectPolicy: Max
```

#### pdb.yaml

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: youtube-rag-server
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app: youtube-rag-server
```

---

### Environment Overlays

#### Production Overlay (overlays/prod/kustomization.yaml)

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

namespace: youtube-rag-prod

resources:
  - ../../base
  - ingress.yaml
  - certificate.yaml

patches:
  - path: deployment-patch.yaml
  - path: configmap-patch.yaml

images:
  - name: ghcr.io/org/youtube-rag-server
    newTag: v1.0.0  # Pinned version

replicas:
  - name: youtube-rag-server
    count: 4

configMapGenerator:
  - name: youtube-rag-config
    behavior: merge
    literals:
      - YOUTUBE_RAG__APP__ENVIRONMENT=prod
      - YOUTUBE_RAG__APP__DEBUG=false
      - YOUTUBE_RAG__SERVER__WORKERS=4
```

#### Production Ingress

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: youtube-rag-server
  annotations:
    kubernetes.io/ingress.class: nginx
    cert-manager.io/cluster-issuer: letsencrypt-prod
    nginx.ingress.kubernetes.io/rate-limit: "100"
    nginx.ingress.kubernetes.io/rate-limit-window: "1m"
spec:
  tls:
    - hosts:
        - api.youtube-rag.example.com
      secretName: youtube-rag-tls
  rules:
    - host: api.youtube-rag.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: youtube-rag-server
                port:
                  number: 80
```

---

## ArgoCD Configuration

### Application Manifest

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: youtube-rag-server-prod
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default

  source:
    repoURL: https://github.com/org/youtube-rag-server.git
    targetRevision: main
    path: k8s/overlays/prod

  destination:
    server: https://kubernetes.default.svc
    namespace: youtube-rag-prod

  syncPolicy:
    automated:
      prune: true
      selfHeal: true
      allowEmpty: false
    syncOptions:
      - CreateNamespace=true
      - PrunePropagationPolicy=foreground
      - PruneLast=true
    retry:
      limit: 5
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m

  revisionHistoryLimit: 10
```

### ApplicationSet for Multiple Environments

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: youtube-rag-server
  namespace: argocd
spec:
  generators:
    - list:
        elements:
          - env: dev
            cluster: https://kubernetes.default.svc
            revision: main
          - env: staging
            cluster: https://kubernetes.default.svc
            revision: main
          - env: prod
            cluster: https://kubernetes.default.svc
            revision: v1.0.0  # Pinned tag

  template:
    metadata:
      name: 'youtube-rag-server-{{env}}'
    spec:
      project: default
      source:
        repoURL: https://github.com/org/youtube-rag-server.git
        targetRevision: '{{revision}}'
        path: 'k8s/overlays/{{env}}'
      destination:
        server: '{{cluster}}'
        namespace: 'youtube-rag-{{env}}'
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
```

---

## Infrastructure Dependencies

### External Services (Managed)

For production, use managed services:

| Service | Provider Options |
|---------|------------------|
| **Vector DB** | Qdrant Cloud, Pinecone, Weaviate Cloud |
| **Document DB** | MongoDB Atlas, AWS DocumentDB |
| **Blob Storage** | AWS S3, Google Cloud Storage, Azure Blob |
| **Redis** (rate limiting) | AWS ElastiCache, Redis Cloud |

### Internal Services (Self-hosted)

For dev/staging, deploy alongside the app:

```yaml
# docker-compose.yml for local development
version: '3.8'

services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - YOUTUBE_RAG__APP__ENVIRONMENT=dev
    depends_on:
      - qdrant
      - mongodb
      - minio

  qdrant:
    image: qdrant/qdrant:latest
    ports:
      - "6333:6333"
    volumes:
      - qdrant_data:/qdrant/storage

  mongodb:
    image: mongo:7
    ports:
      - "27017:27017"
    environment:
      MONGO_INITDB_ROOT_USERNAME: admin
      MONGO_INITDB_ROOT_PASSWORD: changeme
    volumes:
      - mongo_data:/data/db

  minio:
    image: minio/minio:latest
    ports:
      - "9000:9000"
      - "9001:9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    command: server /data --console-address ":9001"
    volumes:
      - minio_data:/data

volumes:
  qdrant_data:
  mongo_data:
  minio_data:
```

---

## Monitoring & Observability

### Prometheus ServiceMonitor

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: youtube-rag-server
  labels:
    app: youtube-rag-server
spec:
  selector:
    matchLabels:
      app: youtube-rag-server
  endpoints:
    - port: http
      path: /metrics
      interval: 30s
```

### Grafana Dashboard

Key metrics to monitor:
- Request latency (p50, p95, p99)
- Request rate by endpoint
- Error rate by status code
- Active ingestion jobs
- Queue depth
- Vector search latency
- LLM API latency and token usage

### Loki Log Aggregation

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: promtail-config
data:
  promtail.yaml: |
    server:
      http_listen_port: 9080
    positions:
      filename: /tmp/positions.yaml
    clients:
      - url: http://loki:3100/loki/api/v1/push
    scrape_configs:
      - job_name: kubernetes-pods
        kubernetes_sd_configs:
          - role: pod
        relabel_configs:
          - source_labels: [__meta_kubernetes_pod_label_app]
            regex: youtube-rag-server
            action: keep
```

---

## Deployment Pipeline

### GitOps Workflow

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Commit    │───▶│    Build    │───▶│    Test     │───▶│    Push     │
│   to main   │    │   Docker    │    │   Image     │    │   to GHCR   │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
                                                                │
                                                                ▼
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│    Prod     │◀───│   Staging   │◀───│     Dev     │◀───│   ArgoCD    │
│   Deploy    │    │   Deploy    │    │   Deploy    │    │    Sync     │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
```

### Release Process

1. **Development**: Commits to `main` auto-deploy to dev
2. **Staging**: Tag with `staging-*` to deploy to staging
3. **Production**: Tag with `v*` (semver) to deploy to prod

```bash
# Deploy to staging
git tag staging-$(date +%Y%m%d-%H%M%S)
git push --tags

# Deploy to production
git tag v1.0.0
git push --tags
```

---

## Rollback Strategy

### Automatic Rollback

ArgoCD can automatically rollback on sync failure:

```yaml
syncPolicy:
  automated:
    selfHeal: true
  retry:
    limit: 3
    backoff:
      duration: 5s
      factor: 2
```

### Manual Rollback

```bash
# Rollback to previous version
argocd app rollback youtube-rag-server-prod

# Rollback to specific revision
argocd app rollback youtube-rag-server-prod --revision 5

# Or via kubectl
kubectl rollout undo deployment/youtube-rag-server -n youtube-rag-prod
```

---

## Security Considerations

### Network Policies

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: youtube-rag-server
spec:
  podSelector:
    matchLabels:
      app: youtube-rag-server
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              name: ingress-nginx
      ports:
        - protocol: TCP
          port: 8000
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              name: youtube-rag
      ports:
        - protocol: TCP
          port: 6333  # Qdrant
        - protocol: TCP
          port: 27017 # MongoDB
        - protocol: TCP
          port: 9000  # MinIO
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
      ports:
        - protocol: TCP
          port: 443  # External APIs
```

### Pod Security Standards

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: youtube-rag-prod
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted
```
