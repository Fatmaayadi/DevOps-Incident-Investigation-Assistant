---
doc_id: md-net-dns-resolution-failure
title: DNS Resolution Failure (application cannot resolve a hostname)
domain: networking
technology: [dns, linux, kubernetes, coredns]
category: name-resolution
document_type: troubleshooting_guide
difficulty: intermediate
keywords:
  - DNS resolution failure
  - cannot resolve hostname
  - could not resolve host
  - temporary failure in name resolution
  - name or service not known
  - NXDOMAIN
  - SERVFAIL
  - resolv.conf
  - nsswitch.conf
  - /etc/hosts
  - search domain
  - ndots
  - CoreDNS
  - kube-dns
error_messages:
  - "Could not resolve host"
  - "nslookup: can't resolve"
  - "unable to resolve host address"
  - "Temporary failure in name resolution"
  - "Name or service not known"
source_type: team_written_from_official_docs
language: en
references:
  - id: R1
    title: "RFC 1035 — Domain Names: Implementation and Specification (section 4.1.1, RCODE)"
    publisher: IETF
    url: https://www.rfc-editor.org/rfc/rfc1035
    accessed: 2026-11-02
  - id: R2
    title: "resolv.conf(5) — Linux manual page"
    publisher: man7.org (Linux man-pages project)
    url: https://man7.org/linux/man-pages/man5/resolv.conf.5.html
    accessed: 2026-11-02
  - id: R3
    title: "getaddrinfo(3) — Linux manual page (RETURN VALUE)"
    publisher: man7.org (Linux man-pages project)
    url: https://man7.org/linux/man-pages/man3/getaddrinfo.3.html
    accessed: 2026-11-02
  - id: R4
    title: "getent(1) — Linux manual page"
    publisher: man7.org (Linux man-pages project)
    url: https://man7.org/linux/man-pages/man1/getent.1.html
    accessed: 2026-11-02
  - id: R5
    title: "nsswitch.conf(5) — Linux manual page"
    publisher: man7.org (Linux man-pages project)
    url: https://man7.org/linux/man-pages/man5/nsswitch.conf.5.html
    accessed: 2026-11-02
  - id: R6
    title: "BIND 9 manual pages — dig"
    publisher: Internet Systems Consortium
    url: https://bind9.readthedocs.io/en/latest/manpages.html
    accessed: 2026-11-02
  - id: R7
    title: "libcurl error codes (CURLE_COULDNT_RESOLVE_HOST)"
    publisher: curl project
    url: https://curl.se/libcurl/c/libcurl-errors.html
    accessed: 2026-11-02
  - id: R8
    title: "Debugging DNS Resolution"
    publisher: Kubernetes Documentation
    url: https://kubernetes.io/docs/tasks/administer-cluster/dns-debugging-resolution/
    accessed: 2026-11-02
  - id: R9
    title: "Debug Services (section: Does the Service work by DNS name?)"
    publisher: Kubernetes Documentation
    url: https://kubernetes.io/docs/tasks/debug/debug-application/debug-service/
    accessed: 2026-11-02
  - id: R10
    title: "Domain Name System (DNS) Parameters — DNS RCODEs registry"
    publisher: IANA
    url: https://www.iana.org/assignments/dns-parameters/dns-parameters.xhtml
    accessed: 2026-11-02
  - id: R11
    title: "GNU C Library source, sysdeps/posix/gai_strerror-strs.h (messages of gai_strerror)"
    publisher: GNU C Library (glibc) project
    url: https://sourceware.org/git/?p=glibc.git;a=blob;f=sysdeps/posix/gai_strerror-strs.h
    accessed: 2026-11-11
related_corpus_documents:
  - doc_id: pdf-container-networking-docker-kubernetes
    pages: "37-46 (ch. 5 Service Discovery)"
last_reviewed: 2026-11-02
review_status: reviewed by team against sources
---

# DNS Resolution Failure (application cannot resolve a hostname)

## Overview

Before an application can open a connection to `db.example.internal` or `my-service`, the name must be translated into an IP address. On Linux, applications usually call `getaddrinfo(3)`. The order of the sources consulted (`/etc/hosts`, DNS, …) is defined in `/etc/nsswitch.conf` [R5], and the DNS servers and search domains come from `/etc/resolv.conf` [R2].

A DNS failure has very different causes depending on **what the DNS server answered**:

- **The name does not exist**: response code 3, "Name Error" in RFC 1035, registered by IANA under the name `NXDomain` [R1, R10]. An authoritative server says "the domain name referenced in the query does not exist" [R1].
- **The server failed**: response code 2, `ServFail` [R1, R10]. The name server "was unable to process this query due to a problem with the name server" [R1].
- **The server refused**: response code 5, `Refused` [R1, R10].
- **No answer at all** within the timeout. This is a network or server reachability problem, not a missing record (team inference).

