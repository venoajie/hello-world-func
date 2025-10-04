
# OCI Identity & Access Management (IAM): A Practical Guide

This document is the canonical guide for managing users, groups, and permissions within this OCI tenancy. Its purpose is to ensure a consistent, secure, and scalable approach to identity management for all projects.

## 1. The Core Principles of IAM

All IAM architecture in this tenancy is based on three fundamental principles:

### Principle 1: Users are Identities, Groups are Roles
-   A **User** is a single identity (a person or a service).
-   A **Group** is an abstract role or function (e.g., `Database-Admins`, `RAG-Ingestor-Deployers`).
-   **Never grant permissions directly to a User.** By adding a User to a Group, they inherit the permissions of that role. This decouples identity from permissions, which is critical for security and maintainability.

### Principle 2: Users and Groups are Global
-   Users and Groups are global entities that exist at the Tenancy (root) level. They are not "in" a compartment.

### Principle 3: Policies are Local
-   An **IAM Policy** is the bridge between a Group and a Compartment. It is attached to a compartment and defines *what* a Group is allowed to do *inside that specific compartment*.

## 2. The Three-Tier Management Model

To enforce these principles, all resources are managed within a three-tier compartment structure.

| Compartment Hierarchy              | Purpose                                                              | Resources Managed Here                                                              |
| ---------------------------------- | -------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| 📂 **`Shared-Infrastructure`**     | The stable, foundational layer of the cloud.                         | **Users** and **Groups**. Also VCNs, DRGs, Databases, etc.                          |
| 📂 **`Applications`**              | An organizational folder for all software projects.                  | Only sub-compartments.                                                              |
| └── 📂 `[Project-Name]`            | A container for a single, specific application.                      | Only sub-compartments (e.g., `Prod`, `Dev`).                                        |
| &nbsp;&nbsp;&nbsp;&nbsp;└── 📂 `[Environment-Name]` | The "blast radius" for a specific deployment environment. | **IAM Policies**, Functions, Object Storage Buckets, Container Repositories, etc. |
| 📂 **`Sandbox`**                   | An isolated lab for experiments and proofs-of-concept.               | All temporary and non-critical resources.                                           |

## 3. A Repeatable Workflow for New Projects

Follow this checklist every time a new application is created to ensure a secure and consistent setup.

### Step 1: Create the Identity and Role (in `Shared-Infrastructure`)

All identities and roles are managed centrally.

1.  Navigate to the **`Shared-Infrastructure`** compartment in the OCI Console.
2.  Go to **Identity & Security -> Users** and create a new, dedicated service user (e.g., `new-app-service-user`).
3.  Go to **Identity & Security -> Groups** and create a new, dedicated group that represents the application's role (e.g., `New-App-Executors`).
4.  **Add the new user to the new group.** This is the step that assigns the identity to the role.

### Step 2: Create the Project Space (in `Applications`)

All application resources are isolated within their own project compartment.

1.  Navigate to the **`Applications`** compartment.
2.  Create a new sub-compartment for the project (e.g., `New-App-Project`).
3.  Navigate into the new `New-App-Project` compartment.
4.  Create a sub-compartment for the environment (e.g., `New-App-Prod`).
5.  **Create all application-specific resources** (the Function Application, Object Storage Buckets, etc.) inside this final `New-App-Prod` compartment.

### Step 3: Create the Policy Bridge (in the Project Compartment)

Policies are always created as locally as possible and **always reference Groups, not Users**.

1.  Navigate to the **`Applications/New-App-Project/New-App-Prod`** compartment.
2.  Go to **Identity & Security -> Policies**.
3.  Create a new, specific IAM policy that grants the **Group** from Step 1 (`New-App-Executors`) the exact permissions it needs *only within this compartment*.

### Step 4: Generate and Use the API Key

The key is the final piece that links the identity to the application.

1.  Navigate back to the service user you created in Step 1 (`new-app-service-user`).
2.  Generate a new, PKCS#1-formatted API key for this user.
3.  Use that user's OCID, fingerprint, and private key in the new project's CI/CD secrets.

---

## 4. Concrete Example: The `RAG-Project`

-   **Identity & Role:** The user `rag-ingestor-service-user` and the group `RAG-Ingestor-Executors` are created and managed within the **`Shared-Infrastructure`** compartment. The user is a member of the group.
-   **Resources:** The `rag-ingestor` function and its related resources all live inside the **`Applications/RAG-Project/RAG-Prod`** compartment.
-   **Policy:** The IAM policy `Allow group RAG-Ingestor-Executors to manage objects...` is created and attached to the **`Applications/RAG-Project/RAG-Prod`** compartment.

This structure guarantees that the `rag-ingestor-service-user` has a clearly defined role, and its permissions are perfectly contained within its own project's blast radius.