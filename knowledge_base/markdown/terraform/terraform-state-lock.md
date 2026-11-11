---
doc_id: md-terraform-state-lock
title: "Terraform State Lock: plan or apply blocked because the state is locked"
domain: terraform
technology: [terraform, aws-s3, iac]
category: infrastructure-as-code
document_type: troubleshooting_guide
difficulty: intermediate
keywords:
  - Error acquiring the state lock
  - state is locked
  - state lock
  - lock ID
  - terraform force-unlock
  - -lock-timeout
  - -lock=false
  - concurrent terraform runs
  - interrupted CI job left lock
  - S3 backend use_lockfile
  - DynamoDB lock table deprecated
  - .tflock
  - remote state backend
error_messages: []
source_type: team_written_from_official_docs
language: en
references:
  - id: R1
    title: "State: Locking"
    publisher: HashiCorp Developer (Terraform documentation)
    url: https://developer.hashicorp.com/terraform/language/state/locking
    accessed: 2026-11-02
  - id: R2
    title: "terraform force-unlock command reference"
    publisher: HashiCorp Developer (Terraform documentation)
    url: https://developer.hashicorp.com/terraform/cli/commands/force-unlock
    accessed: 2026-11-02
  - id: R3
    title: "terraform plan command reference (-lock, -lock-timeout)"
    publisher: HashiCorp Developer (Terraform documentation)
    url: https://developer.hashicorp.com/terraform/cli/commands/plan
    accessed: 2026-11-02
  - id: R4
    title: "terraform init command reference (-lock-timeout default)"
    publisher: HashiCorp Developer (Terraform documentation)
    url: https://developer.hashicorp.com/terraform/cli/commands/init
    accessed: 2026-11-02
  - id: R5
    title: "Backend Type: s3 (State Locking, Permissions Required)"
    publisher: HashiCorp Developer (Terraform documentation)
    url: https://developer.hashicorp.com/terraform/language/backend/s3
    accessed: 2026-11-02
  - id: R6
    title: "Enable Terraform logs (TF_LOG)"
    publisher: HashiCorp Developer (Terraform documentation)
    url: https://developer.hashicorp.com/terraform/internals/debugging
    accessed: 2026-11-02
related_corpus_documents: []
last_reviewed: 2026-11-02
review_status: reviewed by team against sources
---

# Terraform State Lock: plan or apply blocked because the state is locked

## Overview

Terraform records what it manages in a **state** file. To avoid corruption, "if supported by your backend, Terraform will lock your state for all operations that could write state. This prevents others from acquiring the lock and potentially corrupting your state" [R1]. The lock is taken automatically, and "if state locking fails, Terraform does not continue" [R1].

A "state is locked" error therefore has only two possible meanings:

1. **Someone or something is really running Terraform** on the same state: a colleague, another CI job, a scheduled pipeline.
2. **A previous run did not release its lock**: it crashed, was cancelled, or lost its connection. In that case, Terraform's automatic unlocking failed.

Terraform provides `terraform force-unlock` for the second case only. It "should only be used to unlock your own lock in the situation where automatic unlocking failed" [R1].

## Symptoms

- `terraform plan` or `terraform apply` stops with an error saying that the state lock could not be acquired, and prints information about the current lock, including a **lock ID** (team observation; Terraform "will output this lock ID if unlocking fails" [R1]).
- With the default `-lock-timeout` of `0s`, the failure is immediate "if the lock is already held by another process" [R4].
- In CI, the error appears after a previous job was cancelled or timed out in the middle of an `apply` (team observation).

## Possible Causes

| Cause | Explanation |
|---|---|
| **Concurrent run on the same state** | Another `plan`/`apply` holds the lock [R1] |
| **Stale lock after an interrupted run** | Automatic unlocking failed, for example because the process was killed (team inference based on [R1]) |
| **Lock-timeout too short** in automation | The default `0s` fails immediately instead of waiting [R4] |
| **Backend permissions for the lock** | With the S3 backend and `use_lockfile`, `s3:GetObject`, `s3:PutObject` and `s3:DeleteObject` are required on the `.tflock` file [R5] |
| **Backend without locking** | "Not all backends support locking". On S3, locking is opt-in (`use_lockfile = true`) [R1, R5] |

## Investigation Steps

1. **Read the lock information** printed by Terraform: the lock ID and the information about who holds the lock (team recommendation).
2. **Check whether a run is really in progress**: running CI jobs, colleagues, scheduled pipelines on the same workspace (team recommendation).
3. **If a run is in progress, wait**, or rerun with `-lock-timeout` so that Terraform retries for a while [R3].
4. **If no run is in progress** and the lock comes from your own interrupted run, use `terraform force-unlock` with the lock ID [R1, R2].
5. **If unlocking itself fails**, check the backend permissions on the lock object [R5], and enable `TF_LOG` for details [R6].