At the application level, `getaddrinfo` distinguishes a temporary failure (`EAI_AGAIN`, "The name server returned a temporary failure indication. Try again later."), a permanent failure (`EAI_FAIL`), and an unknown name (`EAI_NONAME`, "The node or service is not known") [R3]. Applications usually print the text that the C library associates with these codes. In the GNU C Library, `EAI_AGAIN` is "Temporary failure in name resolution", `EAI_NONAME` is "Name or service not known", and `EAI_FAIL` is "Non-recoverable failure in name resolution" [R11].

## Symptoms

- `curl` fails with error 6, `CURLE_COULDNT_RESOLVE_HOST`: "Could not resolve host. The given remote host was not resolved" [R7].
- In a Kubernetes Pod: `nslookup: can't resolve 'kubernetes.default'` [R8], or `wget: unable to resolve host address` for a Service name [R9].
- On systems using the GNU C Library, application logs show `Temporary failure in name resolution` (`EAI_AGAIN`) or `Name or service not known` (`EAI_NONAME`) [R3, R11].
- Application logs report that the database or API hostname cannot be resolved, often right after a configuration change, a new environment, or a move to containers (team observation).

## Possible Causes

| Cause | Explanation |
|---|---|
| **Typo or wrong name** | The record really does not exist: `NXDOMAIN` [R1] |
| **Short name expanded with the wrong search domain** | Names with fewer dots than `ndots` (default 1) are tried with each entry of the `search` list [R2]. In Kubernetes, a Service in another namespace needs `<service>.<namespace>` [R9] |
| **Wrong or unreachable `nameserver`** in `/etc/resolv.conf` | The resolver queries the listed servers (up to 3) [R2] |
| **Name present in `/etc/hosts` on one machine only**, or `nsswitch.conf` order | `getaddrinfo` follows `nsswitch.conf`, which can include `files` (`/etc/hosts`) and `dns` [R5] |
| **DNS server failure** | `SERVFAIL` [R1] or temporary failure `EAI_AGAIN` [R3] |
| **Kubernetes DNS service down** | CoreDNS/kube-dns Pods not running, no endpoints, or errors in their logs [R8] |
| **Kubernetes Service missing** | No record exists for a Service that was never created [R9] |

## Investigation Steps

1. **Reproduce from the same place as the failing application**: same host, same container or same Pod. Resolution depends on the local `resolv.conf` and `nsswitch.conf` [R2, R5].
2. **Read `/etc/resolv.conf`**: `nameserver`, `search` and `options` such as `ndots`, `timeout` and `attempts` [R2].
3. **Resolve with the system resolver** using `getent ahosts <name>`, which calls `getaddrinfo` [R4].
4. **Query DNS directly** with `dig <name>`. Without `@server`, dig uses the servers of `/etc/resolv.conf` [R6]. Then query another server explicitly: `dig @<server> <name>`.
5. **Compare the two results.** dig queries DNS servers, while `getent ahosts` goes through `getaddrinfo` and `nsswitch.conf`, which may also read `/etc/hosts` [R4, R5, R6]. A difference points to `/etc/hosts` or `nsswitch.conf`.
6. **Read the response status** in the dig output (`NOERROR`, `NXDOMAIN`, `SERVFAIL`, `REFUSED`), which is the name of the DNS response code [R1, R10].
7. **In Kubernetes**, follow the official order [R8]: test `nslookup kubernetes.default` from a test Pod, check the Pod's `/etc/resolv.conf`, check that the DNS Pods are running, read their logs, check the `kube-dns` Service and its EndpointSlices.

## Diagnostic Commands

```shell
# Local resolver configuration
cat /etc/resolv.conf
grep '^hosts' /etc/nsswitch.conf

# Resolution through getaddrinfo (follows nsswitch.conf, may use /etc/hosts)
getent ahosts db.example.internal

# Direct DNS query using the servers of /etc/resolv.conf, then a specific server
dig db.example.internal
dig @10.0.0.10 db.example.internal A
dig +short db.example.internal

# Kubernetes: test Pod with DNS tools, then checks on the DNS service
kubectl apply -f https://k8s.io/examples/admin/dns/dnsutils.yaml
kubectl exec -i -t dnsutils -- nslookup kubernetes.default
kubectl exec -ti dnsutils -- cat /etc/resolv.conf
kubectl get pods --namespace=kube-system -l k8s-app=kube-dns
kubectl logs --namespace=kube-system -l k8s-app=kube-dns
kubectl get svc --namespace=kube-system
kubectl get endpointslice -l kubernetes.io/service-name=kube-dns --namespace=kube-system
```

Sources: `getent ahosts` [R4]; `dig @server name type` and `+short` [R6]; Kubernetes commands [R8]. Reading `resolv.conf` and the `hosts:` line of `nsswitch.conf` relies on [R2, R5].

## Interpretation of Results

