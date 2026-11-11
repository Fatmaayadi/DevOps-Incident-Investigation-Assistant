---
doc_id: md-terraform-init-errors
title: "Terraform init Errors: backend configuration changed, provider installation and dependency lock file"
domain: terraform
technology: [terraform, iac]
category: infrastructure-as-code
document_type: troubleshooting_guide
difficulty: intermediate
keywords:
  - terraform init failed
  - backend configuration changed
  - -reconfigure
  - -migrate-state
  - -backend-config partial configuration
  - provider installation failed
  - Failed to install provider
  - doesn't match any of the checksums previously recorded in the dependency lock file
  - .terraform.lock.hcl
  - terraform init -upgrade
  - terraform providers lock
  - required_providers version constraint
  - TF_LOG
  - credentials in backend config
error_messages:
  - "Error: Failed to install provider"
  - "doesn't match any of the checksums previously recorded in the dependency lock file."
source_type: team_written_from_official_docs
language: en
references:
  - id: R1
    title: "terraform init command reference"
    publisher: HashiCorp Developer (Terraform documentation)
    url: https://developer.hashicorp.com/terraform/cli/commands/init
    accessed: 2026-11-02
  - id: R2
    title: "Backend block configuration overview (Credentials and sensitive data, Initialize the backend, Partial configuration)"
    publisher: HashiCorp Developer (Terraform documentation)
    url: https://developer.hashicorp.com/terraform/language/backend
    accessed: 2026-11-02
  - id: R3
    title: "Dependency Lock File (.terraform.lock.hcl)"
    publisher: HashiCorp Developer (Terraform documentation)
    url: https://developer.hashicorp.com/terraform/language/files/dependency-lock
    accessed: 2026-11-02
  - id: R4
    title: "Provider Requirements (required_providers, version constraints)"
    publisher: HashiCorp Developer (Terraform documentation)
    url: https://developer.hashicorp.com/terraform/language/providers/requirements
    accessed: 2026-11-02
  - id: R5
    title: "Enable Terraform logs (TF_LOG)"
    publisher: HashiCorp Developer (Terraform documentation)
    url: https://developer.hashicorp.com/terraform/internals/debugging
    accessed: 2026-11-02
  - id: R6
    title: "terraform providers lock command reference (-platform)"
    publisher: HashiCorp Developer (Terraform documentation)
    url: https://developer.hashicorp.com/terraform/cli/commands/providers/lock
    accessed: 2026-11-02
related_corpus_documents: []
last_reviewed: 2026-11-02
review_status: reviewed by team against sources
---

# Terraform init Errors: backend configuration changed, provider installation and dependency lock file

## Overview

`terraform init` "initializes a working directory containing Terraform configuration files". It is the first command to run after writing or cloning a configuration, and "it is safe to run this command multiple times" [R1]. It performs three main tasks [R1]:

1. **Backend initialization**: configure where the state is stored.
2. **Child module installation**: download the modules referenced in the configuration.
3. **Plugin installation**: download the providers and record them in the dependency lock file.

Most `init` failures belong to one of these steps. The command "will never delete your existing configuration or state" [R1], so it can be rerun safely while you investigate.

## Symptoms

- `init` refuses to continue after the backend block was changed, and asks how to handle the existing state (team observation; the documented rule is that "either `-reconfigure` or `-migrate-state` must be supplied to update the backend configuration" [R1]).
- `Error: Failed to install provider`, for example a package that "doesn't match any of the checksums previously recorded in the dependency lock file" [R3].
- `init` cannot find a provider version that satisfies the configuration (team observation; see version constraints [R4]).
- A teammate on another operating system cannot use a lock file that was created with a filesystem or network mirror [R3].
- `plan` or `apply` fails because the working directory was not initialized after a backend change [R2].

## Possible Causes

| Cause | Explanation |
|---|---|
| **Backend block changed** | Re-running `init` with an already-initialized backend requires `-reconfigure` or `-migrate-state` [R1]. After any backend change, you "must run terraform init again … before you can perform any plans, applies, or state operations" [R2] |
| **Partial backend configuration not supplied** | With a partial configuration, "the remaining configuration arguments must be provided as part of the initialization process", for example `-backend-config=PATH` [R2] |
| **Missing backend credentials** | Accessing remote state "generally requires access credentials" [R2] |
| **Checksum mismatch** | Terraform verifies each installed package against the checksums in the lock file and returns an error if none match [R3] |
| **Lock file pins an older provider version** | `init` reuses the versions recorded in the lock file; `-upgrade` is needed to select newer versions [R1, R3] |
| **Version constraint impossible to satisfy** | `required_providers` declares, for each provider, a `version` constraint giving "which subset of available provider versions the module is compatible with" [R4] |
| **Lock file missing checksums for other platforms** | When installing from a mirror, Terraform records checksums only for the current platform, "so the configuration will not be usable on any other platform" [R3] |

