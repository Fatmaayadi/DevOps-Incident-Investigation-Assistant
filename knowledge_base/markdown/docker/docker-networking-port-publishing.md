---
doc_id: md-docker-networking-ports
title: "Docker Networking: published port not reachable, containers cannot reach each other, DNS in containers"
domain: docker
technology: [docker, docker-networking, dns]
category: networking
document_type: troubleshooting_guide
difficulty: intermediate
keywords:
  - port not reachable
  - docker run -p
  - publish port
  - port mapping
  - 127.0.0.1 binding
  - app listens on localhost inside container
  - default bridge network
  - user-defined bridge
  - container name resolution
  - embedded DNS 127.0.0.11
  - --link legacy
  - resolv.conf in container
  - dnsmasq
  - docker port
  - docker network inspect
error_messages:
  - "WARNING: Local (127.0.0.1) DNS resolver found in resolv.conf and containers can't use it."
source_type: team_written_from_official_docs
language: en
references:
  - id: R1
    title: "Port publishing and mapping"
    publisher: Docker Docs
    url: https://docs.docker.com/engine/network/port-publishing/
    accessed: 2026-11-02
  - id: R2
    title: "Bridge network driver (Differences between user-defined bridges and the default bridge)"
    publisher: Docker Docs
    url: https://docs.docker.com/engine/network/drivers/bridge/
    accessed: 2026-11-02
  - id: R3
    title: "Networking overview (DNS services)"
    publisher: Docker Docs
    url: https://docs.docker.com/engine/network/
    accessed: 2026-11-02
  - id: R4
    title: "Troubleshooting the Docker daemon (DNS resolver issues)"
    publisher: Docker Docs
    url: https://docs.docker.com/engine/daemon/troubleshoot/
    accessed: 2026-11-02
  - id: R5
    title: "docker container port — reference"
    publisher: Docker Docs (docker/cli reference)
    url: https://docs.docker.com/reference/cli/docker/container/port/
    accessed: 2026-11-02
  - id: R6
    title: "docker network inspect — reference"
    publisher: Docker Docs (docker/cli reference)
    url: https://docs.docker.com/reference/cli/docker/network/inspect/
    accessed: 2026-11-02
  - id: R7
    title: "RFC 1122 — Requirements for Internet Hosts, section 3.2.1.3 (loopback addresses)"
    publisher: IETF
    url: https://www.rfc-editor.org/rfc/rfc1122
    accessed: 2026-11-02
related_corpus_documents:
  - doc_id: pdf-container-networking-docker-kubernetes
    pages: "15-22 (ch. 2 Introduction to Container Networking)"
last_reviewed: 2026-11-02
review_status: reviewed by team against sources
---

# Docker Networking: published port not reachable, containers cannot reach each other, DNS in containers

## Overview

On a Docker host, each container on a bridge network has its own network namespace and IP address. Three rules explain most networking incidents:

1. **Ports are private unless published.** "All ports of containers on bridge networks are accessible from the Docker host and other containers connected to the same network. Ports are not accessible from outside the host" unless they are published with `-p`/`--publish` [R1]. For example, `-p 8080:80` maps port 8080 on the host to port 80 in the container [R1].
2. **Name resolution between containers needs a user-defined network.** "User-defined bridges provide automatic DNS resolution between containers". On the default bridge, containers can only reach each other by IP address, unless the legacy `--link` option is used [R2].
3. **`127.0.0.1` inside a container is the container itself.** A container "uses its own network namespace, and resolves loopback addresses such as `127.0.0.1` to itself" [R4].

## Symptoms

- `curl http://<host>:8080` fails although the container is running (team observation).
- A container cannot reach another one by name, for example the `web` container cannot resolve `db` (team observation, consistent with [R2]).
- Docker prints `WARNING: Local (127.0.0.1) DNS resolver found in resolv.conf and containers can't use it.`, and containers cannot resolve internal hostnames [R4].
- A port published only on `127.0.0.1` works from the host itself but not from other machines [R1].

## Possible Causes

| Cause | Explanation |
|---|---|
| **Port not published** | Without `-p`, ports are not reachable from outside the host [R1] |
| **Wrong port mapping** | `-p HOST:CONTAINER`: the second number must be the port the application listens on inside the container [R1] |
| **Published only on localhost** | With `-p 127.0.0.1:8080:80`, only the Docker host can access the port [R1] |
| **Application listening on `127.0.0.1` inside the container** | Loopback addresses stay inside a host [R7]. A container's loopback is its own [R4], so traffic arriving through the published port does not reach an application bound only to loopback (team inference) |
| **Containers on the default bridge, addressed by name** | No automatic DNS on the default bridge [R2] |
| **Containers on different networks** | With the default configuration, ports are not accessible "from containers in other networks" [R1] |
| **Host DNS resolver on a loopback address** (for example `dnsmasq`) | Containers cannot use a resolver at `127.0.0.1` on the host [R4] |
| **Host port already used by another process** | The mapping cannot be created on that host port (team inference; check with `ss -tlnp`, see `md-net-connection-refused-timeout`) |

## Investigation Steps

