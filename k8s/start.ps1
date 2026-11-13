# Builds the images and runs DocuBrain on a local k3d cluster. Stop with .\k8s\stop.ps1
# Needs Docker Desktop, k3d and kubectl. API keys are read from .env.

$ClusterName = "docubrain-portfolio"
$Namespace = "docubrain"
$BackendImage = "docubrain-portfolio-backend:k8s"
$FrontendImage = "docubrain-portfolio-frontend:k8s"
# Same tags as 03-statefulsets.yaml. Importing them from the host avoids a slow pull inside every new cluster.
$DatabaseImages = @("postgres:16-alpine", "qdrant/qdrant:v1.18.0", "redis:7-alpine")
$AppUrl = "http://localhost:8080"

function Assert-Ok($step) {
    if ($LASTEXITCODE -ne 0) { Write-Host "FAILED: $step" -ForegroundColor Red; exit 1 }
}

function Wait-Rollout($resource, $timeout) {
    kubectl rollout status $resource -n $Namespace --timeout=$timeout
    Assert-Ok "$resource rollout"
}

# "rollout status" on a new StatefulSet returns once the pod exists, not when it is ready
function Wait-StatefulSet($name) {
    kubectl wait statefulset/$name -n $Namespace --for=jsonpath='{.status.readyReplicas}'=1 --timeout=180s
    Assert-Ok "$name ready"
}

Set-Location (Split-Path $PSScriptRoot -Parent)

Write-Host "[1/7] Building the app images and pulling the database images..." -ForegroundColor Cyan
docker build -t $BackendImage backend
Assert-Ok "backend image build"
docker build -t $FrontendImage frontend
Assert-Ok "frontend image build"
foreach ($image in $DatabaseImages) {
    docker image inspect $image *> $null
    if ($LASTEXITCODE -ne 0) {
        docker pull $image
        Assert-Ok "pull $image"
    }
}

Write-Host "[2/7] Recreating a clean cluster..." -ForegroundColor Cyan
k3d cluster delete $ClusterName
# The databases live in a Docker volume, so they survive deleting the cluster.
# Host port 8080 is mapped to the ingress controller.
k3d cluster create $ClusterName --api-port "127.0.0.1:6446" --port "8080:80@loadbalancer" --volume "docubrain_portfolio_k8s_data:/var/lib/docubrain@server:0" --wait
Assert-Ok "k3d cluster create"

Write-Host "[3/7] Waiting for the API server..." -ForegroundColor Cyan
for ($i = 0; $i -lt 30; $i++) {
    kubectl get nodes *> $null
    if ($LASTEXITCODE -eq 0) { break }
    Start-Sleep -Seconds 2
}
kubectl get nodes
Assert-Ok "kubectl get nodes"

Write-Host "[4/7] Importing the images into the cluster (~1 min)..." -ForegroundColor Cyan
# Not "k3d image import": it fails on multi-platform images from Docker Hub and still reports success.
$platform = docker version --format "{{.Server.Os}}/{{.Server.Arch}}"
$imagesTar = Join-Path $env:TEMP "docubrain-images.tar"
docker save --platform $platform -o $imagesTar $BackendImage $FrontendImage @DatabaseImages
Assert-Ok "docker save"
$node = "k3d-$ClusterName-server-0"
docker cp $imagesTar "${node}:/tmp/images.tar"
Assert-Ok "copy images to the node"
Remove-Item $imagesTar
docker exec $node ctr -n k8s.io images import /tmp/images.tar
Assert-Ok "image import"
docker exec $node rm /tmp/images.tar

Write-Host "[5/7] Namespace, Secret, ConfigMap and databases..." -ForegroundColor Cyan
kubectl apply -f k8s/00-namespace.yaml
kubectl apply -f k8s/01-secrets.yaml
kubectl apply -f k8s/02-configmap.yaml
Assert-Ok "kubectl apply"

# The committed Secret only holds placeholders; the real keys stay in .env
$secretKeys = @{
    GROQ_API_KEY        = "groq-api-key"
    SECRET_KEY          = "secret-key"
    LANGFUSE_PUBLIC_KEY = "langfuse-public-key"
    LANGFUSE_SECRET_KEY = "langfuse-secret-key"
}
$secrets = @{}
foreach ($line in Get-Content .env -ErrorAction SilentlyContinue) {
    if ($line -match '^\s*(\w+)\s*=(.*)$' -and $secretKeys.ContainsKey($Matches[1])) {
        $value = $Matches[2].Trim().Trim('"').Trim("'")
        if ($value) { $secrets[$secretKeys[$Matches[1]]] = $value }
    }
}
if ($secrets.Count -gt 0) {
    $patchFile = Join-Path $env:TEMP "docubrain-secret-patch.json"
    @{ stringData = $secrets } | ConvertTo-Json -Compress | Set-Content -Path $patchFile -Encoding ascii
    kubectl patch secret docubrain-secrets -n $Namespace --type merge --patch-file $patchFile
    Remove-Item $patchFile
    Assert-Ok "kubectl patch secret"
}
if (-not $secrets.ContainsKey("groq-api-key")) {
    Write-Host "GROQ_API_KEY not found in .env - AI features will not work." -ForegroundColor Yellow
}

kubectl apply -f k8s/03-statefulsets.yaml
Wait-StatefulSet postgres
Wait-StatefulSet qdrant
Wait-StatefulSet redis

Write-Host "[6/7] Backend, frontend, services and ingress..." -ForegroundColor Cyan
kubectl apply -f k8s/04-deployments.yaml
kubectl apply -f k8s/05-services.yaml
kubectl apply -f k8s/06-ingress.yaml
Wait-Rollout deployment/backend 300s
Wait-Rollout deployment/frontend 180s

Write-Host "[7/7] Waiting for the ingress controller..." -ForegroundColor Cyan
# k3s installs Traefik itself and pulls its image in every new cluster, which can take minutes.
for ($i = 0; $i -lt 60; $i++) {
    kubectl get deployment traefik -n kube-system *> $null
    if ($LASTEXITCODE -eq 0) { break }
    Start-Sleep -Seconds 5
}
kubectl rollout status deployment/traefik -n kube-system --timeout=600s
Assert-Ok "traefik rollout"
$ready = $false
for ($i = 0; $i -lt 60 -and -not $ready; $i++) {
    try {
        $ready = (Invoke-WebRequest "$AppUrl/api/health" -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200
    } catch {
        Start-Sleep -Seconds 2
    }
}
if (-not $ready) { Write-Host "FAILED: $AppUrl did not respond" -ForegroundColor Red; exit 1 }

kubectl get all -n $Namespace
Write-Host ""
Write-Host "DocuBrain is running on Kubernetes: $AppUrl" -ForegroundColor Green
Write-Host "To stop: .\k8s\stop.ps1" -ForegroundColor Yellow
Start-Process $AppUrl