## Investigation Steps

1. **Read which step failed**: backend, modules or plugins [R1].
2. **For backend errors**: did the `backend` block change? Do you want to keep the existing state (`-migrate-state`) or start fresh with the new settings (`-reconfigure`)? [R1]
3. **Check credentials** for the backend through the environment variables or credential files conventional for the target system [R2].
4. **For provider errors**: compare `required_providers` constraints with the versions recorded in `.terraform.lock.hcl` [R3, R4].
5. **For checksum errors**: check whether the lock file was produced on another platform or through a mirror [R3].
6. **Enable logs** with `TF_LOG` if the error is not explicit [R5].

## Diagnostic Commands

```shell
# Re-initialize after a backend change, migrating the existing state
terraform init -migrate-state

# Re-initialize after a backend change, ignoring the previous backend configuration
terraform init -reconfigure

# Supply the rest of a partial backend configuration from a file
terraform init -backend-config=backend.hcl

# Ignore the versions selected in the lock file and take the newest allowed by constraints
terraform init -upgrade

# Record checksums for several platforms in the lock file
terraform providers lock -platform=linux_amd64 -platform=darwin_arm64 -platform=windows_amd64

# Detailed logs
TF_LOG=DEBUG terraform init
```

Sources: `-migrate-state`, `-reconfigure`, `-backend-config`, `-upgrade` [R1, R2]; `terraform providers lock` for several platforms [R3, R6]; `TF_LOG` [R5]. The `-platform=` values are examples chosen by the team.

## Interpretation of Results

| Observation | Meaning | Next step |
|---|---|---|
| `init` asks about the backend after you edited the backend block | Backend configuration changed [R1] | Choose `-migrate-state` (keep state) or `-reconfigure` (no migration) [R1] |
| Error about missing backend arguments | Partial configuration not completed [R2] | Pass `-backend-config` [R2] |
| Access denied by the storage service | Missing or invalid credentials [R2] | Provide credentials through environment variables (see `md-aws-iam-access-denied` for AWS) |
| `Failed to install provider … doesn't match any of the checksums` | Package differs from the recorded checksums [R3] | Check the source of the package; if the change is expected, update the lock file deliberately and review it |
| Works on Linux, fails on macOS/Windows with a lock file from a mirror | Checksums recorded for one platform only [R3] | `terraform providers lock -platform=…` [R3] |
| Newer provider expected but an older one is installed | Lock file selection [R1, R3] | `terraform init -upgrade`, then review the lock file change |

## Possible Solutions

- **Backend change**: rerun `init` with `-migrate-state` to copy the existing state, or `-reconfigure` to discard the previous configuration without migration [R1].
- **Partial configuration**: pass the missing arguments with `-backend-config` [R2].
- **Credentials**: leave credential arguments unset in the configuration, and provide them "using the credentials files or environment variables that are conventional for the target system" [R2].
- **Provider versions**: adjust the `version` constraint in `required_providers` [R4], then run `terraform init -upgrade` if you want newer versions [R1].
- **Lock file**: commit `.terraform.lock.hcl` to version control so that "Terraform will select exactly the same provider versions" next time [R1]. Pre-populate checksums for all team platforms with `terraform providers lock` [R3].

## Prevention

- Commit the dependency lock file and review its changes like code [R1, R3].
- Do not commit the `.terraform/` directory: it "may contain sensitive credentials for your remote backend" [R2].
- Avoid hardcoding credentials or passing them with `-backend-config`. Terraform stores these values in `.terraform` and in plan files, which "can leak sensitive credentials" [R2].

## Related Concepts

- **State locking errors during plan/apply**: see `md-terraform-state-lock`.
- **AWS permissions for remote state**: see `md-aws-iam-access-denied`.

## References

All pages were consulted on 2026-11-02, in their current version.

- [R1] HashiCorp Developer — *terraform init*. https://developer.hashicorp.com/terraform/cli/commands/init
- [R2] HashiCorp Developer — *Backend block configuration overview*. https://developer.hashicorp.com/terraform/language/backend
- [R3] HashiCorp Developer — *Dependency Lock File*. https://developer.hashicorp.com/terraform/language/files/dependency-lock
- [R4] HashiCorp Developer — *Provider Requirements*. https://developer.hashicorp.com/terraform/language/providers/requirements
- [R5] HashiCorp Developer — *Enable Terraform logs*. https://developer.hashicorp.com/terraform/internals/debugging
- [R6] HashiCorp Developer — *terraform providers lock*. https://developer.hashicorp.com/terraform/cli/commands/providers/lock

## Metadata

- **Nature of this document:** written by the project team from the official Terraform documentation listed above. It is **not** official HashiCorp documentation.
- **Verification:** each statement followed by a reference was checked against the source text. Statements marked "team observation" are our own reasoning.
- **Scope limits:** module registry authentication and HCP Terraform workspaces are not covered.
