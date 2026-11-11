---
doc_id: md-gitlab-ci-job-failures
title: "GitLab CI/CD Job Failures: stuck jobs, runner tags, Docker permission denied, missing variables, image pull errors"
domain: gitlab
technology: [gitlab-ci, gitlab-runner, docker]
category: ci-cd
document_type: troubleshooting_guide
difficulty: intermediate
keywords:
  - GitLab pipeline failed
  - job stuck pending
  - no runner with matching tags
  - runner tags untagged jobs
  - permission denied docker.sock gitlab-runner
  - Cannot connect to the Docker daemon in CI
  - Docker-in-Docker privileged
  - docker socket binding
  - shell executor docker group
  - protected variables
  - variable empty in pipeline
  - CI_DEBUG_TRACE
  - Failed to pull image
  - job token allowlist
  - .gitlab-ci.yml rules
  - CI Lint
error_messages:
  - "Failed to pull image"
  - "pull access denied"
  - "requested access to the resource is denied"
source_type: team_written_from_official_docs
language: en
references:
  - id: R1
    title: "Debugging CI/CD pipelines"
    publisher: GitLab Docs
    url: https://docs.gitlab.com/ci/debugging/
    accessed: 2026-11-02
  - id: R2
    title: "Configuring runners (How the runner uses tags)"
    publisher: GitLab Docs
    url: https://docs.gitlab.com/ci/runners/configure_runners/
    accessed: 2026-11-02
  - id: R3
    title: "Use Docker to build Docker images"
    publisher: GitLab Docs
    url: https://docs.gitlab.com/ci/docker/using_docker_build/
    accessed: 2026-11-02
  - id: R4
    title: "Troubleshooting GitLab Runner"
    publisher: GitLab Docs
    url: https://docs.gitlab.com/runner/faq/
    accessed: 2026-11-02
  - id: R5
    title: "GitLab CI/CD variables (Protect variable)"
    publisher: GitLab Docs
    url: https://docs.gitlab.com/ci/variables/
    accessed: 2026-11-02
  - id: R6
    title: "Troubleshooting CI/CD variables (List all variables, Enable debug logging)"
    publisher: GitLab Docs
    url: https://docs.gitlab.com/ci/variables/variables_troubleshooting/
    accessed: 2026-11-02
related_corpus_documents: []
last_reviewed: 2026-11-02
review_status: reviewed by team against sources
---

# GitLab CI/CD Job Failures: stuck jobs, runner tags, Docker permission denied, missing variables, image pull errors

## Overview

A GitLab CI/CD job goes through several stages, and each stage fails in its own way:

1. **The job is added to the pipeline.** `rules`, `only/except` and `workflow: rules` decide this [R1].
2. **A runner picks the job up.** Runner and job **tags** decide this [R2].
3. **The runner prepares the environment**: pulling the image and connecting to Docker if the job uses it [R1, R3].
4. **The `script` commands run.** Their result depends on the variables and dependencies available [R1, R5].

Finding which stage failed is the first step. A job that is never picked up is not a script error. A `Failed to pull image` message is not an application error either.

## Symptoms

- A job stays pending and is reported as **stuck**. In the documented examples, a job whose tags do not match any runner "is executed and stuck" [R2].
- A pipeline does not run, or a job is missing from it [R1].
- `Failed to pull image …`, with messages such as `pull access denied … requested access to the resource is denied` [R1].
- Docker commands in the job fail because Docker is not reachable or not allowed (see Possible Causes) [R3, R4].
- A variable is empty in some pipelines but not in others [R5].

## Possible Causes

| Cause | Explanation |
|---|---|
| **No runner with matching tags** | A runner that runs only tagged jobs with tag `docker` leaves a job tagged `hello`, or an untagged job, stuck. A runner without tags that runs untagged jobs leaves a `docker`-tagged job stuck [R2] |
| **Job or pipeline not created** | Usually caused by `rules` or `only/except` configuration, or `workflow: rules`. A pipeline that contains only jobs in `.pre` or `.post` stages does not run [R1] |
| **Docker with the shell executor** | The `gitlab-runner` user runs the Docker commands "but needs permission to do so"; it must be added to the `docker` group [R3] |
| **Docker-in-Docker without privileged mode** | Docker-in-Docker requires privileged mode on the runner; socket binding does not [R3] |
| **Permission Denied on `/var/run/docker.sock` with the Docker executor** | "The most likely cause is that your system uses SELinux" [R4] |
| **Protected variable used on an unprotected branch** | A protected variable "is only available in pipelines that run on protected branches or protected tags" [R5] |
| **Image in another project's registry** | The CI/CD job token allowlist of the private project does not include the project running the job. Project access tokens cannot access images in other projects [R1] |
| **Self-signed certificate on the GitLab server or registry** | The runner FAQ covers `x509: certificate signed by unknown authority` and points to the self-signed certificates configuration [R4] |

## Investigation Steps

1. **Validate the `.gitlab-ci.yml` syntax** with the pipeline editor or the CI Lint tool [R1].
2. **If a job is missing or the pipeline does not start**, review `rules`, `only/except` and `workflow: rules` [R1].
3. **If the job is stuck**, compare the job's `tags` with the tags of the available runners and their "Run untagged jobs" setting [R2].
4. **If Docker commands fail**, identify the runner executor (shell, Docker, Kubernetes) and the method used: shell executor with the `docker` group, Docker-in-Docker (privileged), or socket binding [R3].
5. **For socket permission errors with the Docker executor**, check SELinux denials on the host [R4].
6. **Verify variables**: export the full list available in the failing job and compare it with what you expect, keeping in mind that this prints unmasked values in the job log (see the warning below the Diagnostic Commands). Check whether the branch is protected [R1, R5, R6].
7. **For image pull errors**, check the job token allowlist of the project hosting the image [R1].
8. **Read the runner logs** on the runner host, and enable debug logging if necessary [R4, R6].