1. **Check the published ports** of the container: which host address and port map to which container port [R5].
2. **Check on which address the application listens inside the container**: `0.0.0.0` (all interfaces) or `127.0.0.1` only (team recommendation; see `md-net-connection-refused-timeout`).
3. **Test from the host** with the published host port, then from another machine. This separates a mapping problem from a host firewall or binding problem [R1].
4. **For container-to-container problems**, check which networks the containers are attached to [R6]. Use a user-defined network if they must reach each other by name [R2].
5. **For DNS problems inside containers**, read the Docker warning about local resolvers and check whether the host uses `dnsmasq` [R4]. Containers on custom networks use the embedded DNS server at `127.0.0.11` [R3].

## Diagnostic Commands

```shell
# Port mappings of a container
docker port <container>
docker ps                      # PORTS column, e.g. 0.0.0.0:8080->80/tcp

# Networks and attached containers (with their IP addresses)
docker network ls
docker network inspect <network>

# Create a user-defined bridge and attach containers to it
docker network create -d bridge my-net
docker run -d --name db --network my-net <db-image>
docker run -d --name web --network my-net -p 8080:80 <web-image>

# Host DNS resolver check (dnsmasq on loopback)
ps aux | grep dnsmasq
```

Sources: `docker port` [R5]; `docker network inspect` [R6]; `docker network create -d bridge my-net` [R3]; `-p` syntax [R1]; `ps aux | grep dnsmasq` [R4]. `docker network ls` and `--network` are standard Docker CLI usage selected by the team.

## Interpretation of Results

| Observation | Meaning | Next step |
|---|---|---|
| `docker port` prints nothing | No port is published [R1, R5] | Recreate the container with `-p` |
| Mapping shows `127.0.0.1:8080->80/tcp` | Only the host can reach it [R1] | Publish on the right host address |
| Mapping is correct, but the request fails even from the host | The application may not listen on the container port, or listens on loopback only (team inference, [R4, R7]) | Make the application listen on `0.0.0.0` and the mapped port |
| Containers are on `bridge` (default) and use names | No automatic DNS on the default bridge [R2] | Put them on a user-defined network [R2] |
| `docker network inspect` shows the containers on different networks | They cannot reach each other by default [R1] | Attach them to a common network |
| Docker warns about a local `127.0.0.1` resolver | Containers cannot use the host's loopback DNS [R4] | Specify DNS servers for Docker, or turn off `dnsmasq` [R4] |

## Possible Solutions

- **Publish the port correctly**: `-p <host-port>:<container-port>`, optionally with a host IP [R1].
- **Bind the application to all interfaces inside the container** (`0.0.0.0`), not to `127.0.0.1` (team recommendation based on [R4, R7]).
- **Use a user-defined bridge network** for containers that must talk to each other by name. On such a network, a `web` container can connect to `db` by name [R2].
- **Fix DNS on hosts with a loopback resolver**: either specify DNS servers for Docker, or turn off `dnsmasq`. Only one of the two is needed [R4]. A container's DNS servers can also be overridden with `--dns` [R3].

## Prevention

- Publish ports on `127.0.0.1` when they only need local access. Publishing is "insecure by default": a published port is available "to the outside world as well" [R1].
- Use one user-defined network per application stack instead of the default bridge [R2].
- Document the listening port of each image, and test the mapping in CI (team recommendation).

## Related Concepts

- **Refused vs timed-out connections**: see `md-net-connection-refused-timeout`.
- **DNS failures in general**: see `md-net-dns-resolution-failure`.
- **Kubernetes Services, the orchestrated equivalent**: see `md-k8s-service-no-endpoints`.
- Corpus: *Container Networking: From Docker to Kubernetes*, ch. 2 (PDF pp. 15-22).

## References

All pages were consulted on 2026-11-02, in their current version, and checked against their sources in the `docker/docs` and `docker/cli` repositories.

- [R1] Docker Docs — *Port publishing and mapping*. https://docs.docker.com/engine/network/port-publishing/
- [R2] Docker Docs — *Bridge network driver*. https://docs.docker.com/engine/network/drivers/bridge/
- [R3] Docker Docs — *Networking overview*. https://docs.docker.com/engine/network/
- [R4] Docker Docs — *Troubleshooting the Docker daemon*. https://docs.docker.com/engine/daemon/troubleshoot/
- [R5] Docker Docs — *docker container port*. https://docs.docker.com/reference/cli/docker/container/port/
- [R6] Docker Docs — *docker network inspect*. https://docs.docker.com/reference/cli/docker/network/inspect/
- [R7] IETF — RFC 1122, section 3.2.1.3. https://www.rfc-editor.org/rfc/rfc1122

## Metadata

- **Nature of this document:** written by the project team from the official sources listed above. It is **not** official Docker documentation.
- **Verification:** each statement followed by a reference was checked against the source text. Statements marked "team observation", "team inference" or "team recommendation" are our own reasoning.
- **Scope limits:** Docker Desktop, IPv6-only setups and overlay (Swarm) networks are not covered. The exact error message for a host port already in use is not quoted, because it is not in the cited documentation.
