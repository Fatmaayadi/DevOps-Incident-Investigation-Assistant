---
doc_id: md-k8s-oomkilled-resource-limits
title: Kubernetes Container OOMKilled (memory limits and node memory pressure)
domain: kubernetes
technology: [kubernetes, kubectl, linux-cgroups]
category: resource-exhaustion
document_type: troubleshooting_guide
difficulty: intermediate
keywords:
  - OOMKilled
  - out of memory
  - memory limit
  - memory request
  - exit code 137
  - QoS class
  - Guaranteed Burstable BestEffort
  - eviction
  - MemoryPressure
  - oom_score_adj
error_messages:
  - "OOMKilled"
  - "Exit Code: 137"
  - "Back-off restarting failed container"
  - "Memory cgroup out of memory"
source_type: team_written_from_official_docs
language: en
references:
  - id: R1
    title: "Resource Management for Pods and Containers (sections: requests and limits, My container is terminated)"
    publisher: Kubernetes Documentation
    url: https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/
    accessed: 2026-11-02
  - id: R2
    title: "Assign Memory Resources to Containers and Pods"
    publisher: Kubernetes Documentation
    url: https://kubernetes.io/docs/tasks/configure-pod-container/assign-memory-resource/
    accessed: 2026-11-02
  - id: R3
    title: "Pod Quality of Service Classes"
    publisher: Kubernetes Documentation
    url: https://kubernetes.io/docs/concepts/workloads/pods/pod-qos/
    accessed: 2026-11-02
  - id: R4
    title: "Node-pressure Eviction (sections: Node conditions, Node out of memory behavior)"
    publisher: Kubernetes Documentation
    url: https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/
    accessed: 2026-11-02
  - id: R5
    title: "kubectl Quick Reference (section: Interacting with running Pods)"
    publisher: Kubernetes Documentation
    url: https://kubernetes.io/docs/reference/kubectl/quick-reference/
    accessed: 2026-11-02
related_corpus_documents:
  - doc_id: pdf-o-reilly-kubernetes-patterns
    pages: "35-44 (ch. 2 Predictable Demands)"
  - doc_id: pdf-o-reilly-kubernetes-up-and-running
    pages: "76-79 (Resource Management)"
last_reviewed: 2026-11-02
review_status: reviewed by team against sources
---

# Kubernetes Container OOMKilled (memory limits and node memory pressure)

## Overview

A container is reported as `OOMKilled` when it was terminated because it tried to use more memory than allowed. Kubernetes memory limits "are enforced by the kernel with out of memory (OOM) kills" [R1].

Two different situations must be distinguished:

1. **The container exceeded its own memory limit.** The kernel may terminate it. This is enforced reactively: "terminations only happen when the kernel detects memory pressure", so a container can briefly use more than its limit before being killed [R1].
2. **The node itself ran out of memory.** The kubelet first tries to reclaim memory by **evicting** Pods. If the node hits an OOM event before the kubelet can do so, the Linux `oom_killer` chooses which container to kill [R4].

When a terminated container can be restarted, the kubelet restarts it "as with any other type of runtime failure" [R2]. A container that is killed repeatedly therefore often ends up in `CrashLoopBackOff` (see `md-k8s-crashloopbackoff`).

## Symptoms

- `kubectl get pods` shows `OOMKilled` in the `STATUS` column for a moment, then `Running` again or `CrashLoopBackOff`, with a growing `RESTARTS` count [R2].
- `kubectl describe pod` shows a `Last State: Terminated` block with `Reason: OOMKilled`. The documented example also shows `Exit Code: 137` [R1].
- Pod events show `Back-off restarting failed container` [R2].
- `kubectl describe nodes` can show a record of the kill, for example `Memory cgroup out of memory: Kill process ...` [R2].
- For node-level pressure: the node reports the `MemoryPressure` condition, which means available memory "has satisfied an eviction threshold" [R4].

## Possible Causes

| Cause | Explanation |
|---|---|
| **Memory limit too low** for the normal workload of the application | The container needs more than its limit even when it behaves correctly [R1] |
| **Memory leak** in the application | Memory usage grows until the limit is reached. The documentation's first suggestion is to "check the application code for a memory leak" [R1] |
| **Node out of memory** because of overcommitment | The sum of the limits on a node can exceed its capacity ("Total limits may be over 100 percent, i.e., overcommitted") [R1]. When the node itself runs out of memory, the `oom_killer` kills the container with the highest effective score [R4] |
| **Container without request or limit** (`BestEffort`) or using far more than its request (`Burstable`) | These containers are killed or evicted first under node pressure [R3, R4] |
| **`emptyDir` volumes in memory** | Memory-backed volumes count against memory consumption [R1] |

## Investigation Steps

1. **Confirm the reason.** In `kubectl describe pod`, look at `Last State: Terminated`, `Reason`, `Exit Code` and `Restart Count` [R1].
2. **Read the configured requests and limits** for each container in the same output (`Limits`, `Requests`) [R1].
3. **Determine the QoS class** of the Pod (`QoS Class` in `kubectl describe pod`) [R3].
4. **Check the node.** Look at the node conditions (`MemoryPressure`), its allocatable memory, and the memory already reserved on it [R1, R4].
5. **Measure actual usage**, if the metrics API is available in the cluster (team note: `kubectl top` depends on it) [R5].
6. **Decide between a leak and an undersized limit.** Does usage grow continuously until the kill, or does the application need a stable amount above the limit? (Team recommendation.)

