---
doc_id: md-k8s-imagepullbackoff
title: Kubernetes Pod in ImagePullBackOff
domain: kubernetes
technology: [kubernetes, kubectl, container-registry]
category: workload-failure
document_type: troubleshooting_guide
difficulty: beginner
keywords:
  - ImagePullBackOff
  - image pull failure
  - Waiting state
  - imagePullPolicy
  - imagePullSecrets
  - private registry
  - docker-registry secret
  - image tag
  - image digest
error_messages:
  - "ImagePullBackOff"
  - "ErrImagePull"
source_type: team_written_from_official_docs
language: en
references:
  - id: R1
    title: "Images (sections: Image names, Image pull policy, ImagePullBackOff, Using a private registry)"
    publisher: Kubernetes Documentation
    url: https://kubernetes.io/docs/concepts/containers/images/
    accessed: 2026-11-02
  - id: R2
    title: "Pull an Image from a Private Registry"
    publisher: Kubernetes Documentation
    url: https://kubernetes.io/docs/tasks/configure-pod-container/pull-image-private-registry/
    accessed: 2026-11-02
  - id: R3
    title: "Debug Pods (section: My pod stays waiting)"
    publisher: Kubernetes Documentation
    url: https://kubernetes.io/docs/tasks/debug/debug-application/debug-pods/
    accessed: 2026-11-02
  - id: R4
    title: "Pod Lifecycle (section: Container states)"
    publisher: Kubernetes Documentation
    url: https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/
    accessed: 2026-11-02
  - id: R5
    title: "Kubernetes source code, pkg/kubelet/images/types.go (image pull error reasons)"
    publisher: Kubernetes project
    url: https://github.com/kubernetes/kubernetes/blob/master/pkg/kubelet/images/types.go
    accessed: 2026-11-11
  - id: R6
    title: "Managing Secrets using kubectl (Verify the Secret)"
    publisher: Kubernetes Documentation
    url: https://kubernetes.io/docs/tasks/configmap-secret/managing-secret-using-kubectl/
    accessed: 2026-11-11
related_corpus_documents:
  - doc_id: pdf-o-reilly-kubernetes-up-and-running
    pages: "72-79 (Pods: inspecting and accessing a Pod)"
last_reviewed: 2026-11-02
review_status: reviewed by team against sources
---

# Kubernetes Pod in ImagePullBackOff

## Overview

`ImagePullBackOff` means that a container could not start because Kubernetes could not pull its container image. The documentation gives as examples "invalid image name, or pulling from a private registry without `imagePullSecret`". The `BackOff` part indicates that Kubernetes keeps retrying the pull with an increasing delay. That delay is capped by a compiled-in limit of 300 seconds (5 minutes) [R1].

The container stays in the `Waiting` state: it has been scheduled to a node, but cannot run there [R3]. `kubectl` shows a `Reason` field explaining why a container is `Waiting` [R4]. The documentation states that "the most common cause of `Waiting` pods is a failure to pull the image" [R3].

### ErrImagePull and ImagePullBackOff

Both values describe the same problem at two moments. In the kubelet source code, `ErrImagePull` is a "General image pull error", and `ImagePullBackOff` is used when the "Container image pull failed, kubelet is backing off image pull" [R5]. A Pod can therefore show `ErrImagePull` right after a failed attempt, then `ImagePullBackOff` while the kubelet waits before the next attempt (team inference from [R1, R5]). The cause is the same, so the investigation is the same. Two related reasons are defined in the same file: `InvalidImageName` ("Unable to parse the image name.") and `ErrImageNeverPull` ("Required Image is absent on host and PullPolicy is NeverPullImage") [R5].

The application code is never executed, so its logs are empty. All the useful information is in the Pod events and the image reference.

## Symptoms

- `kubectl get pods` shows `ImagePullBackOff` in the `STATUS` column, and the `RESTARTS` count stays at 0 (team observation: the container never started).
- Shortly after a failed pull, the same column can show `ErrImagePull` instead (see the Overview) [R5].
- `kubectl describe pod` shows the container in `State: Waiting` with `Reason: ImagePullBackOff` [R1, R4]. The Events section at the bottom reports the pull attempts and the error returned by the registry or the container runtime.
- `kubectl logs` returns nothing useful, because no container process ever ran (team observation).

