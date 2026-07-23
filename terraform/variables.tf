# variables.tf - Input variables for SnapChef Terraform config
# =============================================================
# Values are set in terraform.tfvars (gitignored)
# Defaults are safe values that work for most cases

variable "subscription_id" {
  description = "Azure subscription ID — get from: az account show --query id"
  type        = string
}

variable "resource_group_name" {
  description = "Name of the Azure resource group"
  type        = string
  default     = "snapchef-rg"
}

variable "location" {
  description = "Azure region to deploy to"
  type        = string
  default     = "eastus"
  # Other options: "westeurope", "australiaeast", "southeastasia"
}

variable "prefix" {
  description = "Prefix for all resource names — keeps names unique and grouped"
  type        = string
  default     = "snapchef"
}

variable "acr_name" {
  description = "Azure Container Registry name — must be globally unique, alphanumeric only, 5-50 chars"
  type        = string
  # Set this in terraform.tfvars to something like "snapchefacr<yourname>"
}

variable "environment" {
  description = "Environment tag — dev, staging, or prod"
  type        = string
  default     = "prod"
}

variable "openai_api_key" {
  description = "OpenAI API key — injected as env var into the container"
  type        = string
  sensitive   = true  # marked sensitive so Terraform never prints it in logs
}

variable "pinecone_api_key" {
  description = "Pinecone API key"
  type        = string
  sensitive   = true
}