## Diagnostic Commands

In `.gitlab-ci.yml`:

```yaml
# Verify that Docker works for the job
default:
  before_script:
    - docker info

# List the variables available to the job (masked ones show as [MASKED])
# WARNING: prints the value of every unmasked variable in the job log (see below)
debug-variables:
  script:
    - export

# Very verbose job log (exposes all variables: use with care)
debug-job:
  variables:
    CI_DEBUG_TRACE: "true"
  script:
    - ./build.sh
```

On the runner host:

```shell
# Runner service logs (systemd distributions)
journalctl --unit=gitlab-runner.service -n 100 --no-pager

# Can the gitlab-runner user use Docker? (shell executor)
sudo -u gitlab-runner -H docker info

# Restart the runner after changing its configuration
systemctl restart gitlab-runner.service
```

Sources: `docker info` in `before_script` and `sudo -u gitlab-runner -H docker info` [R3]; `export` and `CI_DEBUG_TRACE` [R6]; `journalctl --unit=gitlab-runner.service` and `systemctl restart gitlab-runner.service` [R4].

**Warning about `export`.** Listing the variables "exposes the values of all available variables, which can be a security risk" [R6]. Only masked variables are replaced by `[MASKED]` [R6], and "Masking a CI/CD variable is not a guaranteed way to prevent malicious users from accessing variable values" [R5]. Use `export` only temporarily, in a project whose job logs are visible to trusted members only, then remove it (team recommendation).

## Interpretation of Results

| Observation | Meaning | Next step |
|---|---|---|
| The job is stuck and no runner has its tags | Tag mismatch [R2] | Change the job tags, add tags to a runner, or allow untagged jobs [R2] |
| The pipeline was not created, with no error | `rules` / `workflow: rules` filtered it out [R1] | Fix the rules |
| `sudo -u gitlab-runner -H docker info` fails | The runner user lacks Docker access (shell executor) [R3] | Add `gitlab-runner` to the `docker` group [R3] |
| Docker executor, socket permission denied, SELinux enabled | SELinux denial [R4] | Check and adjust the SELinux policy |
| Variable present on `main` but empty on a feature branch | Protected variable [R5] | Use it only on protected branches, or unprotect it deliberately |
| `pull access denied … insufficient_scope` for another project's image | Job token allowlist [R1] | Add the project to the target project's allowlist [R1] |

## Possible Solutions

- **Tags**: align job `tags` with an available runner, or enable "Run untagged jobs" on a runner [R2].
- **Docker in jobs**, choosing one approach [R3]:
  - shell executor: add `gitlab-runner` to the `docker` group;
  - Docker-in-Docker: requires a privileged runner;
  - socket binding: mount `/var/run/docker.sock` in the `[runners.docker]` volumes.
- **Variables**: define them at the right level. Remember that protected variables only exist in pipelines on protected branches or tags [R5].
- **Images from other projects**: update the job token allowlist, or use a token type with a wider scope than a project access token [R1].
- **Self-signed certificates**: configure the runner with the certificate, as described in GitLab's self-signed certificates documentation linked from the runner FAQ [R4].

## Prevention

- Validate pipeline changes with CI Lint before merging them [R1].
- Document runner tags and which runners run untagged jobs [R2].
- Be aware of the security trade-offs:
  - adding `gitlab-runner` to the `docker` group "effectively grant[s] gitlab-runner full root permissions" [R3];
  - sharing the host Docker daemon (socket binding) "effectively disable[s] the container's security mechanisms" [R3].
- Use `CI_DEBUG_TRACE` only temporarily. It "exposes all variables and secrets available to the job" [R6]. Never store tokens or passwords in artifacts [R1].

## Related Concepts

- **Docker daemon permissions outside CI**: see `md-docker-daemon-permission-denied`.
- **Certificate errors**: see `md-net-tls-certificate-errors`.
- **The GitHub equivalent**: see `md-github-actions-failures`.

## References

All pages were consulted on 2026-11-02, in their current version.

- [R1] GitLab Docs — *Debugging CI/CD pipelines*. https://docs.gitlab.com/ci/debugging/
- [R2] GitLab Docs — *Configuring runners*. https://docs.gitlab.com/ci/runners/configure_runners/
- [R3] GitLab Docs — *Use Docker to build Docker images*. https://docs.gitlab.com/ci/docker/using_docker_build/
- [R4] GitLab Docs — *Troubleshooting GitLab Runner*. https://docs.gitlab.com/runner/faq/
- [R5] GitLab Docs — *GitLab CI/CD variables*. https://docs.gitlab.com/ci/variables/
- [R6] GitLab Docs — *Troubleshooting CI/CD variables*. https://docs.gitlab.com/ci/variables/variables_troubleshooting/

## Metadata

- **Nature of this document:** written by the project team from the official GitLab documentation listed above. It is **not** official GitLab documentation.
- **Verification:** each statement followed by a reference was checked against the source text. Statements marked "team recommendation" are our own reasoning.
- **Scope limits:** Kubernetes executor specifics and GitLab Runner autoscaling are not covered.
