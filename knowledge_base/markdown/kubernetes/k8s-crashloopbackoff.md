---
doc_id: md-k8s-crashloopbackoff
title: Kubernetes Pod in CrashLoopBackOff
domain: kubernetes
technology: [kubernetes, kubectl]
category: workload-failure
document_type: troubleshooting_guide
difficulty: intermediate
keywords:
  - CrashLoopBackOff
  - restart loop
  - restartPolicy
  - back-off delay
  - kubectl logs --previous
  - Last State Terminated
  - exit code
  - OOMKilled
  - liveness probe
  - startup probe
  - kubectl debug --copy-to
error_messages:
  - "CrashLoopBackOff"
  - "Back-off restarting failed container"
  - "Liveness probe failed"
  - "Container liveness failed liveness probe, will be restarted"
  - "OOMKilled"
source_type: team_written_from_official_docs
language: en
references:
  - id: R1
    title: "Pod Lifecycle (sections: Pod phase, Container states, How Pods handle problems with containers, Container restarts)"
    publisher: Kubernetes Documentation
    url: https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/
    accessed: 2026-11-02
  - id: R2
    title: "Liveness, Readiness, and Startup Probes"
    publisher: Kubernetes Documentation
    url: https://kubernetes.io/docs/concepts/workloads/pods/probes/
    accessed: 2026-11-02
  - id: R3
    title: "Debug Running Pods"
    publisher: Kubernetes Documentation
    url: https://kubernetes.io/docs/tasks/debug/debug-application/debug-running-pod/
    accessed: 2026-11-02
  - id: R4
    title: "Resource Management for Pods and Containers (section: My container is terminated)"
    publisher: Kubernetes Documentation
    url: https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/
    accessed: 2026-11-02
  - id: R5
    title: "Assign Memory Resources to Containers and Pods (section: Exceed a Container's memory limit)"
    publisher: Kubernetes Documentation
    url: https://kubernetes.io/docs/tasks/configure-pod-container/assign-memory-resource/
    accessed: 2026-11-02
  - id: R6
    title: "Configure Liveness, Readiness and Startup Probes"
    publisher: Kubernetes Documentation
    url: https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/
    accessed: 2026-11-02
  - id: R7
    title: "Determine the Reason for Pod Failure"
    publisher: Kubernetes Documentation
    url: https://kubernetes.io/docs/tasks/debug/debug-application/determine-reason-pod-failure/
    accessed: 2026-11-02
  - id: R8
    title: "Define a Command and Arguments for a Container"
    publisher: Kubernetes Documentation
    url: https://kubernetes.io/docs/tasks/inject-data-application/define-command-argument-container/
    accessed: 2026-11-02
  - id: R9
    title: "Secrets (sections: restrictions, Optional Secrets)"
    publisher: Kubernetes Documentation
    url: https://kubernetes.io/docs/concepts/configuration/secret/
    accessed: 2026-11-02
  - id: R10
    title: "kubectl Quick Reference"
    publisher: Kubernetes Documentation
    url: https://kubernetes.io/docs/reference/kubectl/quick-reference/
    accessed: 2026-11-02
  - id: R11
    title: "Debug Pods (sections: Debugging Pods, My pod stays waiting, Debugging a Pod's spec)"
    publisher: Kubernetes Documentation
    url: https://kubernetes.io/docs/tasks/debug/debug-application/debug-pods/
    accessed: 2026-11-02
related_corpus_documents:
  - doc_id: pdf-o-reilly-kubernetes-up-and-running
    pages: "72-79 (Accessing Your Pod, Health Checks, Resource Management)"
  - doc_id: pdf-o-reilly-kubernetes-patterns
    pages: "35-44 (ch. 2 Predictable Demands), 55-60 (ch. 4 Health Probe)"
last_reviewed: 2026-11-02
review_status: pilot — awaiting team validation
---

# Kubernetes Pod in CrashLoopBackOff

## Overview

`CrashLoopBackOff` means that a container in a Pod keeps starting, exiting and being restarted, and that Kubernetes is currently waiting before the next restart attempt. The documentation describes it as the state where "the backoff delay mechanism is currently in effect for a given container that is in a crash loop, failing and restarting repeatedly" [R1].

Two points frame the whole investigation:

- `CrashLoopBackOff` is **not a Pod phase**. It is a value that kubectl shows in its `STATUS` column; the Pod's actual `phase` (an API field) is something different [R1].
- `CrashLoopBackOff` is a **consequence, not a cause**. The useful information is in why the *previous* container instance stopped: its exit code, its termination reason and its last log lines.

### How the restart loop works

