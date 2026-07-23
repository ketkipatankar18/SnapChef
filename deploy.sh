#!/bin/bash
# deploy.sh - SnapChef Deployment Script
# ========================================
# Runs the full deployment in order:
#   1. Terraform provisions Azure infrastructure
#   2. Docker builds the FastAPI backend image
#   3. Image pushed to Azure Container Registry
#   4. Container App pulls and runs the new image
#
# Usage:
#   chmod +x deploy.sh
#   ./deploy.sh

set -e  # exit immediately if any command fails

echo "=================================================="
echo "SnapChef Deployment"
echo "=================================================="

# ── Step 1: Terraform ─────────────────────────────────
echo ""
echo "Step 1: Provisioning Azure infrastructure with Terraform..."
cd terraform

# Download providers (only needed first time)
terraform init

# Show what will be created — review before applying
terraform plan

# Ask for confirmation before creating resources
read -p "Apply Terraform changes? (yes/no): " confirm
if [ "$confirm" != "yes" ]; then
    echo "Deployment cancelled."
    exit 0
fi

# Create all Azure resources
terraform apply -auto-approve

# Get the ACR login server from Terraform output
ACR_SERVER=$(terraform output -raw acr_login_server)
ACR_USERNAME=$(terraform output -raw acr_username)

echo ""
echo "✓ Infrastructure provisioned"
echo "  ACR: $ACR_SERVER"

cd ..

# ── Step 2: Build Docker image ────────────────────────
echo ""
echo "Step 2: Building FastAPI Docker image..."
docker build -t snapchef-api:latest -f Dockerfile .
echo "✓ Docker image built"

# ── Step 3: Push to ACR ───────────────────────────────
echo ""
echo "Step 3: Pushing image to Azure Container Registry..."

# Login to ACR using Azure CLI
az acr login --name $ACR_USERNAME

# Tag image for ACR
docker tag snapchef-api:latest $ACR_SERVER/snapchef-api:latest

# Push
docker push $ACR_SERVER/snapchef-api:latest
echo "✓ Image pushed to ACR"

# ── Step 4: Restart Container App ────────────────────
echo ""
echo "Step 4: Restarting Container App to pull new image..."
az containerapp update \
    --name snapchef-api \
    --resource-group snapchef-rg \
    --image $ACR_SERVER/snapchef-api:latest

echo ""
echo "=================================================="
echo "Deployment Complete!"
echo "=================================================="

# Print the URLs
cd terraform
echo ""
echo "Your API URLs:"
terraform output api_url
terraform output api_health_check
terraform output api_docs_url
echo ""
echo "Next step: Set BACKEND_URL in Streamlit Cloud secrets to the api_url above"
