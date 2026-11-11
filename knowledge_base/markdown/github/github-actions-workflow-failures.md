---
doc_id: md-github-actions-failures
title: "GitHub Actions Workflow Failures: token permissions, secrets, triggers and runners"
domain: github
technology: [github-actions, github, ci-cd]
category: ci-cd
document_type: troubleshooting_guide
difficulty: intermediate
keywords:
  - GitHub Actions failed
  - GITHUB_TOKEN permissions
  - Resource not accessible by integration
  - 403 in workflow
  - permissions key
  - secrets empty
  - secrets forked pull request
  - Dependabot read-only token
  - workflow not triggered
  - workflow did not run after push by GITHUB_TOKEN
  - ACTIONS_STEP_DEBUG
  - ACTIONS_RUNNER_DEBUG
  - runner labels
  - job timeout 6 hours
error_messages:
  - "Resource not accessible by integration"
source_type: team_written_from_official_docs
language: en
references:
  - id: R1
    title: "GITHUB_TOKEN (concepts)"
    publisher: GitHub Docs
    url: https://docs.github.com/en/actions/concepts/security/github_token
    accessed: 2026-11-02
  - id: R2
    title: "Use GITHUB_TOKEN for authentication in workflows"
    publisher: GitHub Docs
    url: https://docs.github.com/en/actions/tutorials/authenticate-with-github_token
    accessed: 2026-11-02
  - id: R3
    title: "Workflow syntax for GitHub Actions (permissions)"
    publisher: GitHub Docs
    url: https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax
    accessed: 2026-11-02
  - id: R4
    title: "Using secrets in GitHub Actions"
    publisher: GitHub Docs
    url: https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets
    accessed: 2026-11-02
  - id: R5
    title: "Secrets (concepts)"
    publisher: GitHub Docs
    url: https://docs.github.com/en/actions/concepts/security/secrets
    accessed: 2026-11-02
  - id: R6
    title: "Enabling debug logging"
    publisher: GitHub Docs
    url: https://docs.github.com/en/actions/how-tos/monitor-workflows/enable-debug-logging
    accessed: 2026-11-02
  - id: R7
    title: "Troubleshooting workflows"
    publisher: GitHub Docs
    url: https://docs.github.com/en/actions/how-tos/troubleshoot-workflows
    accessed: 2026-11-02
  - id: R8
    title: "Actions limits"
    publisher: GitHub Docs
    url: https://docs.github.com/en/actions/reference/limits
    accessed: 2026-11-02
  - id: R9
    title: "Troubleshooting the REST API (Resource not accessible)"
    publisher: GitHub Docs
    url: https://docs.github.com/en/rest/using-the-rest-api/troubleshooting-the-rest-api
    accessed: 2026-11-11
  - id: R10
    title: "Error: 403 Resource not accessible by integration (code scanning)"
    publisher: GitHub Docs
    url: https://docs.github.com/en/code-security/reference/code-scanning/troubleshoot-analysis-errors/resource-not-accessible
    accessed: 2026-11-11
last_reviewed: 2026-11-02
review_status: reviewed by team against sources
---

# GitHub Actions Workflow Failures: token permissions, secrets, triggers and runners

## Overview

A GitHub Actions problem usually belongs to one of four groups:

1. **The workflow did not start at all**: trigger, branch, filters, or the workflow is disabled [R7].
2. **A step fails with an authorization error**, because the automatic `GITHUB_TOKEN` lacks a permission [R1, R3].
3. **A secret is empty or unavailable**, for example in workflows triggered from forks [R4].
4. **A runner problem**: labels, self-hosted runners, or time limits [R7, R8].

At the start of each job, GitHub creates a unique `GITHUB_TOKEN` to authenticate in the workflow. It is a GitHub App installation access token whose permissions "are limited to the repository that contains your workflow" [R1].

## Symptoms