When a container exits, the kubelet restarts it according to the Pod's `restartPolicy` [R1]:

| Container exit | `Always` (default) | `OnFailure` | `Never` |
|---|---|---|---|
| Exit code 0 | Restarts | Does not restart | Does not restart |
| Non-zero exit code | Restarts | Restarts | Does not restart |

Deployments only allow `restartPolicy: Always` [R1]. A container managed by a Deployment is therefore restarted **even when it exits successfully** with code 0.

The delay between restarts grows exponentially (10s, 20s, 40s, …) up to a maximum of 300 seconds (5 minutes). The timer is reset once the container has run for 10 minutes without problems [R1]. Clusters that enable the alpha feature gates `ReduceDefaultCrashLoopBackOffDecay` or `KubeletCrashLoopBackOffMax` can use different delays [R1].

## Symptoms

- `kubectl get pods` shows `CrashLoopBackOff` in the `STATUS` column and a growing `RESTARTS` count [R1]:

  ```
  NAME               READY   STATUS             RESTARTS   AGE
  my-app-7d9c-x2k4   0/1     CrashLoopBackOff   12         25m
  ```

- `kubectl describe pod` shows the container in `State: Waiting` with `Reason: CrashLoopBackOff`, and a `Last State: Terminated` block with a reason and an exit code [R3].
- The Pod events contain `Back-off restarting failed container` [R5].
- `kubectl get pods` shows `0/1` in the `READY` column [R1]. The `Ready` condition indicates whether the Pod can serve requests and be added to the load balancing pools of matching Services [R3]. A crash-looping Pod therefore usually receives no traffic, and users may see errors from a load balancer or ingress in front of the application (team observation: a downstream effect, not a separate problem).

## Possible Causes

The Kubernetes documentation lists the following causes [R1]:

| Cause | Typical evidence |
|---|---|
| **Application error** that makes the main process exit (unhandled exception, failed connection at startup, invalid argument) | Non-zero exit code; error in `kubectl logs --previous` |
| **Configuration error**: wrong environment variable, missing configuration file | Error message about a variable, file or path in the previous logs |
| **Resource constraints**: not enough memory or CPU to start properly | `Reason: OOMKilled` in `Last State` (memory) [R4] |
| **Health checks failing** because the application does not start serving within the expected time | `Liveness probe failed` events followed by a restart [R6] |
| **Liveness or startup probes returning `Failure`** | Same events; the container is killed by the kubelet, not by itself [R2] |

Two more situations follow from the restart rules above. They are an interpretation by the team of documented behaviour, not causes listed as such by the documentation:

- **The main process exits normally (code 0).** Under `restartPolicy: Always`, a container whose command finishes, such as a one-shot script or a process that daemonizes into the background, is restarted again and again [R1].
- **The container command or arguments are wrong.** The `command` and `args` fields override the image's default command (`ENTRYPOINT` / `CMD` in some runtimes) [R8]. A wrong value can make the process exit immediately. The documentation's own example of a crashing container runs the command `false` and ends in `CrashLoopBackOff` with exit code 1 [R3].

### What is usually *not* CrashLoopBackOff

If a Pod references a Secret that does not exist, **none of its containers start** until the Secret is available. The kubelet keeps retrying and reports an Event describing the problem [R9]. In that case the container never runs, so it cannot crash. Check the Pod events and look for a different `Waiting` reason. According to the documentation, "the most common cause of `Waiting` pods is a failure to pull the image" [R11]. That situation is covered in a separate guide (`md-k8s-imagepullbackoff`).

## Investigation Steps

Follow these steps in order. Each step uses the output of the previous one.

1. **Confirm the status and the restart count.** A high `RESTARTS` value together with `CrashLoopBackOff` confirms a crash loop. "Restart Count tells you how many times the container has been restarted" [R3].
2. **Read how the previous instance ended.** In `kubectl describe pod`, look at `Last State: Terminated`: `Reason`, `Exit Code`, `Started` and `Finished` [R1, R3]. A very short time between `Started` and `Finished` indicates a crash during startup.
3. **Read the logs of the previous instance.** The current instance may not have started yet, or may not have logged anything yet. `--previous` shows "the previous container's crash log" [R3]. The documentation calls the logs "often the most direct way to diagnose the issue" [R1].
4. **Read the Pod events.** They show probe failures, back-off messages, kills and configuration problems [R1, R6].
5. **Read the termination message**, if the application writes one. The kubelet exposes it in `lastState.terminated.message` [R7].
6. **Check resource limits** if the reason is `OOMKilled` or the events point to resources [R1, R4].
7. **Check what changed.** Compare with the previous revision of the Deployment: image tag, command, environment, mounted configuration. This step is a team recommendation: a crash loop that starts right after a rollout often comes from that rollout.
8. **Reproduce interactively** if the logs are empty or unclear. Create a copy of the Pod whose command is replaced by a shell, then run the original command by hand [R3].

