---
doc_id: md-net-connection-refused-timeout
title: Connection Refused vs Connection Timed Out
domain: networking
technology: [tcp, linux, curl]
category: connectivity
document_type: troubleshooting_guide
difficulty: beginner
keywords:
  - connection refused
  - ECONNREFUSED
  - connection timed out
  - ETIMEDOUT
  - no one listening
  - TCP reset RST
  - firewall drop
  - port not open
  - listening socket
  - 127.0.0.1 loopback
  - ss -tlnp
  - curl --connect-timeout
error_messages:
  - "Connection refused"
  - "Connection timed out"
  - "Failed to connect() to host or proxy"
  - "Network is unreachable"
source_type: team_written_from_official_docs
language: en
references:
  - id: R1
    title: "connect(2) — Linux manual page (ERRORS)"
    publisher: man7.org (Linux man-pages project)
    url: https://man7.org/linux/man-pages/man2/connect.2.html
    accessed: 2026-11-02
  - id: R2
    title: "RFC 9293 — Transmission Control Protocol (TCP), section 3.5.2 Reset Generation"
    publisher: IETF
    url: https://www.rfc-editor.org/rfc/rfc9293
    accessed: 2026-11-02
  - id: R3
    title: "ss(8) — Linux manual page"
    publisher: man7.org (Linux man-pages project)
    url: https://man7.org/linux/man-pages/man8/ss.8.html
    accessed: 2026-11-02
  - id: R4
    title: "libcurl error codes (CURLE_COULDNT_CONNECT, CURLE_OPERATION_TIMEDOUT)"
    publisher: curl project
    url: https://curl.se/libcurl/c/libcurl-errors.html
    accessed: 2026-11-02
  - id: R5
    title: "curl man page (--connect-timeout, --resolve)"
    publisher: curl project
    url: https://curl.se/docs/manpage.html
    accessed: 2026-11-02
  - id: R6
    title: "RFC 1122 — Requirements for Internet Hosts, section 3.2.1.3 (loopback addresses)"
    publisher: IETF
    url: https://www.rfc-editor.org/rfc/rfc1122
    accessed: 2026-11-02
  - id: R7
    title: "Troubleshoot issues connecting to your Amazon EC2 Linux instance (Connection timed out)"
    publisher: AWS Documentation
    url: https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/TroubleshootingInstancesConnecting.html
    accessed: 2026-11-02
last_reviewed: 2026-11-02
review_status: reviewed by team against sources
---

# Connection Refused vs Connection Timed Out

## Overview

When a client opens a TCP connection, two very different failures can appear. Telling them apart is the first and most useful step of the diagnosis.

- **Connection refused** (`ECONNREFUSED`): "A connect() on a stream socket found no one listening on the remote address" [R1]. The target host was reached and answered immediately. In TCP, when no connection exists for the incoming segment, "a reset is sent in response to any incoming segment except another reset. A SYN segment that does not match an existing connection is rejected by this means" [R2].
- **Connection timed out** (`ETIMEDOUT`): "Timeout while attempting connection. The server may be too busy to accept new connections" [R1]. The client never got an answer. In practice this often means that packets are dropped on the way, for example by a firewall rule, a security group or a missing route (team inference). The AWS documentation lists exactly these checks for a "Connection timed out" error on EC2 [R7].

A third error, `ENETUNREACH` ("Network is unreachable"), means that the local system has no route to the destination network [R1].

In short: *refused* means "the host answered, but nothing listens on that port"; *timed out* means "nothing answered".

## Symptoms

- `curl` fails with error 7, `CURLE_COULDNT_CONNECT` ("Failed to connect() to host or proxy"), or with error 28, `CURLE_OPERATION_TIMEDOUT` ("Operation timeout") [R4].
- Application logs show `Connection refused` immediately, or `Connection timed out` after a long wait [R1].
- A refused connection fails fast; a timed-out connection hangs until the client gives up (team observation; the waiting time depends on client settings such as `--connect-timeout` [R5]).

## Possible Causes

| Error | Possible causes |
|---|---|
| **Connection refused** | The service is not running or crashed; it listens on a different port; it listens only on the loopback address `127.0.0.1` while the client comes from another host (loopback addresses "MUST NOT appear outside a host" [R6]); the client uses the wrong port [R1, R2] |
| **Connection timed out** | A firewall or security group drops the packets; no route to the target (missing internet gateway or route table entry); a network ACL blocks the traffic or its return path; the server is overloaded [R1, R7] |
| **Network is unreachable** | No route to the destination network on the client [R1] |

In container platforms, "refused" also appears when a port is published or forwarded but no process listens behind it (team inference; see `md-docker-networking-ports` and `md-k8s-service-no-endpoints`).

