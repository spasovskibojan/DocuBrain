# Stops the port-forwards and deletes the k3d cluster. The data stays in the
# docubrain_k8s_data Docker volume; wipe it with: docker volume rm docubrain_k8s_data

$ClusterName = "docubrain"

Write-Host "Stopping port-forwards..." -ForegroundColor Cyan
Get-Process kubectl -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

Write-Host "Deleting the cluster..." -ForegroundColor Cyan
k3d cluster delete $ClusterName

Write-Host "Done. Everything is stopped." -ForegroundColor Green
