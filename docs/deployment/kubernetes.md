# Kubernetes Deployment

This guide covers the Kubernetes deployment configuration for the YouTube RAG Server.

## Architecture Overview

The deployment follows a **Kustomize base/overlays pattern** with environment-specific configurations:

```
infrastructure/applications/youtube-mcp/
├── base/                        # Base manifests (environment-agnostic)
│   ├── kustomization.yaml
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── config-map.yaml
│   └── network-policies.yaml
└── overlays/
    ├── dev/                     # Development environment
    │   ├── kustomization.yaml
    │   ├── config-map.yaml
    │   ├── ingress-route.yaml
    │   ├── resource-quota.yaml
    │   ├── certificate.yaml
    │   └── sealed-secret.yaml
    └── prod/                    # Production environment
        ├── kustomization.yaml
        ├── config-map.yaml
        ├── ingress-route.yaml
        ├── resource-quota.yaml
        ├── certificate.yaml
        └── sealed-secret.yaml
```

## Base Configuration

## Environment Configuration

### ConfigMap Variables

The application uses environment variables with the prefix `YOUTUBE_RAG__` and double underscore for nesting.

#### Base ConfigMap (shared across environments)

```yaml
# Application
YOUTUBE_RAG__APP__NAME: "youtube-rag-server"
YOUTUBE_RAG__APP__VERSION: "0.1.0"

# Server
YOUTUBE_RAG__SERVER__HOST: "0.0.0.0"
YOUTUBE_RAG__SERVER__PORT: "8000"
YOUTUBE_RAG__SERVER__API_PREFIX: "/v1"

# Infrastructure (cluster internal)
YOUTUBE_RAG__BLOB_STORAGE__ENDPOINT: "minio:9000"
YOUTUBE_RAG__VECTOR_DB__HOST: "qdrant"
YOUTUBE_RAG__DOCUMENT_DB__HOST: "mongodb"
```

#### Development Overrides

```yaml
YOUTUBE_RAG__APP__ENVIRONMENT: "dev"
YOUTUBE_RAG__APP__DEBUG: "true"
YOUTUBE_RAG__APP__LOG_LEVEL: "DEBUG"
YOUTUBE_RAG__SERVER__WORKERS: "2"
YOUTUBE_RAG__SERVER__DOCS_ENABLED: "true"
```

#### Production Overrides

```yaml
YOUTUBE_RAG__APP__ENVIRONMENT: "prod"
YOUTUBE_RAG__APP__DEBUG: "false"
YOUTUBE_RAG__APP__LOG_LEVEL: "WARNING"
YOUTUBE_RAG__SERVER__WORKERS: "4"
YOUTUBE_RAG__SERVER__DOCS_ENABLED: "false"
```

## Secrets Management

Secrets are managed using **Bitnami Sealed Secrets** and stored encrypted in Git.

### Required Secrets

| Secret Key | Description |
|------------|-------------|
| `YOUTUBE_RAG__BLOB_STORAGE__ACCESS_KEY` | MinIO/S3 access key |
| `YOUTUBE_RAG__BLOB_STORAGE__SECRET_KEY` | MinIO/S3 secret key |
| `YOUTUBE_RAG__DOCUMENT_DB__USERNAME` | MongoDB username |
| `YOUTUBE_RAG__DOCUMENT_DB__PASSWORD` | MongoDB password |
| `YOUTUBE_RAG__TRANSCRIPTION__API_KEY` | OpenAI Whisper API key |
| `YOUTUBE_RAG__EMBEDDINGS__TEXT__API_KEY` | OpenAI Embeddings API key |
| `YOUTUBE_RAG__LLM__API_KEY` | OpenAI LLM API key |

### Creating Sealed Secrets

```bash
# 1. Create a regular Kubernetes secret
kubectl create secret generic youtube-mcp-secrets \
  --namespace=youtube-mcp-prod \
  --from-literal=YOUTUBE_RAG__BLOB_STORAGE__ACCESS_KEY=your-access-key \
  --from-literal=YOUTUBE_RAG__BLOB_STORAGE__SECRET_KEY=your-secret-key \
  --from-literal=YOUTUBE_RAG__DOCUMENT_DB__USERNAME=admin \
  --from-literal=YOUTUBE_RAG__DOCUMENT_DB__PASSWORD=your-password \
  --from-literal=YOUTUBE_RAG__TRANSCRIPTION__API_KEY=sk-xxx \
  --from-literal=YOUTUBE_RAG__EMBEDDINGS__TEXT__API_KEY=sk-xxx \
  --from-literal=YOUTUBE_RAG__LLM__API_KEY=sk-xxx \
  --dry-run=client -o yaml > secret.yaml

# 2. Seal the secret
kubeseal --format=yaml < secret.yaml > sealed-secret.yaml

# 3. Replace the sealed-secret.yaml in the overlay
```

## Resource Quotas

### Development

```yaml
requests.cpu: "200m"
limits.cpu: "1"
requests.memory: "512Mi"
limits.memory: "1Gi"
pods: "5"
```

### Production

```yaml
requests.cpu: "400m"
limits.cpu: "2"
requests.memory: "1Gi"
limits.memory: "2Gi"
pods: "5"
```

## Ingress

The application uses **Traefik IngressRoute** with:

- HTTP to HTTPS redirect
- TLS certificates from Let's Encrypt (cert-manager)
- SSO middleware for authentication

```yaml
# Production IngressRoute
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: youtube-mcp-ingress
spec:
  entryPoints:
    - websecure
  routes:
    - kind: Rule
      match: Host(``)
      middlewares:
        - name: sso
          namespace: infrastructure
      services:
        - name: youtube-mcp
          port: 80
  tls:
    secretName: youtube-mcp-tls
```

## Infrastructure Dependencies

The application connects to services in the `shared-databases` namespace:

| Service | Port | Internal Address |
|---------|------|------------------|
| MongoDB | 27017 | `mongodb` |
| Qdrant REST | 6333 | `qdrant` |
| Qdrant gRPC | 6334 | `qdrant` |
| MinIO | 9000 | `minio` |

## Health Checks

| Endpoint | Probe Type | Purpose |
|----------|------------|---------|
| `/health` | Startup | Wait for app initialization |
| `/health/ready` | Readiness | Check if ready to serve traffic |
| `/health/live` | Liveness | Check if app is alive |

## Manual Deployment

To manually apply the manifests:

```bash
# Development
kubectl apply -k infrastructure/applications/youtube-mcp/overlays/dev

# Production
kubectl apply -k infrastructure/applications/youtube-mcp/overlays/prod
```

## Troubleshooting

### Check pod status

```bash
kubectl get pods -n youtube-mcp-prod
kubectl describe pod <pod-name> -n youtube-mcp-prod
```

### View logs

```bash
kubectl logs -f deployment/youtube-mcp -n youtube-mcp-prod
```

### Check network connectivity

```bash
# Test connection to MongoDB
kubectl exec -it deployment/youtube-mcp -n youtube-mcp-prod -- \
  curl -v mongodb:27017

# Test connection to Qdrant
kubectl exec -it deployment/youtube-mcp -n youtube-mcp-prod -- \
  curl -v qdrant:6333/health
```
