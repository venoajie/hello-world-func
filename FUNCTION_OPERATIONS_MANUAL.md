# OCI Function Deployment: Architect's Log & Decision Record

This document is the architectural source of truth for the OCI Function deployment pattern. It captures the critical, non-obvious design decisions and documents the platform limitations and bugs that shaped the final, working solution.

**Audience:** Cloud Architects, Senior Developers, and anyone performing deep debugging.
**Purpose:** To provide the "why" behind the architecture and prevent future developers from repeating this exhaustive debugging process.

## 1. Executive Summary

The project is **100% complete and functional**. The final architecture is stable but relies on several mandatory workarounds for platform-level issues related to authentication, configuration management, and networking. Failure to adhere to these workarounds will result in immediate and difficult-to-diagnose deployment failures.

## 2. Architectural Decisions & Justifications

### 2.1. Authentication: Why API Key (Not Resource Principals)?

-   **The Goal (Best Practice):** The most secure authentication method is **Resource Principals**, where the function gets its identity directly from the OCI platform.
-   **The Problem (Practical Reality):** The OCI platform's tooling to enable Resource Principals is currently non-functional or deprecated. The Console UI and CLI lack the required options to enable this feature.
-   **The Decision:** We have fallen back to the stable and working pattern of **API Key authentication** using a dedicated, non-privileged IAM user. This introduces a long-lived credential that must be managed but is the only reliable method at this time.
-   **Technical Debt:** This is a form of technical debt. Future work should periodically re-evaluate if OCI has fixed the Resource Principal tooling.

### 2.2. Network: Why a Private Subnet and Service Gateway?

-   **The Goal (Best Practice):** The Principle of Least Privilege. Components should not have network access they do not require.
-   **The Problem:** By default, a function could be placed in a public subnet, exposing it unnecessarily. If placed in a private subnet for security, it loses its path to other OCI services like Object Storage.
-   **The Decision:** The function is deployed into a **Private Subnet**, removing all direct internet access. To grant it a controlled path to other OCI services, a **Service Gateway** is used.
-   **Implementation Detail:** A Service Gateway is only effective when paired with a **Route Rule** in the private subnet's route table. The rule `Destination: All <Region> Services In Oracle Services Network -> Target Type: Service Gateway` is what directs traffic from the function to services like Object Storage over Oracle's private backbone network.
-   **Note on DRG:** A Dynamic Routing Gateway (DRG) is used to connect a VCN to an on-premise network or other VCNs. It is **not required** for this architecture, as the function only needs to communicate with services within OCI, which is the role of the Service Gateway.

### 2.3. Runtime Anomaly: Why the `os.environ` Workaround?

-   **The Problem:** The OCI Functions Python runtime provides a **faulty `os.environ` proxy object**. Standard access methods like `os.environ.get('KEY')` fail unpredictably for keys that are proven to exist in the environment.
-   **The Decision:** The application code **must** bypass the object's broken access methods. The only reliable operation is to capture the string representation of the entire object (`repr(os.environ)`) and parse it manually using regular expressions. **This code in `main.py` is a mandatory workaround for a platform bug.**

### 2.4. Platform Anomaly: Why the PEM Key Reformatting?

-   **The Problem 1 (SDK Requirement):** The OCI Python SDK's cryptography dependency requires private keys to be in the older **PKCS#1** format.
-   **The Problem 2 (Console Bug):** The OCI Console's configuration editor **strips all newline characters** from pasted keys, corrupting the PEM format.
-   **The Decision:** The solution is two-fold:
    1.  Keys must be generated locally using `openssl genrsa -traditional` to ensure PKCS#1 format.
    2.  The application code in `main.py` **must** contain logic using `textwrap` to programmatically reconstruct the correct multi-line PEM format from the single-line string provided by the environment.

### 2.5. Platform Integration: Why `--uds` in the Dockerfile?

-   **The Problem:** The OCI Functions platform communicates with the function container via a **Unix Domain Socket**, not a TCP port.
-   **The Decision:** The `Dockerfile`'s `CMD` instruction must explicitly bind the `uvicorn` server to this socket path (`--uds /tmp/iofs/lsnr.sock`). Attempting to bind to a port like `8080` will cause the platform's health check to fail, resulting in a `504 Timeout`.

### 2.6. Deployment: Why a Two-Phase (Provision vs. Update) Strategy?

-   **The Goal (Best Practice):** To minimize risk and increase deployment velocity by separating infrastructure configuration from application code deployment.
-   **The Problem:** A single, all-powerful deployment script (`fn deploy`) that runs on every commit is risky. An accidental change to `func.yaml` could unintentionally alter production infrastructure (like memory or network settings) when the developer only intended to push a small code fix.
-   **The Decision:** We have implemented two distinct CI/CD workflows:
    1.  **A Provisioning Workflow (`provision-function.yml`):** This uses the powerful `fn deploy` command. It is high-risk and should be run infrequently. Therefore, it is configured to be triggered **manually** via `workflow_dispatch`. This forces a deliberate, human-in-the-loop decision for any infrastructure change.
    2.  **An Application Update Workflow (`update-application.yml`):** This uses the surgical `oci fn function update --image` command. It is low-risk, as its blast radius is confined to the application code only. Therefore, it is configured to run **automatically** on every push to `main`, enabling rapid, safe, and continuous deployment of application logic.
-   **The Benefit:** This separation aligns with modern GitOps and CI/CD best practices, providing both safety for infrastructure and speed for application development.

## 3. Future Improvements & Best Practices

While the current architecture is fully functional, the following tweaks would align it more closely with best practices:

-   **Refine IAM Policy:** The `manage all-resources` policy used for debugging should be replaced with the more granular `manage objects where target.bucket.name = '...'` policy for production.
-   **Consider a NAT Gateway:** If the function ever needs to access a third-party API on the public internet (e.g., to fetch data), a NAT Gateway would need to be added to the VCN and a corresponding route rule added to the private subnet.