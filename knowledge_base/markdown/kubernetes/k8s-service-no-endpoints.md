---
doc_id: md-k8s-service-no-endpoints
title: Kubernetes Service Not Reachable (no endpoints, selector or port mismatch, readiness)
domain: kubernetes
technology: [kubernetes, kubectl, kube-proxy, coredns]
category: networking
document_type: troubleshooting_guide
difficulty: intermediate
keywords:
  - Service unreachable
  - no endpoints
  - EndpointSlice
  - label selector mismatch
  - targetPort
  - readiness probe
  - kube-proxy
  - NetworkPolicy
  - ClusterIP
error_messages:
  - "ENDPOINTS <none>"
  - "unable to resolve host address"
  - "Error from server (NotFound): services"
source_type: team_written_from_official_docs
language: en
references:
  - id: R1
    title: "Debug Services"
    publisher: Kubernetes Documentation
    url: https://kubernetes.io/docs/tasks/debug/debug-application/debug-service/
    accessed: 2026-11-02
  - id: R2
    title: "Pod Lifecycle (section: Readiness probe)"
    publisher: Kubernetes Documentation
    url: https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/
    accessed: 2026-11-02
  - id: R3
    title: "Service"
    publisher: Kubernetes Documentation
    url: https://kubernetes.io/docs/concepts/services-networking/service/
    accessed: 2026-11-02
related_corpus_documents:
  - doc_id: pdf-container-networking-docker-kubernetes
    pages: "37-46 (ch. 5 Service Discovery), from 53 (ch. 7 Kubernetes Networking)"
  - doc_id: pdf-o-reilly-kubernetes-up-and-running
    pages: "from 95 (ch. 7 Service Discovery)"
last_reviewed: 2026-11-02
review_status: reviewed by team against sources
---

# Kubernetes Service Not Reachable (no endpoints, selector or port mismatch, readiness)

## Overview

A Kubernetes Service gives a stable name and IP address to a set of Pods chosen by a **label selector**. "Inside the Kubernetes system is a control loop which evaluates the selector of every Service and saves the results into one or more EndpointSlice objects" [R1]. If that list is empty, the Service has nowhere to send traffic.

The official *Debug Services* guide follows a fixed order, and this guide reuses it [R1]:

1. Does the Service exist?
2. Does it work by DNS name?
3. Does it work by IP?
4. Is it defined correctly?
5. Does it have EndpointSlices?
6. Are the Pods working?
7. Is kube-proxy working?

Stopping at the first failing check usually points to the cause.

## Symptoms

- Clients cannot reach the application through the Service name or ClusterIP: timeouts, connection refused, or errors from an ingress or load balancer in front of it.
- `kubectl get endpointslices -l kubernetes.io/service-name=<service>` shows `<none>` in the `ENDPOINTS` column [R1].
- From a Pod, `wget -O- <service>` fails with `unable to resolve host address` when the Service does not exist or DNS fails [R1].
- `kubectl get svc <service>` returns `Error from server (NotFound): services "<service>" not found` when the Service was never created [R1].

## Possible Causes

| Cause | Explanation |
|---|---|
| **Service missing** or created in another namespace | The first check of the official guide is whether the Service exists [R1] |
| **Selector does not match the Pod labels** | "A common mistake is to have a typo or other error, such as the Service selecting for `app=hostnames`, but the Deployment specifying `run=hostnames`" [R1] |
| **Wrong `targetPort`** | "Some Pods use a different port than the Service". A number written as a string (`"9376"`) or a named port that the Pods do not expose also breaks the mapping [R1] |
| **Wrong protocol** | The port's `protocol` must be correct for the Pods [R1] |
| **Pods not Ready** | When a readiness probe fails, the EndpointSlice controller removes the Pod's IP from the EndpointSlices of all matching Services [R2] |
| **Pods crashing or restarting** | Frequent restarts "could lead to intermittent connectivity issues" [R1] |
| **NetworkPolicy ingress rules** | Rules that affect incoming traffic to the target Pods must be reviewed [R1] |
| **DNS problem** | The Service exists, but its name does not resolve [R1] (see `md-net-dns-resolution-failure`) |
| **kube-proxy problem** | Service, EndpointSlices and Pods are fine, but traffic to the ClusterIP is not forwarded [R1] |

## Investigation Steps

1. **Check that the Service exists** in the expected namespace [R1].
2. **Test DNS from a Pod**: the short name, then `<service>.<namespace>`, then the fully qualified name `<service>.<namespace>.svc.cluster.local` [R1].
3. **Test the ClusterIP directly** from a Pod. If IP works but the name does not, the problem is DNS [R1].
4. **Read the Service definition back** and verify `spec.ports[]`, `targetPort`, the protocol and `selector` [R1].
5. **List the EndpointSlices.** If the list is empty, compare `spec.selector` with the Pods' `metadata.labels` [R1].
6. **Check the Pods behind the Service**: are they `Running`, `Ready`, and stable (few restarts)? Then call each Pod IP directly on the **Pod port** [R1].
7. **Review NetworkPolicies** in the namespace [R1].
8. **If everything above is correct**, check that kube-proxy is running on the nodes and proxying traffic [R1].

