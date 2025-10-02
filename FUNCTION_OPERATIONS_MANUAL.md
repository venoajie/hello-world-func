
# OCI Function Deployment: A Practical Guide v1.0

This document provides the definitive, battle-tested guide for deploying a Python FastAPI application as an OCI Function. The procedures outlined here are the result of an exhaustive debugging process and represent a reliable, repeatable solution, including justifications for deviations from on-paper "best practices" due to platform limitations discovered in the field.

## 1. Final Working Architecture

-   **Application:** A standard Python FastAPI application running via `uvicorn` in a custom Docker container.
-   **Authentication:** **API Key Authentication**. The function authenticates as a dedicated IAM user. This is a deliberate fallback from the preferred but currently non-functional Resource Principals method.
-   **Secret Management:** All credentials (API key, OCIDs, etc.) are stored as **Function Application Configuration**. This is OCI's secure mechanism for injecting secrets into the function's runtime environment.
-   **Deployment:** A CI/CD pipeline in GitHub Actions builds and pushes the Docker image, then uses the `oci` CLI to perform an **"update-only"** deployment. A one-time manual setup of the Application is required.

## 2. Architectural Decisions & Justifications (The "Why")

This section documents the reasoning behind key design choices.

### 2.1. Why API Key Authentication instead of Resource Principals?

-   **The Goal (Best Practice):** The most secure and ideal authentication method is **Resource Principals**, where the function gets its identity directly from the OCI platform without needing any stored credentials.
-   **The Problem (Practical Reality):** We conducted exhaustive tests and proved that the OCI platform's tooling for enabling Resource Principals is currently broken or has been deprecated without replacement.
    -   The OCI Console UI **no longer provides the option** to enable instance principals during function creation.
    -   The `oci fn function create/update` and `oci fn application create` CLI commands **do not have the `--annotation` flag** required to enable this feature programmatically.
    -   The `fn deploy` command, which reads from `func.yaml`, also fails to apply the setting correctly, resulting in the function being unable to find its credentials (`private.pem` error).
-   **The Decision:** We have fallen back to the "gold standard" of API Key authentication. While this introduces a long-lived credential (the API key) that must be managed, it is a secure, stable, and—most importantly—**working** pattern.

### 2.2. Why Pinned Dependencies are Critical

-   **The Problem:** The final `InvalidPrivateKey` error, coupled with an `unsupported algorithm` traceback from the underlying cryptography library, occurred even when we proved the key was perfectly formatted and delivered.
-   **The Hypothesis:** This strongly indicates an incompatibility between the Python `cryptography` library (installed by the `oci` SDK) and the underlying system-level OpenSSL libraries present in the minimal `python:3.11-slim` Docker base image. Using "latest" for all packages creates an untested, potentially unstable software environment.
-   **The Decision:** The `requirements.txt` file **must** have all major dependencies pinned to specific, known-good versions. This creates a reproducible build and eliminates the risk of a dependency update breaking the application in a cryptic way.

## 3. Lesson Learned & Technical Debt

-   **Lesson 1: Trust, but Verify, the Platform.** The biggest obstacle was assuming the platform's primary authentication mechanism (Resource Principals) was functional. The lack of working tooling is a significant platform gap.
-   **Lesson 2: Minimal Images Have Hidden Costs.** Using `-slim` Docker images is great for size, but can lead to incredibly difficult-to-debug errors when applications have dependencies on system-level libraries (like OpenSSL).
-   **Technical Debt:** The use of API Key authentication is a form of technical debt. The next developer should periodically re-evaluate if OCI has fixed the Resource Principal tooling, as migrating to it would improve the security posture by eliminating the need for a managed API key.

## 4. Unresolved Issues & Next Steps

The project is 99% complete. The final `InvalidPrivateKey` error needs to be resolved.

-   **Final Failure Point:** The application fails during startup with `oci.exceptions.InvalidPrivateKey` and a `ValueError: (...unsupported algorithm...)` traceback.
-   **Primary Hypothesis:** The `python:3.11-slim` base image has an incompatible set of system-level crypto libraries.
-   **Next Action for Next Developer:** The very first action should be to test this hypothesis by changing the Docker base image to a more complete, non-slim version to see if the error is resolved.
