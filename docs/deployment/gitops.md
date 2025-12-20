# GitOps with ArgoCD

This guide covers the GitOps deployment workflow using ArgoCD for the YouTube RAG Server.

## Architecture

The deployment uses a **multi-repo GitOps** pattern:

```
┌─────────────────────────────┐     ┌─────────────────────────────────┐
│     youtube_mcp     │     │     playground-infrastructure   │
│    (Application Code)       │     │      (K8s Manifests)            │
├─────────────────────────────┤     ├─────────────────────────────────┤
│ - Source code               │     │ - ArgoCD Applications           │
│ - Dockerfile                │     │ - Kustomize base/overlays       │
│ - CI/CD workflows           │     │ - ConfigMaps                    │
│ - Image digest refs         │     │ - Sealed Secrets                │
│   (infrastructure/overlays) │     │ - Network Policies              │
└─────────────────────────────┘     └─────────────────────────────────┘
            │                                      │
            │  Build & Push Image                  │
            ▼                                      ▼
┌─────────────────────────────┐     ┌─────────────────────────────────┐
│         GHCR                │     │          ArgoCD                 │
│   (Container Registry)      │◀────│    (GitOps Controller)          │
└─────────────────────────────┘     └─────────────────────────────────┘
                                                   │
                                                   ▼
                                    ┌─────────────────────────────────┐
                                    │      Kubernetes Cluster         │
                                    │  youtube-mcp-dev / prod         │
                                    └─────────────────────────────────┘
```

## ArgoCD Configuration

### Project Definition

```yaml
# infrastructure/argocd-apps/youtube-mcp/project.yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: youtube-mcp
  namespace: argocd
spec:
  description: Youtube MCP - YouTube RAG Server

  sourceRepos:
    - "git@github.com:pablitxn/youtube-mcp.git"
    - "git@github.com:pablitxn/playground-infrastructure.git"

  destinations:
    - namespace: youtube-mcp-prod
      server: https://kubernetes.default.svc
    - namespace: youtube-mcp-dev
      server: https://kubernetes.default.svc

  clusterResourceWhitelist:
    - group: ''
      kind: Namespace
```

### Application Definitions

#### Development

```yaml
# infrastructure/argocd-apps/youtube-mcp/youtube-mcp-dev.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: youtube-mcp-dev
  namespace: argocd
spec:
  project: youtube-mcp
  source:
    repoURL: git@github.com:pablitxn/youtube-mcp.git
    targetRevision: dev
    path: infrastructure/overlays/dev
  destination:
    server: https://kubernetes.default.svc
    namespace: youtube-mcp-dev
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

#### Production

```yaml
# infrastructure/argocd-apps/youtube-mcp/youtube-mcp-prod.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: youtube-mcp-prod
  namespace: argocd
spec:
  project: youtube-mcp
  source:
    repoURL: git@github.com:pablitxn/youtube-mcp.git
    targetRevision: main
    path: infrastructure/overlays/prod
  destination:
    server: https://kubernetes.default.svc
    namespace: youtube-mcp-prod
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

## Deployment Workflow

### CI/CD Pipeline

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Push to       │───▶│   CI Pipeline   │───▶│   Build &       │
│   main/dev      │    │   (Lint/Test)   │    │   Push Image    │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                                                      │
                                                      ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Kubernetes    │◀───│   ArgoCD        │◀───│   Update        │
│   Deployment    │    │   Sync          │    │   Image Digest  │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

### Image Digest Updates

The CI pipeline updates image digests in the `infrastructure/overlays/` directory:

```yaml
# youtube_mcp/infrastructure/overlays/prod/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
images:
  - name: ghcr.io/pablitxn/youtube-mcp
    newName: ghcr.io/pablitxn/youtube-mcp
    digest: sha256:8b40939362651c9c17fbaa2afd12b98e696236b35a74a9929226f49c5d443928
```

### Deployment Triggers

| Branch | Environment | Trigger |
|--------|-------------|---------|
| `dev` | Development | Push to `dev` branch |
| `main` | Production | Push to `main` branch |

## Sync Policies

### Automated Sync

Both environments use automated sync with:

- **Prune**: Remove resources not in Git
- **Self-Heal**: Revert manual changes
- **CreateNamespace**: Auto-create namespace if missing

### Sync Options

```yaml
syncOptions:
  - CreateNamespace=true
  - PrunePropagationPolicy=foreground
  - PruneLast=true
```

## Manual Operations

### Check Application Status

```bash
# List all applications
argocd app list

# Get application details
argocd app get youtube-mcp-prod

# Get sync status
argocd app get youtube-mcp-prod -o yaml | grep -A5 status
```

### Force Sync

```bash
# Sync application
argocd app sync youtube-mcp-prod

# Sync with prune
argocd app sync youtube-mcp-prod --prune
```

### Rollback

```bash
# Rollback to previous version
argocd app rollback youtube-mcp-prod

# Rollback to specific revision
argocd app rollback youtube-mcp-prod --revision 5

# View history
argocd app history youtube-mcp-prod
```

### Refresh

```bash
# Refresh application (check for changes)
argocd app get youtube-mcp-prod --refresh

# Hard refresh (clear cache)
argocd app get youtube-mcp-prod --hard-refresh
```

## Repository Structure

### Application Repository (youtube_mcp)

```
youtube_mcp/
├── infrastructure/
│   └── overlays/
│       ├── dev/
│       │   └── kustomization.yaml    # Image tag for dev
│       └── prod/
│           └── kustomization.yaml    # Image digest for prod
├── src/                              # Application source code
├── Dockerfile                        # Container build definition
└── .github/
    └── workflows/
        └── ci.yml                    # CI/CD pipeline
```

### Infrastructure Repository (infrastructure)

```
playground-infrastructure/
└── hostinger/
    ├── argocd-apps/
    │   └── youtube-mcp/
    │       ├── project.yaml          # ArgoCD Project
    │       ├── youtube-mcp-dev.yaml  # Dev Application
    │       └── youtube-mcp-prod.yaml # Prod Application
    └── applications/
        └── youtube-mcp/
            ├── base/                 # Base Kustomize manifests
            │   ├── kustomization.yaml
            │   ├── deployment.yaml
            │   ├── service.yaml
            │   ├── config-map.yaml
            │   └── network-policies.yaml
            └── overlays/
                ├── dev/              # Dev-specific patches
                └── prod/             # Prod-specific patches
```

## Notifications

ArgoCD can send notifications on sync events. Configure in:

```yaml
# argocd-notifications-cm ConfigMap
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-notifications-cm
data:
  trigger.on-sync-succeeded: |
    - when: app.status.sync.status == 'Synced'
      send: [slack-message]
  template.slack-message: |
    message: |
      Application {{.app.metadata.name}} sync succeeded!
```

## Troubleshooting

### Application Out of Sync

```bash
# Check diff
argocd app diff youtube-mcp-prod

# Force sync
argocd app sync youtube-mcp-prod --force
```

### Sync Failed

```bash
# View sync operation details
argocd app get youtube-mcp-prod

# Check events
kubectl get events -n youtube-mcp-prod --sort-by=.lastTimestamp
```
