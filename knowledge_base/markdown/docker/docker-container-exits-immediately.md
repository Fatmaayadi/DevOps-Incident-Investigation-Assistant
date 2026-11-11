---
doc_id: md-docker-container-exits
title: Docker Container Exits Immediately After Starting
domain: docker
technology: [docker, dockerfile]
category: container-failure
document_type: troubleshooting_guide
difficulty: beginner
keywords:
  - container exits immediately
  - Exited (0)
  - Exited (1)
  - Exited (137)
  - exit code 125 126 127
  - docker ps -a
  - docker logs
  - ENTRYPOINT CMD
  - exec form shell form
  - PID 1
  - root process
  - detached mode
  - service start in container
  - restart policy
  - OOM
error_messages:
  - "Container command '/etc' could not be invoked."
  - "Container command 'foo' not found or does not exist."
  - "flag provided but not defined"
source_type: team_written_from_official_docs
language: en
references:
  - id: R1
    title: "Running containers (sections: Exit status, Foreground and background)"
    publisher: Docker Docs
    url: https://docs.docker.com/engine/containers/run/
    accessed: 2026-11-02
  - id: R2
    title: "docker container run — reference (section: Detached mode)"
    publisher: Docker Docs (docker/cli reference)
    url: https://docs.docker.com/reference/cli/docker/container/run/
    accessed: 2026-11-02
  - id: R3
    title: "docker container ls — reference (--all, --filter exited=)"
    publisher: Docker Docs (docker/cli reference)
    url: https://docs.docker.com/reference/cli/docker/container/ls/
    accessed: 2026-11-02
  - id: R4
    title: "docker container logs — reference"
    publisher: Docker Docs (docker/cli reference)
    url: https://docs.docker.com/reference/cli/docker/container/logs/
    accessed: 2026-11-02
  - id: R5
    title: "Dockerfile reference (Shell and exec form, ENTRYPOINT)"
    publisher: Docker Docs
    url: https://docs.docker.com/reference/dockerfile/
    accessed: 2026-11-02
  - id: R6
    title: "Run multiple processes in a container"
    publisher: Docker Docs
    url: https://docs.docker.com/engine/containers/multi-service_container/
    accessed: 2026-11-02
  - id: R7
    title: "Start containers automatically (restart policies)"
    publisher: Docker Docs
    url: https://docs.docker.com/engine/containers/start-containers-automatically/
    accessed: 2026-11-02
  - id: R8
    title: "Resource constraints (Understand the risks of running out of memory)"
    publisher: Docker Docs
    url: https://docs.docker.com/engine/containers/resource_constraints/
    accessed: 2026-11-02
last_reviewed: 2026-11-02
review_status: reviewed by team against sources
---

# Docker Container Exits Immediately After Starting

## Overview

A container lives as long as its **main process** lives. "A container's main running process is the `ENTRYPOINT` and/or `CMD` at the end of the `Dockerfile`" [R6], and "containers started in detached mode exit when the root process used to run the container exits" [R2]. A container that "exits immediately" is therefore always one of three things:

- a main process that **finished normally**, because it was not a long-running foreground process;
- a main process that **crashed**;
- a command that **could not even be started**.

The exit code tells which case applies. Docker documents the codes returned by `docker run` [R1]:

| Exit code | Meaning (Docker documentation) |
|---|---|
| **125** | "the error is with Docker daemon itself", for example an invalid `docker run` flag |
| **126** | "the specified contained command can't be invoked" |
| **127** | "the contained command can't be found" |
| **any other value** | the exit code "of the provided container command" |

## Symptoms

- `docker ps` does not show the container, but `docker ps -a` shows it with a status like `Exited (0) …`, `Exited (1) …` or `Exited (137) …` [R3].
- `docker run` returns at once with an error such as `Container command 'foo' not found or does not exist.` (127) or `Container command '/etc' could not be invoked.` (126) [R1].
- With a restart policy, the container appears to restart repeatedly (see Possible Causes).

## Possible Causes

| Cause | Explanation |
|---|---|
| **The main command finishes** | For example, starting a daemon with `service nginx start`: "the root process (`service nginx start`) returns and the detached container stops as designed". Docker's example starts nginx in the foreground instead: `nginx -g 'daemon off;'` [R2] |
| **The application crashes at startup** | Missing configuration, environment variable or dependency; the exit code is the application's own [R1] |
| **Command not found** | Wrong binary name or path in `CMD`/`ENTRYPOINT`, or missing in the image: exit code 127 [R1] |
| **Command cannot be invoked** | The target is not executable, for example a directory: exit code 126 [R1] |
| **Docker-side error** | Invalid flag or daemon problem: exit code 125 [R1] |
| **Shell form vs exec form confusion** | The exec form is parsed as a JSON array and "doesn't automatically invoke a command shell", so variables are not expanded unless a shell is called explicitly [R5] |
| **Killed for memory** | On Linux hosts, the kernel may kill processes when memory runs out, and containers are more likely to be killed than the daemon [R8]. The documented `docker ps` example also shows `Exited (137)` containers [R3] |

## Investigation Steps

