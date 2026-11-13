# Deletes the k3d cluster. The data stays in the docubrain_portfolio_k8s_data Docker volume;
# wipe it with: docker volume rm docubrain_portfolio_k8s_data

$ClusterName = "docubrain-portfolio"

Write-Host "Deleting the cluster..." -ForegroundColor Cyan
k3d cluster delete $ClusterName

Write-Host "Done. Everything is stopped." -ForegroundColor Green