| Observation | Meaning | Next step |
|---|---|---|
| The application reports `Temporary failure in name resolution` | `EAI_AGAIN`: the name server returned a temporary failure [R3, R11] | Check that the `nameserver` entries are reachable and working, then retry |
| The application reports `Name or service not known` | `EAI_NONAME`: the name is not known [R3, R11] | Check the spelling, the search domain and `/etc/hosts` |
| dig status `NXDOMAIN` | The name does not exist on the authoritative server [R1, R10] | Check the spelling, the zone, the search domain |
| dig status `SERVFAIL` | The name server could not process the query [R1] | Check the DNS server and its upstream servers |
| dig status `REFUSED` | The server refuses to answer the query [R1] | Use the correct resolver, or fix its access rules |
| dig times out | No server answered (team inference) | Check network reachability of the `nameserver` IPs; see `md-net-connection-refused-timeout` |
| `getent ahosts` works but `dig` fails, or the opposite | `/etc/hosts` or `nsswitch.conf` gives a different answer than DNS [R4, R5, R6] | Inspect `/etc/hosts` and the `hosts:` line |
| Full name works, short name fails | Search list or `ndots` problem [R2] | Use the fully qualified name, or fix `search` |
| In a Pod, `kubernetes.default` does not resolve | Cluster DNS problem, not an application problem [R8] | Check the DNS Pods, their logs, the `kube-dns` Service and endpoints [R8] |
| `kubernetes.default` resolves but `<service>` does not | The Service does not exist, or it lives in another namespace [R9] | Use `<service>.<namespace>`; see `md-k8s-service-no-endpoints` |

## Possible Solutions

- **Fix the name** in the application configuration, or create the missing record in the right DNS zone.
- **Use fully qualified names** where the search list is ambiguous, for example `<service>.<namespace>.svc.cluster.local` in Kubernetes [R9].
- **Fix `/etc/resolv.conf`**: a reachable `nameserver`, the correct `search` domains, and sensible `timeout`/`attempts` options [R2]. On many systems this file is generated by another tool (team note: change the source of the configuration, not only the file).
- **Remove stale `/etc/hosts` entries** that override DNS, or fix the order in `nsswitch.conf` [R5].
- **Kubernetes**: repair the DNS add-on as shown by the checks in [R8]. Restore the DNS Pods, fix the errors in their logs, and make sure the `kube-dns` Service has endpoints.

## Prevention

- Use one source of truth for names (DNS) rather than hand-edited `/etc/hosts` files (team recommendation).
- Monitor the DNS service itself, for example the DNS Pods and their logs in Kubernetes [R8].
- In applications, treat temporary resolution failures (`EAI_AGAIN`, "Try again later") differently from unknown names (`EAI_NONAME`) [R3]: retry the first, report the second as a configuration error (team recommendation).

## Related Concepts

- **Service discovery in Kubernetes**: see `md-k8s-service-no-endpoints`. Corpus: *Container Networking: From Docker to Kubernetes*, ch. 5 *Service Discovery* (PDF pp. 37-46).
- **After resolution succeeds**, connection errors are a different problem: see `md-net-connection-refused-timeout`.
- **DNS inside Docker containers**: see `md-docker-networking-ports`.

## References

All pages were consulted on 2026-11-02, in their current version.

- [R1] IETF — RFC 1035, *Domain Names — Implementation and Specification*, section 4.1.1. https://www.rfc-editor.org/rfc/rfc1035
- [R2] Linux man-pages — *resolv.conf(5)*. https://man7.org/linux/man-pages/man5/resolv.conf.5.html
- [R3] Linux man-pages — *getaddrinfo(3)*. https://man7.org/linux/man-pages/man3/getaddrinfo.3.html
- [R4] Linux man-pages — *getent(1)*. https://man7.org/linux/man-pages/man1/getent.1.html
- [R5] Linux man-pages — *nsswitch.conf(5)*. https://man7.org/linux/man-pages/man5/nsswitch.conf.5.html
- [R6] ISC — *BIND 9 manual pages*, `dig`. https://bind9.readthedocs.io/en/latest/manpages.html
- [R7] curl project — *libcurl error codes*. https://curl.se/libcurl/c/libcurl-errors.html
- [R8] Kubernetes Documentation — *Debugging DNS Resolution*. https://kubernetes.io/docs/tasks/administer-cluster/dns-debugging-resolution/
- [R9] Kubernetes Documentation — *Debug Services*. https://kubernetes.io/docs/tasks/debug/debug-application/debug-service/
- [R10] IANA — *Domain Name System (DNS) Parameters*, DNS RCODEs. https://www.iana.org/assignments/dns-parameters/dns-parameters.xhtml
- [R11] GNU C Library — source file `sysdeps/posix/gai_strerror-strs.h` (consulted on 2026-11-11 through the read-only GitHub mirror `bminor/glibc`, because the official repository refused automated access). https://sourceware.org/git/?p=glibc.git;a=blob;f=sysdeps/posix/gai_strerror-strs.h

## Metadata

- **Nature of this document:** written by the project team from the official sources listed above (IETF, Linux man-pages, ISC, curl, Kubernetes). It is **not** official documentation of any of these projects.
- **Verification:** each statement followed by a reference was checked against the source text. Statements marked "team inference", "team note" or "team recommendation" are our own reasoning.
- **Scope limits:** the exact error text printed by an application depends on its language and libraries; the `keywords` field lists common wordings to help search, but only the messages in `error_messages` are quoted from the sources.
