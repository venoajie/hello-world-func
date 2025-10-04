
# OCI Function Deployment: A Practical Guide for Python FastAPI

This document provides a definitive, battle-tested guide for deploying a Python FastAPI application as an OCI Function. This guide implements security best practices, including the Principle of Least Privilege for all IAM and Network configurations.

For a deeper dive into the architectural decisions, please consult the `FUNCTION_OPERATIONS_MANUAL.md`.

## 1. Architecture Overview

### 1.1. Application Architecture
-   **Application:** A standard Python FastAPI application in a custom Docker container.
-   **Authentication:** **API Key Authentication** via a dedicated, non-privileged IAM user.
-   **Secret Management:** Credentials stored as **Function Application Configuration**.
-   **Deployment:** A CI/CD pipeline (e.g., GitHub Actions).

### 1.2. Network Architecture
The function is deployed with a security-first, zero-trust network posture:
-   **Private Subnet:** The function runs in a private subnet with no public IP address.
-   **Service Gateway:** Outbound traffic to OCI services (like Object Storage) is routed through a Service Gateway over Oracle's private network.
-   **Network Security Group (NSG):** A stateful firewall is attached to the function, restricting all traffic to only what is explicitly required for operation.

## 2. Prerequisites

### 2.1. Tools
-   OCI CLI, Docker.

### 2.2. OCI Resources
-   A **VCN** with a **Private Subnet**.
-   A **Service Gateway** with a corresponding **Route Rule** in the private subnet's route table.
-   A **Network Security Group (NSG)** configured as described in Step 1 below.
-   An **Object Storage Bucket**.

## 3. Deployment Lifecycles: Provisioning vs. Updating

This project uses a two-phase deployment strategy to separate infrequent, high-risk infrastructure changes from frequent, low-risk application updates.

### Phase 1: Provisioning (Manual)
-   **Workflow:** `provision-function.yml`
-   **Trigger:** Manual, via the GitHub Actions UI.
-   **Purpose:** This workflow uses the `fn deploy` command to create or update the *entire function infrastructure* based on `func.yaml`.
-   **When to Use:**
    1.  For the very first deployment of the function.
    2.  When you make changes to `func.yaml` (e.g., increasing memory, changing the timeout, or updating network settings).

### Phase 2: Application Update (Automatic)
-   **Workflow:** `update-application.yml`
-   **Trigger:** Automatic, on every push to the `main` branch.
-   **Purpose:** This workflow uses the `oci fn function update` command to *only* update the Docker image of the function. It does not change any other settings.
-   **When to Use:** This is the standard workflow for all day-to-day development and code changes.

## 4. Step-by-Step Deployment Guide

1.  **Initial Setup:** Complete the IAM, Network, and Local CLI setup as described in the previous version.
2.  **First Deployment (Provisioning):**
    -   Navigate to the "Actions" tab in your GitHub repository.
    -   Select the "Provision Function Infrastructure (Manual)" workflow.
    -   Click "Run workflow" to perform the initial deployment.
3.  **Subsequent Deployments (Application Updates):**
    -   Commit and push your code changes to the `main` branch.
    -   The "Update Application Code" workflow will automatically run, deploying your new image.

### Step 5: Deploy and Verify
Push a change to your `main` branch to trigger the CI/CD pipeline.

## 4. Key Decisions & Troubleshooting
For a deep dive into architectural reasoning, consult the `FUNCTION_OPERATIONS_MANUAL.md`.

| Error Code / Message                                | Root Cause                                                                          | Solution                                                                                                                                              |
| --------------------------------------------------- | ----------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| **`401 NotAuthenticated` / `403 Forbidden`**        | Credentials mismatch or insufficient IAM permissions.                               | 1. Use the local `--profile` test to verify credentials. <br> 2. Ensure the hardened IAM policies from Step 1 are in place.                             |
| **`InvalidPrivateKey`**                             | Key format (PKCS#8) or newline stripping issue.                                     | 1. Generate a key using `openssl genrsa -traditional`. <br> 2. Ensure `main.py` contains the `textwrap` logic.                                      |
| **`504 Timeout`**                                   | Network issue (e.g., NSG blocking traffic) or app listening on the wrong interface. | 1. Verify NSG rules. <br> 2. Ensure `Dockerfile` CMD uses `uvicorn --uds /tmp/iofs/lsnr.sock`.                                                       |
| **`Invalid Image ... does not exist`**              | The Functions service lacks permission to pull the image from OCIR.                 | Ensure the IAM Policy `Allow service FNS to read repos in compartment ...` exists.                                                                    |
```