## Possible Causes

| Cause | Explanation |
|---|---|
| **Wrong image name, registry or tag** | A typo, a tag that was never pushed, or a missing registry hostname. Without a registry hostname, Kubernetes assumes the Docker public registry. Without a tag, it assumes `latest` [R1] |
| **Image not pushed** to the registry | The documentation explicitly asks: "Have you pushed the image to the registry?" [R3] |
| **Private registry without credentials** | The Pod has no `imagePullSecrets`, or the Secret is wrong [R1] |
| **Secret in the wrong namespace or of the wrong type** | `imagePullSecrets` must reference Secrets in the **same namespace** as the Pod, of type `kubernetes.io/dockercfg` or `kubernetes.io/dockerconfigjson` [R1] |
| **Invalid registry credentials** | The Secret exists but contains a wrong server, username or password [R2] |
| **`imagePullPolicy: Never`** and image absent from the node | With `Never`, the kubelet does not fetch the image; if it is not already present, startup fails [R1] |

Note on `latest`: if a Deployment is first created with a non-`latest` tag and later updated to `:latest`, the `imagePullPolicy` field does **not** change to `Always` automatically [R1]. This affects which image is used, not whether the pull succeeds.

## Investigation Steps

1. **Read the Pod events.** In `kubectl describe pod`, the Events section shows the image reference that was tried and the error message [R3].
2. **Check the exact image reference** in the Pod spec: registry hostname, repository, tag or digest. Compare it character by character with what exists in the registry [R1, R3].
3. **Try to pull the image manually** from a machine with access to the registry, for example `docker pull <image>` [R3]. If this fails too, the problem is the image or the credentials, not Kubernetes.
4. **If the registry is private, check the pull Secret**: that it exists in the Pod's namespace, has the right type, and is listed in `spec.imagePullSecrets` (directly or through the Pod's ServiceAccount) [R1, R2].
5. **Check the Secret without printing its values.** `kubectl describe secret` shows its type and the size of each key: "The commands `kubectl get` and `kubectl describe` avoid showing the contents of a `Secret` by default" [R6]. Decoding the Secret, as shown in [R2], prints the registry password in clear text. Do it only if necessary, on a trusted terminal, and never paste the output into a ticket or a chat (team recommendation).
6. **Check `imagePullPolicy`** if the image is expected to be pre-loaded on the nodes [R1].

## Diagnostic Commands

```shell
# Status of the Pods
kubectl get pods -n <namespace>

# Waiting reason and events (pull errors appear here)
kubectl describe pod <pod> -n <namespace>

# Exact image reference and pull policy used by the Pod
kubectl get pod <pod> -n <namespace> -o jsonpath='{.spec.containers[*].image}{"\n"}{.spec.containers[*].imagePullPolicy}{"\n"}'

# Pull secrets referenced by the Pod
kubectl get pod <pod> -n <namespace> -o jsonpath='{.spec.imagePullSecrets}'

# Does the Secret exist in the same namespace, and what type is it? (keys and sizes only, no values)
kubectl describe secret <secret> -n <namespace>

# Manual pull from a workstation with registry access
docker pull <registry>/<repository>:<tag>
```

Sources: `kubectl describe pod` and `docker pull` [R3]; `kubectl describe secret` [R6]. The `jsonpath` queries are standard kubectl output formatting, adapted by the team to display the fields discussed in [R1].

## Interpretation of Results

| Observation | Meaning | Next step |
|---|---|---|
| The image reference in the spec contains a typo or a tag that does not exist in the registry | Wrong image name or tag [R1, R3] | Fix the reference and redeploy |
| `docker pull` also fails from a workstation | The problem is outside Kubernetes: the image is missing, or the credentials are refused [R3] | Push the image, or fix the registry account |
| `docker pull` works locally, but the Pod still fails on a private registry | The cluster lacks valid credentials (team inference) | Check `imagePullSecrets`, the namespace and the Secret content [R1, R2] |
| `kubectl describe secret` returns NotFound in the Pod's namespace | Pull secrets are namespaced; the Secret was created elsewhere [R1] | Create the Secret in the Pod's namespace [R1] |
| The Secret exists but the Pod spec has no `imagePullSecrets` (and its ServiceAccount has none) | The Secret is not used [R1] | Reference it in the Pod spec or in the ServiceAccount [R1] |
| `STATUS` shows `InvalidImageName` | The image reference cannot be parsed [R5] | Fix the image reference |
| `imagePullPolicy: Never` (`ErrImageNeverPull`) | Startup fails if the image is not already on the node [R1, R5] | Pre-pull the image on every node, or change the policy |

