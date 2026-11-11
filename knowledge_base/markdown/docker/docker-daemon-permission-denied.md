---
doc_id: md-docker-daemon-permission-denied
title: "Docker: permission denied on the daemon socket / Cannot connect to the Docker daemon"
domain: docker
technology: [docker, linux, systemd]
category: access-permissions
document_type: troubleshooting_guide
difficulty: beginner
keywords:
  - permission denied docker.sock
  - Got permission denied while trying to connect to the Docker daemon socket
  - Cannot connect to the Docker daemon
  - Is the docker daemon running
  - docker group
  - usermod -aG docker
  - newgrp docker
  - DOCKER_HOST
  - sudo docker
  - rootless mode
  - ~/.docker/config.json permission denied
error_messages:
  - "Cannot connect to the Docker daemon. Is 'docker daemon' running on this host?"
  - "WARNING: Error loading config file: /home/user/.docker/config.json - stat /home/user/.docker/config.json: permission denied"
source_type: team_written_from_official_docs
language: en
references:
  - id: R1
    title: "Linux post-installation steps for Docker Engine (Manage Docker as a non-root user)"
    publisher: Docker Docs
    url: https://docs.docker.com/engine/install/linux-postinstall/
    accessed: 2026-11-02
  - id: R2
    title: "Troubleshooting the Docker daemon (Unable to connect, Check whether Docker is running, DOCKER_HOST)"
    publisher: Docker Docs
    url: https://docs.docker.com/engine/daemon/troubleshoot/
    accessed: 2026-11-02
  - id: R3
    title: "Docker Engine security (Docker daemon attack surface)"
    publisher: Docker Docs
    url: https://docs.docker.com/engine/security/
    accessed: 2026-11-02
  - id: R4
    title: "Rootless mode"
    publisher: Docker Docs
    url: https://docs.docker.com/engine/security/rootless/
    accessed: 2026-11-02
  - id: R5
    title: "dockerd — reference (Daemon socket option)"
    publisher: Docker Docs (docker/cli reference)
    url: https://docs.docker.com/reference/cli/dockerd/
    accessed: 2026-11-11
last_reviewed: 2026-11-02
review_status: reviewed by team against sources
---

# Docker: permission denied on the daemon socket / Cannot connect to the Docker daemon

## Overview

The `docker` command is only a client: it sends requests to the Docker daemon (`dockerd`). On Linux, "the Docker daemon binds to a Unix socket, not a TCP port. By default it's the `root` user that owns the Unix socket, and other users can only access it using `sudo`" [R1]. When the daemon starts, "it creates a Unix socket accessible by members of the `docker` group" [R1]. The daemon reference gives its default location: "By default, a `unix` domain socket (or IPC socket) is created at `/var/run/docker.sock`, requiring either `root` permission, or `docker` group membership" [R5].

Two different errors are often confused:

1. **Permission problem**: the daemon runs, but the current user is not allowed to use its socket. The user is not in the `docker` group, or the group membership has not been reloaded yet [R1].
2. **Connection problem**: `Cannot connect to the Docker daemon. Is 'docker daemon' running on this host?` This "may indicate" that the daemon is not running, or that the client tries to reach a daemon "on a different host, and that host is unreachable" [R2].

## Symptoms

- `docker ps` works with `sudo` but fails without it (team observation; consistent with the socket ownership described in [R1]).
- The permission error refers to the daemon socket, `/var/run/docker.sock` by default [R5].
- The client prints `Cannot connect to the Docker daemon. Is 'docker daemon' running on this host?` [R2].
- After switching from `sudo docker` to plain `docker`: `WARNING: Error loading config file: /home/user/.docker/config.json - stat /home/user/.docker/config.json: permission denied` [R1].
- In CI jobs that run Docker commands, the same errors appear when the job's user cannot reach the daemon (team observation; see `md-gitlab-ci-job-failures`).

## Possible Causes

| Cause | Explanation |
|---|---|
| **User not in the `docker` group** | Only root, or members of `docker`, can use the socket [R1] |
| **Group membership not yet applied** | After `usermod`, you must "log out and log back in so that your group membership is re-evaluated", or use `newgrp docker`. In a VM, a restart may be needed [R1] |
| **Daemon not running** | Start it and try again [R2] |
| **`DOCKER_HOST` points to another daemon** | If `DOCKER_HOST` is set, the client connects to that host; if it is set by mistake, unset it [R2] |
| **Remote daemon unreachable** | Firewall or network outage between the client and the remote host [R2] |
| **`~/.docker` owned by root** | Caused by earlier use of `sudo docker` [R1] |

## Investigation Steps