## Investigation Steps

1. **Read the exact error**: refused, timed out, or unreachable. Each one points to a different layer [R1].
2. **Check name resolution first.** Make sure you are connecting to the expected IP address (see `md-net-dns-resolution-failure`). You can force an address with `curl --resolve` to test a specific server [R5].
3. **For "refused", go to the server**: list the listening TCP sockets and their processes. Check that the expected port is open and on which address it listens (`0.0.0.0`/`::` for all interfaces, or `127.0.0.1` only) [R3, R6].
4. **For "timed out", follow the path**: local firewall, cloud security groups, network ACLs, routes, then server load [R7].
5. **Test from several places** (same host, same network, outside) to locate the point where the connection stops working (team recommendation).

## Diagnostic Commands

```shell
# On the server: listening TCP sockets, numeric ports, owning process
ss -t -l -n -p

# On the server: all TCP sockets (listening and established)
ss -t -a

# From the client: verbose connection attempt with a bounded wait
curl -v --connect-timeout 5 http://10.0.1.20:8080/

# From the client: force a hostname to a given address (bypass DNS for the test)
curl -v --resolve api.example.com:443:10.0.1.20 https://api.example.com/
```

Sources: `ss` options `-t`, `-l`, `-n`, `-p`, `-a` [R3]; curl `--connect-timeout` and `--resolve` [R5]. The `-v` (verbose) option of curl is used here to display the connection attempt.

## Interpretation of Results

| Observation | Meaning | Next step |
|---|---|---|
| curl fails at once with "Connection refused" | Host reached, no listener on that port [R1, R2] | Start the service or fix the port |
| `ss -tlnp` does not show the port | Nothing listens on the server [R3] | Check that the service runs; see `md-linux-systemd-service-failure` |
| `ss -tlnp` shows `127.0.0.1:<port>` only | The service only accepts local connections [R6] | Make it listen on the right interface |
| curl waits, then "timed out" | No answer: packets dropped or no route, or server overloaded [R1, R7] | Check firewall, security group, network ACL, routes |
| It works from the server itself but not from outside | Local listener is fine; something between client and server blocks traffic (team inference) | Check the network path and the listening address |
| "Network is unreachable" | No route on the client side [R1] | Check routing and VPN on the client |

## Possible Solutions

- **Refused**: start or restart the service, correct the port in the client or the server configuration, and make the service listen on an address reachable by the client [R1, R3, R6].
- **Timed out**: open the port in the host firewall and in the cloud security group, from the correct source addresses. Fix the network ACL, including outbound traffic to ephemeral ports, and the route table [R7].
- **Overloaded server**: check CPU load and scale the service if needed [R7].

## Prevention

- Document which port and address each service listens on, and check it in deployment tests (team recommendation).
- Use short connection timeouts in clients so that failures are reported quickly instead of hanging [R5].
- Keep firewall and security group rules in version control, for example with infrastructure as code, so that changes are traceable (team recommendation).

## Related Concepts

- **DNS before TCP**: see `md-net-dns-resolution-failure`.
- **HTTP errors from proxies when the upstream refuses or times out**: see `md-net-http-502-503-504`.
- **TLS errors after the TCP connection succeeds**: see `md-net-tls-certificate-errors`.
- **AWS-specific checks** (security groups, network ACLs, internet gateway): see `md-aws-ec2-unreachable`.

## References

All pages were consulted on 2026-11-02, in their current version.

- [R1] Linux man-pages — *connect(2)*. https://man7.org/linux/man-pages/man2/connect.2.html
- [R2] IETF — RFC 9293, *Transmission Control Protocol (TCP)*, section 3.5.2. https://www.rfc-editor.org/rfc/rfc9293
- [R3] Linux man-pages — *ss(8)*. https://man7.org/linux/man-pages/man8/ss.8.html
- [R4] curl project — *libcurl error codes*. https://curl.se/libcurl/c/libcurl-errors.html
- [R5] curl project — *curl man page*. https://curl.se/docs/manpage.html
- [R6] IETF — RFC 1122, *Requirements for Internet Hosts — Communication Layers*, section 3.2.1.3. https://www.rfc-editor.org/rfc/rfc1122
- [R7] AWS Documentation — *Troubleshoot issues connecting to your Amazon EC2 Linux instance*. https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/TroubleshootingInstancesConnecting.html

## Metadata

- **Nature of this document:** written by the project team from the official sources listed above. It is **not** official documentation of any of these projects.
- **Verification:** each statement followed by a reference was checked against the source text. Statements marked "team observation", "team inference" or "team recommendation" are our own reasoning.
- **Scope limits:** UDP has no connection setup and behaves differently; this guide covers TCP only.
