
# OCI Tagging Strategy: A Practical Guide

This document defines the canonical tagging strategy for this OCI tenancy. Its purpose is to ensure consistent metadata for cost management, automation, and security.

## 1. Core Principles
(No changes)

## 2. The `Tenancy-Management` Tag Namespace

A single, central Tag Namespace is used for all resources. It must be created in the **Root Compartment**.

**Namespace Name:** `Tenancy-Management`

**Defined Keys:**

| Key Name               | Type          | Description                                                                 | Example Values                               |
| ---------------------- | ------------- | --------------------------------------------------------------------------- | -------------------------------------------- |
| `Project-Name`         | String        | The name of the application or project the resource belongs to.             | `RAG-Project`, `hello-world`, `shared-infra` |
| `Environment`          | String (List) | The deployment environment of the resource.                                 | `prod`, `dev`, `sandbox`                     |
| `Owner`                | String        | The person responsible for this resource.                                   | `veno-ajie`                                  |
| `Automation-Lifecycle` | String (List) | A flag for automation scripts to manage the resource's lifespan.            | `persistent`, `temporary`                    |
| `Service-Identifier`   | String        | A unique, machine-readable identifier for a specific service or component.  | `rag-ingestor`, `auth-api`                   |

---

## 3. Advanced Security: Tag-Based Dynamic Groups

While compartment-based rules are good, tag-based rules provide the **maximum level of security and granularity**. This is the required pattern for all production functions.

### The Problem with Compartment-Based Rules

A rule like `ALL {resource.compartment.id = '...'}` is broad. If you accidentally create a second, unrelated function in the same compartment, it will instantly inherit all the sensitive permissions of the first function.

### The Solution: Match a Unique Tag

By matching a unique tag, we ensure that only the specific function we intend ever receives the permissions.

**Step 1: Add the `Service-Identifier` Key**
- In your `Tenancy-Management` Tag Namespace, add the new key `Service-Identifier`.

**Step 2: Update the Dynamic Group Rule**
- Navigate to your `RAGIngestorFunctionDynamicGroup`.
- Replace the old compartment-based rule with this new, more secure tag-based rule:

```
# This rule matches ONLY the function that has been explicitly tagged
# with the 'Service-Identifier' of 'rag-ingestor'.

ALL {resource.type = 'fnfunc', resource.defined_tags.'Tenancy-Management'.'Service-Identifier' = 'rag-ingestor'}
```

### How It Works Automatically

The CI/CD workflow in `.github/workflows/deploy.yml` is configured to automatically apply this exact tag (`"Tenancy-Management": {"Service-Identifier": "rag-ingestor"}`) every time the function is created or updated.

This creates a secure, "zero-trust" system where a function's identity is explicitly stamped onto it by the deployment pipeline, rather than being implicitly inherited from its location.