## Diagnostic Commands

Replace `<pod>`, `<container>` and `<namespace>` with your values. `-c <container>` can be omitted for single-container Pods [R3].

```shell
# 1. Status and restart count
kubectl get pods -n <namespace>

# 2. Container state, Last State (reason, exit code), events
kubectl describe pod <pod> -n <namespace>

# 3. Logs of the current and of the previous (crashed) instance
kubectl logs <pod> -c <container> -n <namespace>
kubectl logs <pod> -c <container> -n <namespace> --previous

# 4. Events: sorted by time, or warnings only
kubectl get events -n <namespace> --sort-by=.metadata.creationTimestamp
kubectl events -n <namespace> --types=Warning

# 5. Termination message of the last terminated instance
kubectl get pod <pod> -n <namespace> -o go-template="{{range .status.containerStatuses}}{{.lastState.terminated.message}}{{end}}"

# 6. Full status as YAML (lastState, restartCount, probes, resources)
kubectl get pod <pod> -n <namespace> -o yaml

# 7. Rollout history of the Deployment that owns the Pod
kubectl rollout history deployment/<deployment> -n <namespace>

# 8. Copy of the Pod with the container command replaced by a shell
kubectl debug <pod> -it --copy-to=<pod>-debug --container=<container> -- sh
# ... investigate, then clean up
kubectl delete pod <pod>-debug
```

Sources: commands 1–3 and 8 [R3]; command 4 [R10]; command 5 [R7]; command 6 [R11]; command 7 [R10]. Adding `-n <namespace>` to these commands is our own adaptation.

Notes:

- `kubectl debug --copy-to` creates a **new Pod**. It does not modify the crashing one. To change the command of an existing container, you must name it with `--container`; otherwise `kubectl debug` adds a new container instead [R3]. Delete the copy when you are done [R3].
- `kubectl exec` does not help while the container is not running, or when the image has no shell. In that case, use the copy method above or an ephemeral debug container [R3].

## Interpretation of Results

| Observation | Meaning | Next step |
|---|---|---|
| `Last State: Terminated`, `Reason: Error`, `Exit Code: 1` | The process exited with an error by itself. This is the documentation's example of a crashing command [R3] | Read `kubectl logs --previous` for the error |
| `Reason: OOMKilled` (the documented example also shows `Exit Code: 137`) | "The container tried to use more memory than its limit" [R4] | Check for a memory leak, or raise the memory limit and possibly the request [R4] |
| Events `Liveness probe failed: …` then `Container … failed liveness probe, will be restarted` | The kubelet killed the container because its liveness probe failed [R6] | Check whether the application is really unhealthy or just slow to start (see Possible Solutions) |
| `Exit Code: 0` and continuous restarts | The main process finished successfully; with `restartPolicy: Always` it is restarted anyway [R1] | Check the container command: it should run a long-lived foreground process |
| Very short time between `Started` and `Finished` | Crash during initialization (team observation) | Look for configuration, environment, file path or dependency errors in the previous logs |
| `kubectl logs --previous` is empty | The process failed before writing anything, or writes its logs elsewhere (team observation) | Read the termination message [R7], or reproduce with `kubectl debug --copy-to … -- sh` [R3] |
| Containers never start and the events report a problem fetching a Secret | Not a crash loop: a required Secret is missing [R9] | Create the Secret, or fix its name or key |

## Possible Solutions

Apply the solution that matches the evidence. Do not change several things at once.

- **Application or configuration error.** Fix the code or the configuration shown in the previous logs: environment variable, configuration file, mounted volume, external dependency [R1]. The documentation also suggests running the same image locally or in a development environment to debug application-specific issues [R1].
- **Wrong command or arguments.** Correct `command` / `args` in the Pod template. They override the image defaults and cannot be changed on an existing Pod, so the Pods must be recreated (for a Deployment, by updating its template) [R8].
- **Process exits with code 0.** Run the application as a long-lived foreground process. If the workload is really a one-shot task, use a Job with `restartPolicy: OnFailure` or `Never` instead of a Deployment [R1].
- **OOMKilled.** Investigate a possible memory leak first. If the application behaves as expected, set a higher memory limit, and possibly a higher request [R4].
- **Liveness probe kills a slow-starting container.** Add a **startup probe** with a `failureThreshold × periodSeconds` long enough for the worst-case startup time. Liveness checks only begin after the startup probe has succeeded [R6]. The documented example allows 30 × 10 s = 300 s. If it never succeeds, the container is killed after 300 s [R6]. Alternatively, use `initialDelaySeconds` [R2].
- **Liveness probe too aggressive.** Make sure the probe "truly indicates unrecoverable application failure, for example a deadlock" [R2]. A common pattern is to reuse the readiness endpoint with a higher `failureThreshold` [R2].
- **Crash loop introduced by a rollout.** Roll back with `kubectl rollout undo deployment/<deployment>` while the cause is investigated [R10]. This restores service but does not explain the failure.