- A job fails when it calls the GitHub API, publishes a package, comments on a pull request or pushes, with an HTTP 403-style authorization error (team observation; the exact message depends on the action or tool used).
- The error `Resource not accessible by integration`. With a GitHub App token or a fine-grained personal access token, it means that "your token has insufficient permissions" [R9]. The automatic `GITHUB_TOKEN` is a GitHub App installation access token [R1]. The same error is documented for code scanning on Dependabot pull requests, whose workflows run with read-only scopes [R10].
- A step behaves as if a secret were missing. If a secret has not been set, an expression referencing it returns an empty string [R4].
- A workflow does not run after another workflow pushed commits with `GITHUB_TOKEN` [R1].
- A workflow does not run on a pull request that has merge conflicts [R7].
- A job is terminated after running too long [R8].

## Possible Causes

| Cause | Explanation |
|---|---|
| **Missing token permission** | The `permissions` key modifies the default permissions. "If you specify the access for any of these permissions, all of those that are not specified are set to none" [R3] |
| **Restricted default permissions** | The defaults come from the enterprise, organization or repository settings, then from the workflow and job configuration [R3] |
| **Pull request from a fork** | For `pull_request` events from forks (other than `pull_request_target`), write permissions become read-only unless "Send write tokens to workflows from pull requests" is enabled [R3]. "With the exception of GITHUB_TOKEN, secrets are not passed to the runner when a workflow is triggered from a forked repository" [R4] |
| **Dependabot pull requests** | They "run as if they are from a forked repository", use a read-only `GITHUB_TOKEN`, and "cannot access any secrets" [R3] |
| **Secret not defined, or not passed to the action** | Unset secrets evaluate to an empty string [R4]. "To make a secret available to an action, you must set the secret as an input or environment variable in your workflow file" [R5] |
| **No new run after a `GITHUB_TOKEN` push** | Events triggered by `GITHUB_TOKEN` do not create new workflow runs, except `workflow_dispatch` and `repository_dispatch` (and approval-gated `pull_request` runs) [R1] |
| **Trigger conditions** | Some events only run from the default branch (for example `schedule`); branch/path filters can skip the run; a disabled workflow does not respond to triggers [R7] |
| **Runner labels** | A label that matches existing preset labels can cause runner assignment issues [R7] |
| **Time limits** | Jobs on GitHub-hosted runners can run up to 6 hours; self-hosted runners up to 5 days; queued self-hosted jobs are cancelled after 24 hours [R8] |

## Investigation Steps

1. **Check whether the run exists.** If not, review the `on:` triggers, filters and branch, and whether the workflow is disabled [R7].
2. **Open the failed step's log** and look for the exact error [R7].
3. **For authorization errors**, read the `permissions` block at workflow and job level. Remember that unspecified permissions become `none` [R3]. Check whether the event comes from a fork or Dependabot [R3].
4. **For secret problems**, check that the secret exists at the expected level (repository, environment or organization), and that it is passed to the step as an input or environment variable [R4, R5]. Check whether the run comes from a fork [R4].
5. **Enable debug logging** if the logs are not detailed enough: `ACTIONS_STEP_DEBUG` for step logs, `ACTIONS_RUNNER_DEBUG` for runner diagnostic logs [R6].
6. **For skipped jobs**, download the log archive and read `JOB-NAME/system.txt`, which contains the `Evaluating`, `Expanded` and `Result` lines of the `if` condition [R7].

## Diagnostic Commands

Configuration to inspect or add in the workflow file:

```yaml
# Explicit, minimal permissions for the job (unspecified ones become "none")
permissions:
  contents: read
  issues: write

# Pass a secret to a step explicitly
steps:
  - run: ./deploy.sh
    env:
      API_TOKEN: ${{ secrets.API_TOKEN }}
```

Debug logging (repository secrets or variables) [R6]:

```text
ACTIONS_STEP_DEBUG = true     # more detailed step logs
ACTIONS_RUNNER_DEBUG = true   # runner diagnostic logs in the log archive
```

Verbose output of tools inside a step, as suggested by GitHub [R7]:

```shell
GIT_TRACE=1 GIT_CURL_VERBOSE=1 git fetch origin
npm install --verbose
```

Sources: `permissions` syntax and examples [R2, R3]; passing secrets as environment variables [R4, R5]; debug variables [R6]; verbose tools [R7].

## Interpretation of Results