## Diagnostic Commands

```shell
# Retry acquiring the lock for up to 5 minutes instead of failing immediately
terraform plan -lock-timeout=5m

# Detailed logs (TRACE, DEBUG, INFO, WARN, ERROR) to stderr, optionally to a file
TF_LOG=DEBUG TF_LOG_PATH=./terraform-debug.log terraform plan

# Release a stale lock that you own (requires the lock ID shown in the error)
terraform force-unlock <LOCK_ID>
```

S3 backend with native locking:

```hcl
terraform {
  backend "s3" {
    bucket       = "my-terraform-state"
    key          = "network/terraform.tfstate"
    region       = "eu-west-1"
    use_lockfile = true
  }
}
```

Sources: `-lock-timeout` [R3, R4]; `TF_LOG` and `TF_LOG_PATH` [R6]; `terraform force-unlock [options] LOCK_ID` [R2]; `use_lockfile` [R5]. The bucket, key and region values are placeholders.

## Interpretation of Results

| Observation | Meaning | Next step |
|---|---|---|
| Another pipeline or person is running Terraform on the same state | The lock is legitimate [R1] | Wait, or serialize the runs |
| `-lock-timeout` makes the command succeed after a while | A short concurrent operation held the lock [R3] | Keep a lock timeout in automation |
| No run in progress; your previous run was interrupted | Stale lock [R1] | `terraform force-unlock <LOCK_ID>` [R2] |
| `force-unlock` fails, or locking fails on S3 | Missing permissions on the `.tflock` object, or backend configuration [R5] | Grant the documented S3 permissions [R5] |
| The backend has no locking configured | State is not protected [R1, R5] | Enable locking (`use_lockfile = true` on S3) [R5] |

## Possible Solutions

- **Wait for the running operation** or use `-lock-timeout` in pipelines [R3].
- **Force-unlock only your own stale lock.** "If you unlock the state when someone else is holding the lock it could cause multiple writers" [R1]. The command requires the unique lock ID, which "acts as a nonce, ensuring that locks and unlocks target the correct lock" [R1]. It "does not modify your infrastructure" [R2].
- **Do not disable locking.** `-lock=false` "is dangerous if others might concurrently run commands against the same workspace" [R3]; HashiCorp does "not recommend it" [R1].
- **Migrate from DynamoDB locking to S3 locking**: DynamoDB-based locking "is deprecated and will be removed in a future minor version"; both can be configured during migration [R5].

## Prevention

- Run Terraform for a given state from a single pipeline, and avoid parallel jobs on the same workspace (team recommendation).
- Use a backend that supports locking, and enable it [R1, R5].
- Enable bucket versioning on the S3 state bucket, which is "highly recommended … to allow for state recovery" [R5].
- Give CI jobs enough time to finish an `apply`, so that they are not killed while holding the lock (team recommendation).

## Related Concepts

- **Initialization and backend configuration errors**: see `md-terraform-init-errors`.
- **AWS permissions behind the S3 backend**: see `md-aws-iam-access-denied`.
- Corpus note: the excerpt of *The Terraform Book* in the corpus (chapter 3, building an application stack) does not cover state locking.

## References

All pages were consulted on 2026-11-02, in their current version.

- [R1] HashiCorp Developer — *State: Locking*. https://developer.hashicorp.com/terraform/language/state/locking
- [R2] HashiCorp Developer — *terraform force-unlock*. https://developer.hashicorp.com/terraform/cli/commands/force-unlock
- [R3] HashiCorp Developer — *terraform plan*. https://developer.hashicorp.com/terraform/cli/commands/plan
- [R4] HashiCorp Developer — *terraform init*. https://developer.hashicorp.com/terraform/cli/commands/init
- [R5] HashiCorp Developer — *Backend Type: s3*. https://developer.hashicorp.com/terraform/language/backend/s3
- [R6] HashiCorp Developer — *Enable Terraform logs*. https://developer.hashicorp.com/terraform/internals/debugging

## Metadata

- **Nature of this document:** written by the project team from the official Terraform documentation listed above. It is **not** official HashiCorp documentation.
- **Verification:** each statement followed by a reference was checked against the source text. Statements marked "team observation", "team inference" or "team recommendation" are our own reasoning.
- **Scope limits:** the exact wording of the lock error is not quoted, because it is not reproduced in the cited pages. HCP Terraform / Terraform Enterprise run queues are not covered.