## Prevention

- Define liveness probes carefully. "Incorrect implementation of liveness probes can lead to cascading failures", with restarts under high load and more pressure on the remaining Pods [R2]. Use readiness probes, not liveness probes, for temporary unavailability [R2, R6].
- Use a startup probe for applications with long or variable startup times [R2, R6].
- Set memory requests and limits based on observed usage (team recommendation), and keep in mind that memory limits are enforced reactively by OOM kills [R4].
- Make the application log a clear message before exiting on a fatal error. Consider writing a termination message, or setting `terminationMessagePolicy: FallbackToLogsOnError` so that the end of the logs is used when the message file is empty [R7].
- Create Secrets and other referenced objects before the Pods that depend on them [R9].

## Related Concepts

- **Restart policy and container states** (`Waiting`, `Running`, `Terminated`): [R1]. Corpus: *Kubernetes: Up and Running*, PDF pp. 72-79.
- **Health probes** (startup, liveness, readiness): [R2], [R6]. Corpus: *Kubernetes Patterns*, ch. 4 *Health Probe*, PDF pp. 55-60.
- **Resource requests, limits and OOM kills**: [R4], [R5]. Corpus: *Kubernetes Patterns*, ch. 2 *Predictable Demands*, PDF pp. 35-44. See also `md-k8s-oomkilled-resource-limits`.
- **Image pull failures** (another `Waiting` reason): see `md-k8s-imagepullbackoff`.
- **Service without endpoints** (consequence of Pods that are not Ready): see `md-k8s-service-no-endpoints`.

## References

All pages were consulted on 2026-11-02, from the current version of the Kubernetes documentation. The text was checked against the documentation source in the `kubernetes/website` repository; the *Pod Lifecycle* page was last modified there on 2026-10-29.

- [R1] Kubernetes Documentation — *Pod Lifecycle*. https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/
- [R2] Kubernetes Documentation — *Liveness, Readiness, and Startup Probes*. https://kubernetes.io/docs/concepts/workloads/pods/probes/
- [R3] Kubernetes Documentation — *Debug Running Pods*. https://kubernetes.io/docs/tasks/debug/debug-application/debug-running-pod/
- [R4] Kubernetes Documentation — *Resource Management for Pods and Containers*. https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/
- [R5] Kubernetes Documentation — *Assign Memory Resources to Containers and Pods*. https://kubernetes.io/docs/tasks/configure-pod-container/assign-memory-resource/
- [R6] Kubernetes Documentation — *Configure Liveness, Readiness and Startup Probes*. https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/
- [R7] Kubernetes Documentation — *Determine the Reason for Pod Failure*. https://kubernetes.io/docs/tasks/debug/debug-application/determine-reason-pod-failure/
- [R8] Kubernetes Documentation — *Define a Command and Arguments for a Container*. https://kubernetes.io/docs/tasks/inject-data-application/define-command-argument-container/
- [R9] Kubernetes Documentation — *Secrets*. https://kubernetes.io/docs/concepts/configuration/secret/
- [R10] Kubernetes Documentation — *kubectl Quick Reference*. https://kubernetes.io/docs/reference/kubectl/quick-reference/
- [R11] Kubernetes Documentation — *Debug Pods*. https://kubernetes.io/docs/tasks/debug/debug-application/debug-pods/

## Metadata

- **Nature of this document:** written by the project team from the official Kubernetes documentation listed above. It is **not** official Kubernetes documentation.
- **Verification:** each statement followed by a reference was checked against the source text. Statements marked "team recommendation", "team observation" or "interpretation by the team" are our own reasoning from documented behaviour, and are not quoted from a source.
- **Scope limits:** this guide does not cover image pull errors, Pods stuck in `Pending`, or cluster-level node problems. Exact kubectl output can vary between Kubernetes versions.
- **Review status:** pilot document, awaiting team validation (see the `review_status` field above). **Remaining action:** a team member must check this guide against its sources, then update `review_status` and `last_reviewed`. This validation has not been done yet.