## Diagnostic Commands

```shell
# Temporary Pod with a shell, to test from inside the cluster
kubectl run -it --rm --restart=Never busybox --image=registry.k8s.io/busybox:1.27.2 sh

# 1. Does the Service exist?
kubectl get svc <service> -n <namespace>

# 2. DNS (run from the test Pod)
nslookup <service>
nslookup <service>.<namespace>
nslookup <service>.<namespace>.svc.cluster.local

# 3. Access by ClusterIP (from the test Pod)
wget -qO- <cluster-ip>:<port>

# 4. Service definition: ports, targetPort, protocol, selector
kubectl get service <service> -n <namespace> -o json

# 5. EndpointSlices built from the selector
kubectl get endpointslices -n <namespace> -l kubernetes.io/service-name=<service>

# 6. Pods selected by the same labels as the Service
kubectl get pods -n <namespace> -l <key>=<value>

# 6b. Bypass the Service: call a Pod IP on the Pod port (from the test Pod)
wget -qO- <pod-ip>:<target-port>
```

Sources: all commands come from the official *Debug Services* guide [R1]; the `-n <namespace>` flags are our adaptation.

## Interpretation of Results

| Observation | Meaning | Next step |
|---|---|---|
| `kubectl get svc` returns NotFound | The Service does not exist in this namespace [R1] | Create it, or use the right namespace |
| `nslookup` fails for every form of the name | DNS problem [R1] | See `md-net-dns-resolution-failure`; check whether `kubernetes.default` resolves [R1] |
| The name fails but the ClusterIP works | DNS problem only [R1] | Same as above |
| `ENDPOINTS` is `<none>` | The selector does not select Ready Pods [R1, R2] | Compare the selector with the labels; check readiness |
| Pods listed with the selector are `0/1` Ready | Readiness probe failing: the Pods are removed from the endpoints [R2] | Fix the application or the probe |
| A Pod IP answers on the Pod port, but the Service does not | Port mapping error (`port`/`targetPort`) or proxying problem [R1] | Check `targetPort`, then kube-proxy |
| A Pod IP does not answer on the Pod port | The application itself is not serving [R1] | See `md-k8s-crashloopbackoff`, or check the container's listening port |

## Possible Solutions

- **Fix the selector or the Pod labels** so that they match exactly [R1].
- **Fix `targetPort`**: it must be the port on which the container listens. Use a number, not a string, unless you deliberately use a named port that the Pods define [R1].
- **Fix readiness**: a Pod that is not Ready receives no traffic through Services [R2]. Fix the application or the readiness probe.
- **Review NetworkPolicies** that block ingress to the Pods [R1].
- **Repair DNS or kube-proxy** if the earlier checks pass [R1].

## Prevention

- Use the same labels in the Deployment template and in the Service selector, defined in a single place, for example a Helm value or a kustomize label (team recommendation).
- Use named ports consistently in Pods and Services [R1, R3].
- Define readiness probes that reflect the real ability to serve traffic, so that endpoints only contain healthy Pods [R2].

## Related Concepts

- **Service, selectors and EndpointSlices**: [R3].
- **Readiness vs liveness**: readiness controls traffic; liveness controls restarts [R2]. See `md-k8s-crashloopbackoff`.
- **Errors seen by clients in front of the Service** (HTTP 502/503/504 from an ingress or load balancer): see `md-net-http-502-503-504`.
- **Connection refused vs timeout**: see `md-net-connection-refused-timeout`.
- Corpus: *Container Networking: From Docker to Kubernetes*, ch. 5 *Service Discovery* (PDF pp. 37-46) and ch. 7 *Kubernetes Networking* (from PDF p. 53); *Kubernetes: Up and Running*, ch. 7 *Service Discovery* (from PDF p. 95).

## References

All pages were consulted on 2026-11-02, in their current version, and checked against the documentation source in the `kubernetes/website` repository.

- [R1] Kubernetes Documentation — *Debug Services*. https://kubernetes.io/docs/tasks/debug/debug-application/debug-service/
- [R2] Kubernetes Documentation — *Pod Lifecycle*. https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/
- [R3] Kubernetes Documentation — *Service*. https://kubernetes.io/docs/concepts/services-networking/service/

## Metadata

- **Nature of this document:** written by the project team from the official Kubernetes documentation listed above. It is **not** official Kubernetes documentation.
- **Verification:** each statement followed by a reference was checked against the source text. Statements marked "team recommendation" are our own reasoning.
- **Scope limits:** kube-proxy internals (iptables/IPVS rules) are not detailed here; follow the "Is the kube-proxy working?" section of [R1].