1. **Ask Docker whether the daemon answers**: `docker info` is "the operating-system independent way to check whether Docker is running" [R2].
2. **Check the service on the host** with the init system, for example `systemctl is-active docker` [R2].
3. **Check which daemon the client targets** by reading `DOCKER_HOST` [R2].
4. **Check your groups**: is `docker` listed for the current session? (Team recommendation: use the `id` command.)
5. **If the error mentions `~/.docker/config.json`**, check the ownership of `~/.docker` [R1].

## Diagnostic Commands

```shell
# Does the client reach a daemon?
docker info

# Is the daemon service active? (systemd hosts)
sudo systemctl is-active docker

# Which daemon is the client configured to use?
env | grep DOCKER_HOST

# Groups of the current user in this session
id

# Is dockerd running?
ps aux | grep dockerd
```

Sources: `docker info`, `systemctl is-active docker`, `env | grep DOCKER_HOST`, checking the `dockerd` process with `ps` [R2]. `id` is a standard Linux command added by the team to display the session's groups.

## Interpretation of Results

| Observation | Meaning | Next step |
|---|---|---|
| `docker info` works with `sudo` only | The daemon runs; the user lacks socket access [R1] | Add the user to the `docker` group, then re-login [R1] |
| `id` does not list `docker`, although `usermod` was run | The session has not re-evaluated group membership [R1] | Log out and back in, or run `newgrp docker` [R1] |
| `systemctl is-active docker` is not `active` | The daemon is not running [R2] | Start the daemon, then read its logs if it fails (see `md-linux-systemd-service-failure`) |
| `DOCKER_HOST` is set unexpectedly | The client talks to another host [R2] | `unset DOCKER_HOST` and fix `~/.bashrc` or `~/.profile` [R2] |
| `DOCKER_HOST` is correct but the connection fails | Remote daemon down, or network blocked [R2] | Check the remote daemon and the firewall |
| `config.json … permission denied` warning | `~/.docker` was created by `sudo` [R1] | Fix its ownership (see below) |

## Possible Solutions

- **Give a user access to Docker without `sudo`** [R1]:

  ```shell
  sudo groupadd docker          # if the group does not exist yet
  sudo usermod -aG docker $USER
  # log out and log back in (or: newgrp docker), then test:
  docker run hello-world
  ```

- **Fix `~/.docker` ownership** after earlier `sudo` use [R1]:

  ```shell
  sudo chown "$USER":"$USER" /home/"$USER"/.docker -R
  sudo chmod g+rwx "$HOME/.docker" -R
  ```

- **Start the daemon** if it is not running [R2].
- **Unset or fix `DOCKER_HOST`** [R2].
- **Prefer rootless mode** when giving Docker access to users is not acceptable. Rootless mode "lets you run the Docker daemon and containers as a non-root user" [R4].

## Prevention

- Treat membership of the `docker` group as administrative access. The documentation warns that "the `docker` group grants root-level privileges to the user" [R1], and that "only trusted users should be allowed to control your Docker daemon" [R3].
- Do not make the socket world-writable as a shortcut (team recommendation, consistent with [R1, R3]).
- Use rootless mode, or an on-demand Docker-enabled shell, for single-user workstations where ambient access to the socket should be limited [R1, R4].

## Related Concepts

- **Daemon not starting**: see `md-linux-systemd-service-failure`.
- **Docker in CI runners**: see `md-gitlab-ci-job-failures`.
- **Containers that start and stop again**: see `md-docker-container-exits`.

## References

All pages were consulted on 2026-11-02, in their current version, and checked against their sources in the `docker/docs` repository.

- [R1] Docker Docs — *Linux post-installation steps for Docker Engine*. https://docs.docker.com/engine/install/linux-postinstall/
- [R2] Docker Docs — *Troubleshooting the Docker daemon*. https://docs.docker.com/engine/daemon/troubleshoot/
- [R3] Docker Docs — *Docker Engine security*. https://docs.docker.com/engine/security/
- [R4] Docker Docs — *Rootless mode*. https://docs.docker.com/engine/security/rootless/
- [R5] Docker Docs — *dockerd* (consulted on 2026-11-11). https://docs.docker.com/reference/cli/dockerd/

## Metadata

- **Nature of this document:** written by the project team from the official Docker documentation listed above. It is **not** official Docker documentation.
- **Verification:** each statement followed by a reference was checked against the source text. Statements marked "team observation" or "team recommendation" are our own reasoning.
- **Scope limits:** Docker Desktop (macOS, Windows) manages the daemon differently; this guide targets Docker Engine on Linux. The exact wording of the "permission denied" message is not quoted from the documentation; it is listed in `keywords` only. On 2026-11-11 it was searched again in [R1], [R2], [R3] and in GitLab's *Use Docker to build Docker images* page, without success.
