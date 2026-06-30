#!/usr/bin/env bash
# Bootstrap GitHub Actions OIDC federated credentials for Azure deployment.
# Usage:
#   ./setup-github-oidc.sh \
#     --subscription SUB_ID \
#     --resource-group RG_NAME \
#     --github-org YOUR_ORG \
#     --github-repo Trending_Posts_Content_Generation \
#     --api-app content-intelligence-api-SUFFIX \
#     --web-app content-intelligence-web-SUFFIX

set -euo pipefail

SUBSCRIPTION=""
RESOURCE_GROUP=""
GITHUB_ORG=""
GITHUB_REPO=""
API_APP=""
WEB_APP=""
APP_NAME="github-actions-content-intelligence"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --subscription) SUBSCRIPTION="$2"; shift 2 ;;
    --resource-group) RESOURCE_GROUP="$2"; shift 2 ;;
    --github-org) GITHUB_ORG="$2"; shift 2 ;;
    --github-repo) GITHUB_REPO="$2"; shift 2 ;;
    --api-app) API_APP="$2"; shift 2 ;;
    --web-app) WEB_APP="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

for v in SUBSCRIPTION RESOURCE_GROUP GITHUB_ORG GITHUB_REPO API_APP WEB_APP; do
  if [[ -z "${!v}" ]]; then
    echo "Missing required argument for: $v" >&2
    exit 1
  fi
done

az account set --subscription "$SUBSCRIPTION"

APP_ID=$(az ad app create --display-name "$APP_NAME" --query appId -o tsv)
OBJECT_ID=$(az ad app show --id "$APP_ID" --query id -o tsv)

az ad sp create --id "$APP_ID" >/dev/null
SP_OBJECT_ID=$(az ad sp show --id "$APP_ID" --query id -o tsv)

az ad app federated-credential create \
  --id "$OBJECT_ID" \
  --parameters "{
    \"name\": \"github-main\",
    \"issuer\": \"https://token.actions.githubusercontent.com\",
    \"subject\": \"repo:${GITHUB_ORG}/${GITHUB_REPO}:ref:refs/heads/main\",
    \"audiences\": [\"api://AzureADTokenExchange\"]
  }" >/dev/null

SCOPE="/subscriptions/${SUBSCRIPTION}/resourceGroups/${RESOURCE_GROUP}"
az role assignment create \
  --assignee "$SP_OBJECT_ID" \
  --role "Website Contributor" \
  --scope "$SCOPE" >/dev/null

echo ""
echo "=== GitHub Actions secrets (Settings → Secrets and variables → Actions) ==="
echo "AZURE_CLIENT_ID=$APP_ID"
echo "AZURE_TENANT_ID=$(az account show --query tenantId -o tsv)"
echo "AZURE_SUBSCRIPTION_ID=$SUBSCRIPTION"
echo ""
echo "=== GitHub Actions variables ==="
echo "AZURE_API_WEBAPP_NAME=$API_APP"
echo "AZURE_WEB_WEBAPP_NAME=$WEB_APP"
echo "VITE_API_BASE_URL=https://${API_APP}.azurewebsites.net/api"
echo ""
echo "Grant the API managed identity Key Vault Secrets User on your vault after Bicep deploy."
