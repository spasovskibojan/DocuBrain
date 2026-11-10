#!/bin/bash
# Deploys DocuBrain to the cluster kubectl is currently connected to.

set -e

echo "Deploying DocuBrain to Kubernetes..."

kubectl apply -f k8s/00-namespace.yaml
echo "Namespace created"

kubectl apply -f k8s/01-secrets.yaml
echo "Secrets applied"

kubectl apply -f k8s/02-configmap.yaml
echo "ConfigMaps applied"

kubectl apply -f k8s/03-statefulsets.yaml
echo "StatefulSets created (databases)"

echo "Waiting for databases to be ready..."
kubectl rollout status statefulset/postgres -n docubrain --timeout=120s
kubectl rollout status statefulset/qdrant -n docubrain --timeout=120s
kubectl rollout status statefulset/redis -n docubrain --timeout=120s

kubectl apply -f k8s/04-deployments.yaml
echo "Deployments created (backend + frontend)"

kubectl apply -f k8s/05-services.yaml
echo "Services created"

kubectl apply -f k8s/06-ingress.yaml
echo "Ingress created"

echo ""
echo "DocuBrain deployed."
echo ""
echo "Cluster status:"
kubectl get all -n docubrain
echo ""
echo "Ingress rules:"
kubectl get ingress -n docubrain