## Diagnostic Commands

```shell
# Last termination reason, exit code, restarts, limits/requests, QoS class
kubectl describe pod <pod> -n <namespace>

# Node capacity, allocatable memory, allocated requests/limits, conditions
kubectl describe nodes <node>

# Current memory usage per Pod / per container (requires metrics in the cluster)
kubectl top pod -n <namespace>
kubectl top pod <pod> -n <namespace> --containers

# Logs of the instance that was killed
kubectl logs <pod> -c <container> -n <namespace> --previous
```

Sources: `kubectl describe pod` [R1, R2]; `kubectl describe nodes` [R1, R2]; `kubectl top pod` [R5]; `kubectl logs --previous` [R5].

## Interpretation of Results

| Observation | Meaning | Next step |
|---|---|---|
| `Last State: Terminated`, `Reason: OOMKilled` | "The container tried to use more memory than its limit" [R1] | Leak or undersized limit: see Possible Solutions |
| `Restart Count` keeps increasing, events show `Back-off restarting failed container` | Repeated kills and restarts [R2] | Same as above; see also `md-k8s-crashloopbackoff` |
| Node condition `MemoryPressure` is true | The node, not just one container, is short of memory [R4] | Reduce overcommitment, review requests, add capacity |
| Pod QoS class `BestEffort` | No requests or limits; first to be evicted under pressure [R3] | Define requests and limits |
| `Allocated resources` shows memory limits above 100 % | The node is overcommitted [R1] | Align limits with real usage, or spread the Pods |
| Pod is `Pending` with `Insufficient memory` | The request is too big for every node; this is a scheduling problem, not an OOM kill [R2] | See `md-k8s-pod-pending-failedscheduling` |

## Possible Solutions

- **Fix the leak** if memory grows continuously. Restarting only hides the problem [R1].
- **Raise the memory limit, and possibly the request**, if the application behaves as expected but needs more memory [R1].
- **Make memory needs explicit with requests.** Scheduling is based on requests: "a Pod is scheduled to run on a Node only if the Node has enough available memory to satisfy the Pod's memory request" [R2].
- **Use the `Guaranteed` QoS class for critical workloads**: every container has CPU and memory requests equal to its limits [R3]. Such Pods are least likely to be evicted and are "guaranteed not to be killed until they exceed their limits" [R3].
- **Reduce node overcommitment**, or add capacity when several Pods compete for memory on the same node (team recommendation based on [R1, R4]).

## Prevention

- Always set memory requests and limits. Without them, a Pod is `BestEffort` and is evicted first under node pressure [R3].
- Size limits from observed usage under realistic load, with a margin (team recommendation).
- Remember that, unlike eviction, an OOM-killed container can be restarted according to its `restartPolicy` [R4]. Monitor restart counts and alert on repeated `OOMKilled` (team recommendation).
- Use `ResourceQuota` to stop one namespace from consuming too much of the cluster's resources [R1].

## Related Concepts

- **QoS classes and eviction order**: when a node runs out of resources, Kubernetes evicts `BestEffort` Pods first, then `Burstable`, and finally `Guaranteed` [R3].
- **`oom_score_adj`**: the kubelet sets it from the QoS class (for example `-997` for `Guaranteed` and `1000` for `BestEffort`), so that containers of low-QoS Pods using a lot of memory relative to their requests are killed first [R4].
- **CPU limits behave differently**: CPU is throttled rather than killed, and container runtimes do not terminate Pods or containers for excessive CPU usage [R1].
- Corpus: *Kubernetes Patterns*, ch. 2 *Predictable Demands* (PDF pp. 35-44); *Kubernetes: Up and Running*, Resource Management (PDF pp. 76-79).
- Related guides: `md-k8s-crashloopbackoff`, `md-k8s-pod-pending-failedscheduling`.

## References

All pages were consulted on 2026-11-02, in their current version, and checked against the documentation source in the `kubernetes/website` repository.

- [R1] Kubernetes Documentation — *Resource Management for Pods and Containers*. https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/
- [R2] Kubernetes Documentation — *Assign Memory Resources to Containers and Pods*. https://kubernetes.io/docs/tasks/configure-pod-container/assign-memory-resource/
- [R3] Kubernetes Documentation — *Pod Quality of Service Classes*. https://kubernetes.io/docs/concepts/workloads/pods/pod-qos/
- [R4] Kubernetes Documentation — *Node-pressure Eviction*. https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/
- [R5] Kubernetes Documentation — *kubectl Quick Reference*. https://kubernetes.io/docs/reference/kubectl/quick-reference/

## Metadata

- **Nature of this document:** written by the project team from the official Kubernetes documentation listed above. It is **not** official Kubernetes documentation.
- **Verification:** each statement followed by a reference was checked against the source text. Statements marked "team note" or "team recommendation" are our own reasoning.
- **Scope limits:** exact eviction thresholds depend on the kubelet configuration of each cluster. The meaning of exit code 137 is not explained by the Kubernetes documentation; we only report it as the value shown in the documented `OOMKilled` example.
