---
doc_id: md-k8s-pod-pending-failedscheduling
title: Kubernetes Pod Stuck in Pending (FailedScheduling)
domain: kubernetes
technology: [kubernetes, kubectl, kube-scheduler]
category: scheduling
document_type: troubleshooting_guide
difficulty: intermediate
keywords:
  - Pending
  - FailedScheduling
  - insufficient cpu
  - insufficient memory
  - resource requests
  - allocatable
  - taints and tolerations
  - nodeSelector
  - node affinity
  - hostPort
  - PersistentVolumeClaim unbound
error_messages:
  - "FailedScheduling"
  - "0/42 nodes available: insufficient cpu"
  - "Insufficient memory"
  - "failed to fit in any node"
source_type: team_written_from_official_docs
language: en
references:
  - id: R1
    title: "Debug Pods (section: My pod stays pending)"
    publisher: Kubernetes Documentation
    url: https://kubernetes.io/docs/tasks/debug/debug-application/debug-pods/
    accessed: 2026-11-02
  - id: R2
    title: "Debug Running Pods (section: Example: debugging Pending Pods)"
    publisher: Kubernetes Documentation
    url: https://kubernetes.io/docs/tasks/debug/debug-application/debug-running-pod/
    accessed: 2026-11-02
  - id: R3
    title: "Resource Management for Pods and Containers (sections: How Pods with resource requests are scheduled, Troubleshooting)"
    publisher: Kubernetes Documentation
    url: https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/
    accessed: 2026-11-02
  - id: R4
    title: "Taints and Tolerations"
    publisher: Kubernetes Documentation
    url: https://kubernetes.io/docs/concepts/scheduling-eviction/taint-and-toleration/
    accessed: 2026-11-02
  - id: R5
    title: "Assigning Pods to Nodes (sections: nodeSelector, Affinity and anti-affinity)"
    publisher: Kubernetes Documentation
    url: https://kubernetes.io/docs/concepts/scheduling-eviction/assign-pod-node/
    accessed: 2026-11-02
  - id: R6
    title: "Persistent Volumes (section: Binding)"
    publisher: Kubernetes Documentation
    url: https://kubernetes.io/docs/concepts/storage/persistent-volumes/
    accessed: 2026-11-02
  - id: R7
    title: "Pod Lifecycle (section: Pod phase)"
    publisher: Kubernetes Documentation
    url: https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/
    accessed: 2026-11-02
  - id: R8
    title: "Assign Memory Resources to Containers and Pods (section: Specify a memory request that is too big for your Nodes)"
    publisher: Kubernetes Documentation
    url: https://kubernetes.io/docs/tasks/configure-pod-container/assign-memory-resource/
    accessed: 2026-11-02
related_corpus_documents:
  - doc_id: pdf-o-reilly-kubernetes-patterns
    pages: "35-44 (ch. 2 Predictable Demands)"
last_reviewed: 2026-11-02
review_status: reviewed by team against sources
---

# Kubernetes Pod Stuck in Pending (FailedScheduling)

## Overview

A Pod in the `Pending` phase "has been accepted by the Kubernetes cluster, but one or more of the containers has not been set up and made ready to run". This includes the time spent waiting to be scheduled and the time spent downloading images [R7]. When a Pod **stays** `Pending`, "it means that it can not be scheduled onto a node" [R1].

The scheduler explains its decision in the Pod events, usually with the reason `FailedScheduling` [R2]. The scheduler places a Pod on a node only if, for each resource type, the sum of the **requests** of the containers already scheduled there plus the new Pod fits in the node's capacity. It does this "although actual memory or CPU resource usage on nodes is very low" [R3]. A cluster that looks idle in monitoring can therefore still refuse a Pod.

## Symptoms

- `kubectl get pods` shows `Pending` with `0/1` ready and no restarts [R2].
- `kubectl describe pod` shows no node assigned (`Node: /` in the documented example) and a `Warning FailedScheduling` event from `default-scheduler` [R2].
- Typical messages: `0/42 nodes available: insufficient cpu` [R3], `Insufficient memory` [R8], or `failed to fit in any node` with a per-node explanation [R2].

## Possible Causes

| Cause | Explanation |
|---|---|
| **Not enough CPU or memory** available on any node | The supply of CPU or memory in the cluster may be exhausted [R1]; the requests do not fit [R3] |
| **Pod larger than every node** | "If all the nodes have a capacity of `cpu: 1`, then a Pod with a request of `cpu: 1.1` will never be scheduled" [R3]. A memory request bigger than any node keeps the Pod `Pending` "indefinitely" [R8] |
| **Taints not tolerated** | A taint marks that a node "should not accept any pods that do not tolerate the taints" [R4]. If most nodes are tainted, only the remaining nodes are considered [R3] |
| **`nodeSelector` or required node affinity matching no node** | "Kubernetes only schedules the Pod onto nodes that have each of the labels you specify" [R5]. A label selector that matches no node prevents scheduling [R2] |
| **`hostPort` in use** | A `hostPort` limits the number of places where the Pod can run: at most as many Pods as there are nodes [R1] |
| **PersistentVolumeClaim not bound** | "Claims will remain unbound indefinitely if a matching volume does not exist" [R6]. A Pod that uses such a claim cannot start (team inference) |

## Investigation Steps

1. **Read the scheduler message.** `kubectl describe pod` lists the events; the `FailedScheduling` message says why each node was rejected [R1, R2].
2. **If the message mentions insufficient resources**, compare the Pod's requests with the nodes' **allocatable** resources and the requests already allocated on each node [R3].
3. **If no resource is mentioned**, check the Pod's `nodeSelector`, affinity rules and tolerations against the node labels and taints [R4, R5].
4. **Check `hostPort`** usage and the number of replicas compared with the number of nodes [R1].
5. **Check the PersistentVolumeClaims** used by the Pod: are they `Bound`? [R6]
6. **Look at all recent events of the namespace.** Events are namespaced, so pass the namespace explicitly [R2].