1. **List stopped containers** and read the status and exit code [R3].
2. **Read the container's logs**. `docker logs` retrieves the logs present at the time of execution, including those of a container that has already exited (team note: logs remain until the container is removed) [R4].
3. **Interpret the exit code** with the table above [R1].
4. **Check the command that was run**: the `COMMAND` column of `docker ps -a`, and the `ENTRYPOINT`/`CMD` of the image [R3, R5].
5. **Run the image interactively with a shell** in place of the normal command, then start the application by hand to see the error (team recommendation).
6. **Check whether a restart policy is hiding the problem** by restarting the container again and again [R7].

## Diagnostic Commands

```shell
# All containers, including stopped ones (status shows the exit code)
docker ps -a

# Only containers that exited with a given code
docker ps -a --filter 'exited=137'

# Logs of the (stopped) container, last 100 lines with timestamps
docker logs --tail 100 -t <container>

# Image entrypoint and default command
docker inspect --format '{{json .Config.Entrypoint}} {{json .Config.Cmd}}' <image>

# Start a shell instead of the normal command to test by hand
docker run --rm -it --entrypoint sh <image>
```

Sources: `docker ps -a` and `--filter exited=` [R3]; `docker logs`, `--tail`, `-t` [R4]; the exit-code examples [R1]. The `docker inspect --format` and `--entrypoint sh` commands are team-selected uses of documented `docker inspect` templates and `docker run` options.

## Interpretation of Results

| Observation | Meaning | Next step |
|---|---|---|
| `Exited (0)` right after start | The main command completed normally; it is not a long-running foreground process [R2] | Run the service in the foreground as the main process [R2] |
| `Exited (1)` (or another application code) | The application failed [R1] | Read `docker logs` for the error |
| Exit code 127, "not found or does not exist" | The command is missing from the image or misspelled [R1] | Fix `CMD`/`ENTRYPOINT` or install the binary |
| Exit code 126, "could not be invoked" | The command exists but is not executable [R1] | Fix the path or the file permissions |
| Exit code 125 | Problem with Docker or with the `docker run` arguments [R1] | Read the error printed by `docker run` |
| `Exited (137)` | The process was killed; check memory first (team inference, see [R3, R8]) | Check memory limits and host memory |
| Logs show an unexpanded `$VARIABLE` | Exec form used without a shell [R5] | Use the shell form, or call `sh -c` explicitly [R5] |

## Possible Solutions

- **Keep the main process in the foreground.** Do not pass `service x start` to a detached container; run the server binary in foreground mode, as in `nginx -g 'daemon off;'` [R2].
- **Fix the command**: correct the path or name in `CMD`/`ENTRYPOINT`, and make the file executable [R1, R5].
- **Fix the application startup error** shown in the logs (configuration, environment variables, dependencies).
- **Use the exec form for `ENTRYPOINT`** so that the process runs as PID 1 and receives signals. With the shell form, the process "will not be the container's PID 1, and will not receive Unix signals" [R5].
- **Use `--init`** when the main process does not reap child processes correctly [R6].
- **Choose a restart policy deliberately**. `on-failure` restarts only on a non-zero exit code. A restart policy "only takes effect after a container starts successfully", meaning it was up for at least 10 seconds [R7].

## Prevention

- Use one service per container, with the service as the foreground main process [R6].
- Test the image locally with `docker run` before deploying it, and read `docker logs` (team recommendation).
- Set memory limits consciously, and avoid disabling the OOM safeguards (`--oom-kill-disable`, extreme `--oom-score-adj`) [R8].

## Related Concepts

- **The same pattern in Kubernetes**: see `md-k8s-crashloopbackoff`, and `md-k8s-oomkilled-resource-limits` for memory kills.
- **Supervised services on Linux**: see `md-linux-systemd-service-failure`.
- **Docker daemon access errors**: see `md-docker-daemon-permission-denied`.

## References

All pages were consulted on 2026-11-02, in their current version. They were checked against the sources in the `docker/docs` and `docker/cli` repositories, or against the published page.

- [R1] Docker Docs — *Running containers*. https://docs.docker.com/engine/containers/run/
- [R2] Docker Docs — *docker container run*. https://docs.docker.com/reference/cli/docker/container/run/
- [R3] Docker Docs — *docker container ls*. https://docs.docker.com/reference/cli/docker/container/ls/
- [R4] Docker Docs — *docker container logs*. https://docs.docker.com/reference/cli/docker/container/logs/
- [R5] Docker Docs — *Dockerfile reference*. https://docs.docker.com/reference/dockerfile/
- [R6] Docker Docs — *Run multiple processes in a container*. https://docs.docker.com/engine/containers/multi-service_container/
- [R7] Docker Docs — *Start containers automatically*. https://docs.docker.com/engine/containers/start-containers-automatically/
- [R8] Docker Docs — *Resource constraints*. https://docs.docker.com/engine/containers/resource_constraints/

## Metadata

- **Nature of this document:** written by the project team from the official Docker documentation listed above. It is **not** official Docker documentation.
- **Verification:** each statement followed by a reference was checked against the source text. Statements marked "team note", "team inference" or "team recommendation" are our own reasoning.
- **Scope limits:** the Docker documentation does not explain exit code 137; it appears in a documented `docker ps` example. Docker Compose and Swarm services have their own restart settings, which are not covered here.
