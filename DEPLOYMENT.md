# Deployment Guide

This document outlines the steps required to deploy the TIFF to COG conversion service using GitHub Actions.

## Required GitHub Secrets

You need to configure the following **secrets** in your GitHub repository:

### 1. `AWS_ROLE_ARN`

- **Purpose**: AWS IAM role ARN for GitHub Actions to assume for ECR access
- **Format**: `arn:aws:iam::ACCOUNT-ID:role/ROLE-NAME`
- **Example**: `arn:aws:iam::123456789012:role/GitHubActions-ECR-Role`

### 2. `EODH_TOKEN`

- **Purpose**: Bearer token for authenticating with the EODH API
- **Format**: API token string
- **Usage**: Used in the Authorization header when deploying to EODH

## Required GitHub Variables

You need to configure the following **variables** in your GitHub repository:

### 1. `AWS_ECR_REGISTRY`

- **Purpose**: Full ECR registry URL where Docker images will be pushed
- **Format**: `public.ecr.aws/ACCOUNT-ID/REPOSITORY-NAME`
- **Example**: `public.ecr.aws/123456789012/tiff-to-cog`

## AWS Setup Requirements

### 1. ECR Public Repository

- Create a public ECR repository in AWS
- Repository name should match your project (e.g., `tiff-to-cog`)

### 2. IAM Role for GitHub Actions

Create an IAM role with the following:

- **Trust Policy**: Allow GitHub Actions to assume the role
- **Permissions**:
  - "sts:GetServiceBearerToken"
  - "ecr-public:GetAuthorizationToken"
  - "ecr-public:BatchCheckLayerAvailability"
  - "ecr-public:InitiateLayerUpload"
  - "ecr-public:UploadLayerPart"
  - "ecr-public:CompleteLayerUpload"
  - "ecr-public:PutImage"

### 3. GitHub OIDC Provider (if using OIDC)

- Set up GitHub as an OIDC provider in AWS
- Configure the trust relationship to allow your repository

## EODH API Setup

### 1. EODH Account

- Obtain an API token from EODH (eodatahub.org.uk)
- Ensure you have permissions to deploy to the workspace you wish to deploy to

## Deployment Steps Summary

1. **Set up AWS**:
   - Create ECR public repository
   - Create IAM role with ECR permissions
   - Configure GitHub OIDC provider (if using OIDC)

2. **Configure GitHub**:
   - Add `AWS_ROLE_ARN` secret
   - Add `EODH_TOKEN` secret  
   - Add `AWS_ECR_REGISTRY` variable

3. **Deploy**:
   - Push to `develop` or `main` branch
   - Or manually trigger via `workflow_dispatch`

## How It Works

The GitHub Actions workflow performs the following steps:

1. **Build and Push Job**:
   - Checks out the code
   - Configures AWS credentials using the IAM role
   - Logs into Amazon ECR Public
   - Builds the Docker image using the Dockerfile in `src/`
   - Pushes the image to the ECR registry with appropriate tags

2. **Deploy to EODH Job**:
   - Takes the built image URI from the first job
   - Updates the CWL file with the actual image URI
   - Deploys the CWL workflow to the EODH API
   - Verifies successful deployment (expects HTTP 204 status)

The workflow automatically triggers on pushes to `develop` or `main` branches, or can be manually triggered through the GitHub Actions interface.
