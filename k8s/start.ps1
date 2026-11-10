# Builds the images and runs DocuBrain on a local k3d cluster. Stop with .\k8s\stop.ps1
# Needs Docker Desktop, k3d and kubectl. The Groq key is read from .env.

$ClusterName = "docubrain"
$Namespace = "docubrain"

function Assert-Ok($step) {
    if ($LASTEXITCODE -ne 0) { Write-Host "FAILED: $step" -ForegroundColor Red; exit 1 }
}

Set-Location (Split-Path $PSScriptRoot -Parent)

Write-Host "[1/7] Building docubrain-backend and docubrain-frontend images..." -ForegroundColor Cyan
# Ports 8000/5173 are needed for the port-forwards, so the compose stack has to be stopped
if (docker ps -q --filter "name=docubrain_backend") {
    docker compose stop
}
docker compose build backend frontend
Assert-Ok "docker compose build"

Write-Host "[2/7] Recreating a clean cluster..." -ForegroundColor Cyan
k3d cluster delete $ClusterName
# The databases live in a Docker volume, so they survive deleting the cluster
k3d cluster create $ClusterName --api-port "127.0.0.1:6445" --volume "docubrain_k8s_data:/var/lib/docubrain@server:0" --wait
Assert-Ok "k3d cluster create"

Write-Host "[3/7] Waiting for the API server..." -ForegroundColor Cyan
for ($i = 0; $i -lt 30; $i++) {
    kubectl get nodes *> $null
    if ($LASTEXITCODE -eq 0) { break }
    Start-Sleep -Seconds 2
}
kubectl get nodes
Assert-Ok "kubectl get nodes"

Write-Host "[4/7] Importing local images into the cluster (~1 min)..." -ForegroundColor Cyan
k3d image import docubrain-backend:latest docubrain-frontend:latest -c $ClusterName
Assert-Ok "k3d image import"

Write-Host "[5/7] Namespace, Secret, ConfigMap and databases..." -ForegroundColor Cyan
kubectl apply -f k8s/00-namespace.yaml
kubectl apply -f k8s/01-secrets.yaml
kubectl apply -f k8s/02-configmap.yaml
Assert-Ok "kubectl apply"

# The committed Secret only holds a placeholder Groq key; the real one stays in .env
$groqLine = Get-Content .env -ErrorAction SilentlyContinue | Where-Object { $_ -match '^\s*GROQ_API_KEY\s*=' } | Select-Object -First 1
$groqKey = if ($groqLine) { ($groqLine -split '=', 2)[1].Trim().Trim('"').Trim("'") } else { "" }
if ($groqKey) {
    $patchFile = Join-Path $env:TEMP "docubrain-groq-patch.json"
    @{ stringData = @{ "groq-api-key" = $groqKey } } | ConvertTo-Json -Compress | Set-Content -Path $patchFile -Encoding ascii
    kubectl patch secret docubrain-secrets -n $Namespace --type merge --patch-file $patchFile
    Remove-Item $patchFile
    Assert-Ok "kubectl patch secret"
} else {
    Write-Host "GROQ_API_KEY not found in .env - AI features will not work." -ForegroundColor Yellow
}

kubectl apply -f k8s/03-statefulsets.yaml
kubectl rollout status statefulset/postgres -n $Namespace --timeout=180s
kubectl rollout status statefulset/qdrant   -n $Namespace --timeout=180s
kubectl rollout status statefulset/redis    -n $Namespace --timeout=180s
Assert-Ok "databases rollout"

Write-Host "[6/7] Backend, frontend, services and ingress..." -ForegroundColor Cyan
kubectl apply -f k8s/04-deployments.yaml
kubectl apply -f k8s/05-services.yaml
kubectl apply -f k8s/06-ingress.yaml
kubectl rollout status deployment/backend  -n $Namespace --timeout=300s
kubectl rollout status deployment/frontend -n $Namespace --timeout=180s
Assert-Ok "app rollout"

Write-Host "[7/7] Opening access to the app..." -ForegroundColor Cyan
# The frontend calls http://localhost:8000/api from the browser, so both services are port-forwarded
Start-Process powershell -ArgumentList '-NoExit','-Command',
  'Write-Host "BACKEND  -> http://localhost:8000  (keep this window open)" -ForegroundColor Green; kubectl port-forward -n docubrain svc/backend-service 8000:8000'
Start-Process powershell -ArgumentList '-NoExit','-Command',
  'Write-Host "FRONTEND -> http://localhost:5173  (keep this window open)" -ForegroundColor Green; kubectl port-forward -n docubrain svc/frontend-service 5173:80'

Start-Sleep -Seconds 3
Start-Process "http://localhost:5173"

Write-Host ""
Write-Host "DocuBrain is running on Kubernetes: http://localhost:5173" -ForegroundColor Green
kubectl get all -n $Namespace
Write-Host ""
Write-Host "Leave the two port-forward windows open. To stop: .\k8s\stop.ps1" -ForegroundColor Yellow
