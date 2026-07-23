# outputs.tf - Values printed after terraform apply
# ===================================================
# These are the URLs and names you need after deployment

output "resource_group_name" {
  description = "Name of the created resource group"
  value       = azurerm_resource_group.snapchef.name
}

output "acr_login_server" {
  description = "ACR login server — used when pushing Docker images"
  value       = azurerm_container_registry.snapchef.login_server
}

output "acr_username" {
  description = "ACR admin username — used for docker login"
  value       = azurerm_container_registry.snapchef.admin_username
}

output "api_url" {
  description = "Public URL of the FastAPI backend — set this as BACKEND_URL in Streamlit Cloud"
  value       = "https://${azurerm_container_app.snapchef_api.ingress[0].fqdn}"
}

output "api_health_check" {
  description = "Health check URL — open this in browser to verify deployment"
  value       = "https://${azurerm_container_app.snapchef_api.ingress[0].fqdn}/health"
}

output "api_docs_url" {
  description = "FastAPI auto-generated docs — open this to test endpoints"
  value       = "https://${azurerm_container_app.snapchef_api.ingress[0].fqdn}/docs"
}