| Observation | Meaning | Next step |
|---|---|---|
| `Resource not accessible by integration` | The token lacks a permission required by the endpoint [R9] | Read the `X-Accepted-GitHub-Permissions` response header, which lists the required permissions, then grant them with `permissions` [R3, R9] |
| The workflow declares `permissions:` for some scopes only, and the failing call needs another scope | That scope is set to `none` [R3] | Add the missing permission with the least access needed [R2, R3] |
| The failure happens only on pull requests from forks | Read-only token and no secrets for fork-triggered workflows [R3, R4] | Redesign the workflow; do not expose secrets to untrusted code |
| The failure happens only on Dependabot pull requests | Read-only token, no secrets [R3] | Handle Dependabot runs separately |
| A secret value is empty in the logs or in a condition | Secret not set at this level, or not passed to the step [R4, R5] | Define the secret and pass it explicitly |
| A push from a workflow did not trigger the other workflow | Expected behaviour with `GITHUB_TOKEN` [R1] | Use `workflow_dispatch`, or a GitHub App token or PAT if a run is required [R1] |
| Job terminated after a long time | Execution time limit reached [R8] | Split the job, or use self-hosted runners for long jobs |

## Possible Solutions

- **Grant the minimum required permissions** with the `permissions` key, at workflow or job level [R2, R3].
- **Pass secrets explicitly** as inputs or environment variables, and define them at the right level [R4, R5].
- **Fork-triggered workflows**: they get a read-only token and no secrets by design [R3, R4]. Run privileged steps in a separate, trusted workflow (team recommendation).
- **Trigger dependent workflows** with `workflow_dispatch`, or create pull requests with a GitHub App token or a personal access token when runs must start without approval [R1].
- **Use unique labels for self-hosted runners** [R7].

## Prevention

- Always declare `permissions` explicitly with least privilege. An action can access `GITHUB_TOKEN` through `github.token` even if it is not passed explicitly [R2].
- Prefer GitHub Apps or fine-grained credentials with minimal scopes over personal tokens [R5].
- Do not print secrets. Redaction exists but "is not guaranteed" [R5].

## Related Concepts

- **Push and authentication errors outside CI**: see `md-git-push-rejected-ssh`.
- **The GitLab equivalent**: see `md-gitlab-ci-job-failures`.

## References

All pages were consulted on 2026-11-02, in their current version.

- [R1] GitHub Docs — *GITHUB_TOKEN*. https://docs.github.com/en/actions/concepts/security/github_token
- [R2] GitHub Docs — *Use GITHUB_TOKEN for authentication in workflows*. https://docs.github.com/en/actions/tutorials/authenticate-with-github_token
- [R3] GitHub Docs — *Workflow syntax for GitHub Actions*. https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax
- [R4] GitHub Docs — *Using secrets in GitHub Actions*. https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets
- [R5] GitHub Docs — *Secrets*. https://docs.github.com/en/actions/concepts/security/secrets
- [R6] GitHub Docs — *Enabling debug logging*. https://docs.github.com/en/actions/how-tos/monitor-workflows/enable-debug-logging
- [R7] GitHub Docs — *Troubleshooting workflows*. https://docs.github.com/en/actions/how-tos/troubleshoot-workflows
- [R8] GitHub Docs — *Actions limits*. https://docs.github.com/en/actions/reference/limits
- [R9] GitHub Docs — *Troubleshooting the REST API* (consulted on 2026-11-11). https://docs.github.com/en/rest/using-the-rest-api/troubleshooting-the-rest-api
- [R10] GitHub Docs — *Error: 403 "Resource not accessible by integration"* (consulted on 2026-11-11). https://docs.github.com/en/code-security/reference/code-scanning/troubleshoot-analysis-errors/resource-not-accessible

## Metadata

- **Nature of this document:** written by the project team from the official GitHub documentation listed above. It is **not** official GitHub documentation.
- **Verification:** each statement followed by a reference was checked against the source text. Statements marked "team observation" or "team recommendation" are our own reasoning.
- **Scope limits:** GitHub-hosted runner images and billing problems are not covered. Apart from `Resource not accessible by integration` [R9, R10], error messages returned by the API depend on the tool used; they are not quoted.