## Possible Solutions

- **Correct the image reference.** Prefer a meaningful tag such as `v1.42.0`, or a digest, rather than `:latest`. A digest guarantees that the Pod always uses the same image version [R1].
- **Push the missing image or tag** to the registry, then let Kubernetes retry, or recreate the Pod.
- **Create a registry Secret in the Pod's namespace** and reference it [R1, R2]:

  ```shell
  kubectl create secret docker-registry <name> \
    --docker-server=<registry-server> \
    --docker-username=<user> \
    --docker-password=<password> \
    --docker-email=<email> \
    -n <namespace>
  ```

  ```yaml
  spec:
    imagePullSecrets:
      - name: <name>
  ```

- **Avoid repeating the Secret in every Pod**: add `imagePullSecrets` to the ServiceAccount used by the Pods [R1].
- **Reuse existing Docker credentials** with a Secret of type `kubernetes.io/dockerconfigjson` created from a `config.json` file. This is useful with several private registries, because `kubectl create secret docker-registry` only works for a single registry [R1, R2].

## Prevention

- Pin images by explicit version tag or digest; avoid `:latest` in production, which makes it harder to know which version runs and to roll back [R1].
- Create registry Secrets once **per namespace**, because Pods can only reference pull secrets in their own namespace [R1].
- Be careful when typing registry passwords on the command line. The documentation warns that they "may store them in your shell history unprotected" and may be visible to other users while `kubectl` runs [R2]. Prefer creating the Secret from an existing credentials file [R2].
- Check in CI that the image tag was actually pushed before deploying it (team recommendation).

## Related Concepts

- **Container states and the `Waiting` reason**: [R4]. Restart loops of a container that *did* start are covered in `md-k8s-crashloopbackoff`.
- **Pods that cannot be scheduled at all** (`Pending`, no node assigned): see `md-k8s-pod-pending-failedscheduling`.
- **Image registries outside Kubernetes**, for example certificate errors with a private registry: see `md-net-tls-certificate-errors`.

## References

All pages were consulted on 2026-11-02, in their current version, and checked against the documentation source in the `kubernetes/website` repository.

- [R1] Kubernetes Documentation — *Images*. https://kubernetes.io/docs/concepts/containers/images/
- [R2] Kubernetes Documentation — *Pull an Image from a Private Registry*. https://kubernetes.io/docs/tasks/configure-pod-container/pull-image-private-registry/
- [R3] Kubernetes Documentation — *Debug Pods*. https://kubernetes.io/docs/tasks/debug/debug-application/debug-pods/
- [R4] Kubernetes Documentation — *Pod Lifecycle*. https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/
- [R5] Kubernetes project — source file `pkg/kubelet/images/types.go` (consulted on 2026-11-11). https://github.com/kubernetes/kubernetes/blob/master/pkg/kubelet/images/types.go
- [R6] Kubernetes Documentation — *Managing Secrets using kubectl* (consulted on 2026-11-11). https://kubernetes.io/docs/tasks/configmap-secret/managing-secret-using-kubectl/

## Metadata

- **Nature of this document:** written by the project team from the official Kubernetes documentation listed above. It is **not** official Kubernetes documentation.
- **Verification:** each statement followed by a reference was checked against the source text. Statements marked "team observation", "team inference" or "team recommendation" are our own reasoning from documented behaviour.
- **Scope limits:** this guide does not reproduce the exact error strings returned by each registry or container runtime, because they vary between implementations. Read the Events section for the actual message. The values `ErrImagePull`, `InvalidImageName` and `ErrImageNeverPull` come from the kubelet source code [R5]: the documentation pages cited here do not mention them.