## Diagnostic Commands

```shell
# Pod status and scheduler events
kubectl get pods -n <namespace>
kubectl describe pod <pod> -n <namespace>

# Only the events part of describe
kubectl describe pod <pod> -n <namespace> | grep -A 9999999999 Events

# Events of the namespace (events are namespaced)
kubectl get events --namespace=<namespace>

# Node capacity, allocatable resources, allocated requests and limits
kubectl describe nodes <node>

# Node labels and taints
kubectl get nodes --show-labels
kubectl describe node <node> | grep -i taints

# Claims used by the Pod
kubectl get pvc -n <namespace>
```

Sources: `kubectl describe pod` and `kubectl get events --namespace` [R2]; `grep -A … Events` and `kubectl describe nodes` [R3]. Listing node labels and filtering taints from `describe node` are standard kubectl usage, added by the team to check [R4, R5].

## Interpretation of Results

| Observation | Meaning | Next step |
|---|---|---|
| `insufficient cpu` / `Insufficient memory` | The requests do not fit on any node [R3, R8] | Free capacity, lower requests, or add nodes |
| `Node didn't have enough resource: CPU, requested: 1000, used: 1420, capacity: 2000` | Detailed per-node fit failure from the documented example [R2] | Compare the request with free allocatable capacity |
| In `kubectl describe nodes`, `Allocatable` is lower than `Capacity` | Part of the capacity is reserved for system daemons; the scheduler uses `allocatable` [R3] | Size requests against allocatable, not capacity |
| The node rejects the Pod because of a taint | The Pod has no matching toleration [R4] | Add a toleration if the Pod really belongs on that node, or schedule it elsewhere |
| No node has the labels required by `nodeSelector` | Selector mismatch [R5] | Fix the selector or label the intended node |
| PVC status `Pending` | No matching volume, so the claim is unbound [R6] | Provide a matching PersistentVolume or StorageClass |

## Possible Solutions

For insufficient resources, the documentation lists [R1, R3]:

- add more nodes to the cluster;
- terminate unneeded Pods to make room for pending Pods;
- adjust (lower) resource requests;
- check that the Pod is not larger than all the nodes.

For the other causes:

- **Scale down a Deployment** whose extra replicas cannot fit. The documented example corrects the situation with `kubectl scale`, and notes that leaving one Pod pending is "harmless" [R2].
- **Taints**: add a matching toleration to the Pod, or remove the taint with `kubectl taint nodes <node> <key>=<value>:<effect>-` (note the trailing `-`) [R4]. A toleration allows scheduling but does not guarantee it [R4].
- **Selectors and affinity**: fix the selector, or add the expected label to the node [R5].
- **`hostPort`**: in most cases it is unnecessary. Use a Service object to expose the Pod instead [R1].
- **Storage**: create a PersistentVolume that matches the claim, for example a PVC asking for 100Gi cannot bind to 50Gi volumes [R6].

## Prevention

- Set realistic requests: scheduling is based on requests, not on observed usage [R3].
- Use `ResourceQuota` to stop one namespace from using all cluster resources [R3].
- Document node taints and labels used for dedicated nodes, so that teams know which tolerations and selectors to use (team recommendation).

## Related Concepts

- **Requests and limits, allocatable resources**: [R3]. Corpus: *Kubernetes Patterns*, ch. 2 *Predictable Demands* (PDF pp. 35-44).
- **Taints/tolerations vs node affinity**: node affinity attracts Pods to nodes; taints let a node repel Pods [R4].
- **Pods that are scheduled but cannot start**: see `md-k8s-imagepullbackoff` and `md-k8s-crashloopbackoff`.
- **Memory kills after scheduling**: see `md-k8s-oomkilled-resource-limits`.

## References

All pages were consulted on 2026-11-02, in their current version, and checked against the documentation source in the `kubernetes/website` repository.

- [R1] Kubernetes Documentation — *Debug Pods*. https://kubernetes.io/docs/tasks/debug/debug-application/debug-pods/
- [R2] Kubernetes Documentation — *Debug Running Pods*. https://kubernetes.io/docs/tasks/debug/debug-application/debug-running-pod/
- [R3] Kubernetes Documentation — *Resource Management for Pods and Containers*. https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/
- [R4] Kubernetes Documentation — *Taints and Tolerations*. https://kubernetes.io/docs/concepts/scheduling-eviction/taint-and-toleration/
- [R5] Kubernetes Documentation — *Assigning Pods to Nodes*. https://kubernetes.io/docs/concepts/scheduling-eviction/assign-pod-node/
- [R6] Kubernetes Documentation — *Persistent Volumes*. https://kubernetes.io/docs/concepts/storage/persistent-volumes/
- [R7] Kubernetes Documentation — *Pod Lifecycle*. https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/
- [R8] Kubernetes Documentation — *Assign Memory Resources to Containers and Pods*. https://kubernetes.io/docs/tasks/configure-pod-container/assign-memory-resource/

## Metadata

- **Nature of this document:** written by the project team from the official Kubernetes documentation listed above. It is **not** official Kubernetes documentation.
- **Verification:** each statement followed by a reference was checked against the source text. Statements marked "team inference" or "team recommendation" are our own reasoning.
- **Scope limits:** the exact wording of scheduler messages varies between Kubernetes versions; the messages quoted here are those of the documented examples.
