# main.tf - SnapChef Azure Infrastructure
# =========================================
# Provisions:
#   - Resource Group          : logical container for all resources
#   - Azure Container Registry: stores our Docker images
#   - Log Analytics Workspace : collects logs from Container Apps
#   - Container Apps Environment: runtime environment for Container Apps
#   - Container App           : runs our FastAPI backend

terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
  }
  required_version = ">= 1.0"
}

# Azure provider — authenticates via az login
provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

# ── Resource Group ────────────────────────────────────────────────────────────
# Logical container — deleting this deletes everything inside it
resource "azurerm_resource_group" "snapchef" {
  name     = var.resource_group_name
  location = var.location

  tags = {
    project     = "snapchef"
    environment = var.environment
    managed_by  = "terraform"
  }
}

# ── Azure Container Registry (ACR) ───────────────────────────────────────────
# Stores our Docker images — like DockerHub but private on Azure
# FastAPI backend image gets pushed here before deployment
resource "azurerm_container_registry" "snapchef" {
  name                = var.acr_name
  resource_group_name = azurerm_resource_group.snapchef.name
  location            = azurerm_resource_group.snapchef.location
  sku                 = "Basic"
  admin_enabled       = true

  tags = {
    project = "snapchef"
  }
}

# ── Log Analytics Workspace ───────────────────────────────────────────────────
# Collects logs from Container Apps
# Used by Azure Monitor to store and query logs
resource "azurerm_log_analytics_workspace" "snapchef" {
  name                = "${var.prefix}-logs"
  resource_group_name = azurerm_resource_group.snapchef.name
  location            = azurerm_resource_group.snapchef.location
  sku                 = "PerGB2018"
  retention_in_days   = 30

  tags = {
    project = "snapchef"
  }
}

# ── Container Apps Environment ────────────────────────────────────────────────
# Runtime environment that Container Apps run inside
# All apps in one environment share networking
resource "azurerm_container_app_environment" "snapchef" {
  name                       = "${var.prefix}-env"
  resource_group_name        = azurerm_resource_group.snapchef.name
  location                   = azurerm_resource_group.snapchef.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.snapchef.id

  tags = {
    project = "snapchef"
  }
}

# ── Container App — FastAPI Backend ──────────────────────────────────────────
# Running instance of our FastAPI app
# Pulls image from ACR, exposes port 8000, scales to 0 when idle
resource "azurerm_container_app" "snapchef_api" {
  name                         = "${var.prefix}-api"
  container_app_environment_id = azurerm_container_app_environment.snapchef.id
  resource_group_name          = azurerm_resource_group.snapchef.name
  revision_mode                = "Single"

  registry {
    server               = azurerm_container_registry.snapchef.login_server
    username             = azurerm_container_registry.snapchef.admin_username
    password_secret_name = "acr-password"
  }

  secret {
    name  = "acr-password"
    value = azurerm_container_registry.snapchef.admin_password
  }

  template {
    container {
      name   = "snapchef-api"
      image  = "${azurerm_container_registry.snapchef.login_server}/snapchef-api:latest"
      cpu    = 1.0
      memory = "2Gi"

      env {
        name  = "OPEN_AI_API_KEY"
        value = var.openai_api_key
      }

      env {
        name  = "PINECONE_API_KEY"
        value = var.pinecone_api_key
      }

      # Maps to @app.get("/health") in FastAPI app.py
      startup_probe {
        path                    = "/health"
        port                    = 8000
        transport               = "HTTP"
        interval_seconds        = 30
        timeout                 = 10
        failure_count_threshold = 10
      }

      liveness_probe {
        path              = "/health"
        port              = 8000
        transport         = "HTTP"
        interval_seconds  = 30
        timeout           = 10
        failure_count_threshold = 3
      }

      readiness_probe {
        path              = "/health"
        port              = 8000
        transport         = "HTTP"
        interval_seconds  = 10
        timeout           = 5
        failure_count_threshold = 3
      }
    }

    # Scale to 0 when idle — no traffic = no cost
    min_replicas = 1
    max_replicas = 3
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    transport        = "http"

    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  tags = {
    project = "snapchef"
  }
}
