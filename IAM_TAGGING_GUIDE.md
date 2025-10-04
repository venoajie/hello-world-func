
# OCI Tagging Strategy: A Practical Guide

This document defines the canonical tagging strategy for this OCI tenancy. Its purpose is to ensure consistent metadata for cost management, automation, and security.

## 1. Core Principles

1.  **Always Use Defined Tags:** Free-form tags are forbidden due to their inconsistency. All tags must belong to the `Tenancy-Management` namespace.
2.  **Tag All Resources:** Every resource that can be tagged should be tagged at creation time.
3.  **Tags Complement Compartments:** Compartments define the blast radius and ownership, while tags provide rich, queryable metadata about the resources within them.

## 2. The `Tenancy-Management` Tag Namespace

A single, central Tag Namespace is used for all resources.

**Namespace Name:** `Tenancy-Management`

**Defined Keys:**

| Key Name               | Type          | Description                                                      | Example Values                               |
| ---------------------- | ------------- | ---------------------------------------------------------------- | -------------------------------------------- |
| `Project-Name`         | String        | The name of the application or project the resource belongs to.  | `RAG-Project`, `hello-world`, `shared-infra` |
| `Environment`          | String (List) | The deployment environment of the resource.                      | `prod`, `dev`, `sandbox`                     |
| `Owner`                | String        | The person responsible for this resource.                        | `veno-ajie`                                  |
| `Automation-Lifecycle` | String (List) | A flag for automation scripts to manage the resource's lifespan. | `persistent`, `temporary`                    |

## 3. The IAM Power-Up: Tag-Based Policies

Tags are a critical component of our security strategy. They allow us to create highly granular permissions that are independent of compartments.

**Example Policy:** Granting a user full access to only sandbox resources.

```
# This policy, attached to the 'Sandbox' compartment, allows a user to manage
# any resource, but ONLY if that resource is explicitly tagged as 'sandbox'.

Allow group Sandbox-Users to manage all-resources in compartment Sandbox
    where target.resource.tag."Tenancy-Management"."Environment" = 'sandbox'
```

This prevents accidental damage to production resources and is a core pattern for secure access control.

## 4. A Repeatable Workflow for New Resources

Follow this checklist every time a new resource is created.

1.  **Create the Resource:** Provision the new resource (e.g., a VM, a bucket) in its correct compartment.
2.  **Apply Defined Tags:** Immediately after creation, navigate to the resource's "Tags" section.
3.  **Assign Values:**
    *   Select the `Tenancy-Management` namespace.
    *   Assign a value for `Project-Name`.
    *   Assign a value for `Environment`.
    *   Assign a value for `Owner`.
    *   Assign a value for `Automation-Lifecycle`.
