---
doc_id: md-sre-incident-triage
title: "Incident Triage and Troubleshooting Method (SRE practices)"
domain: sre
technology: [sre, incident-response, monitoring]
category: incident-response
document_type: troubleshooting_guide
difficulty: intermediate
keywords:
  - incident triage
  - incident response
  - stop the bleeding
  - mitigate before root cause
  - problem report
  - hypothetico-deductive troubleshooting
  - what changed recently
  - rollback
  - four golden signals
  - latency traffic errors saturation
  - symptoms versus causes
  - incident commander
  - incident state document
  - when to declare an incident
  - blameless postmortem
  - production outage
error_messages: []
source_type: team_written_from_official_docs
language: en
references:
  - id: R1
    title: "Site Reliability Engineering, chapter 12 — Effective Troubleshooting"
    publisher: Google (sre.google), licensed under CC BY-NC-ND 4.0
    url: https://sre.google/sre-book/effective-troubleshooting/
    accessed: 2026-11-02
  - id: R2
    title: "Site Reliability Engineering, chapter 14 — Managing Incidents"
    publisher: Google (sre.google), licensed under CC BY-NC-ND 4.0
    url: https://sre.google/sre-book/managing-incidents/
    accessed: 2026-11-02
  - id: R3
    title: "Site Reliability Engineering, chapter 15 — Postmortem Culture: Learning from Failure"
    publisher: Google (sre.google), licensed under CC BY-NC-ND 4.0
    url: https://sre.google/sre-book/postmortem-culture/
    accessed: 2026-11-02
  - id: R4
    title: "Site Reliability Engineering, chapter 6 — Monitoring Distributed Systems"
    publisher: Google (sre.google), licensed under CC BY-NC-ND 4.0
    url: https://sre.google/sre-book/monitoring-distributed-systems/
    accessed: 2026-11-02
  - id: R5
    title: "Site Reliability Engineering, chapter 13 — Emergency Response"
    publisher: Google (sre.google), licensed under CC BY-NC-ND 4.0
    url: https://sre.google/sre-book/emergency-response/
    accessed: 2026-11-02
related_corpus_documents: []
last_reviewed: 2026-11-02
review_status: reviewed by team against sources
---

# Incident Triage and Troubleshooting Method (SRE practices)

## Overview

This guide describes **how to approach** any production incident before going into technology-specific guides. It is our own summary of chapters 6, 12, 13, 14 and 15 of Google's *Site Reliability Engineering* book, published online under the CC BY-NC-ND 4.0 licence [R1-R5]. The book is not reproduced here: please read the linked chapters for the full text.

Three ideas from these chapters structure the method:

1. **Mitigate first, find the root cause second.** In a major outage, the instinct to start root-causing immediately should be ignored. The priority is to make the system work as well as possible, for example by diverting traffic or disabling subsystems. As the chapter puts it: "Stopping the bleeding should be your first priority" [R1].
2. **Troubleshoot methodically.** The book describes troubleshooting as an application of the hypothetico-deductive method. From observations and knowledge of the system, you form hypotheses about the cause, then test them, by comparing them with the observed state or by changing the system in a controlled way [R1].
3. **Organize the response when it grows**: clear roles, a live incident document, and explicit handoffs [R2]. Afterwards, write a blameless postmortem [R3].

## Symptoms

This guide applies to any situation where:

- an alert fires or a user reports that "the system is slow" or "returns errors" [R1];
- the impact is not yet known (one user or everyone?) [R1];
- several teams may need to be involved [R2].

The book suggests declaring an incident if any of the following is true [R2]:

- a second team is needed;
- the outage is visible to customers;
- the issue is still unsolved after an hour of concentrated analysis.

## Possible Causes

This guide does not list technical causes; the domain guides do (see Related Concepts). It lists the **reasoning errors** that make troubleshooting fail, as described in [R1]:

- looking at irrelevant symptoms, or misreading what a metric means;
- not knowing how to change the system safely to test a hypothesis;
- preferring improbable theories, or assuming that the cause of a past incident is happening again. The book's advice: "when you hear hoofbeats, think of horses not zebras" [R1];
- chasing correlations that are coincidences or share a common cause, since correlation is not causation [R1].

A frequent real cause to check early is **what changed recently**: the book notes that working systems tend to keep working "until acted upon by an external force", such as a configuration change or a shift in load [R1].

## Investigation Steps

1. **Get a good problem report**: expected behaviour, actual behaviour, and how to reproduce it if possible. Record it in a searchable place, such as a ticket [R1].
2. **Triage**: estimate the severity and the scope of the impact, and respond proportionally. A full emergency response suits a global outage, not a problem affecting one user [R1].
3. **Stop the bleeding**: apply a mitigation (divert traffic, roll back, disable a feature) before searching for the root cause [R1].
4. **Examine** the system with metrics, logs and the state exposed by components [R1]. The four golden signals give a first view of a user-facing system: latency, traffic, errors and saturation [R4].
5. **Diagnose** [R1]:
   - simplify the problem and divide the system: walk the stack from one end, or bisect it;
   - ask *what* the system is doing, *where* its resources go, and *why*;
   - check what touched it last.
6. **Test and treat** [R1]:
   - test hypotheses in decreasing order of likelihood, taking into account the risk of each test;
   - beware of tests with side effects or confounding factors;
   - take clear notes of hypotheses, tests and results.
7. **If the incident grows**, do not stay alone: the book advises to pull in more people when overwhelmed, and to follow the company's incident response process if one exists [R5]. Separate the roles: incident commander, operations, communication, planning. Keep a live incident document, and hand off explicitly [R2].
8. **After resolution**, write a blameless postmortem if the incident meets your criteria. Examples given in [R3]: user-visible downtime beyond a threshold, data loss, on-call intervention such as a rollback, or a resolution time above a threshold.

## Diagnostic Commands

This guide is technology-independent. Use the first checks of the guide that matches the symptom:

| Symptom reported | First guide to open |
|---|---|
| HTTP 502/503/504 from a proxy or load balancer | `md-net-http-502-503-504` |
| "Connection refused" / "timed out" | `md-net-connection-refused-timeout` |
| Hostname cannot be resolved | `md-net-dns-resolution-failure` |
| TLS / certificate errors | `md-net-tls-certificate-errors` |
| Kubernetes Pod restarting, `CrashLoopBackOff` | `md-k8s-crashloopbackoff` |
| Kubernetes image cannot be pulled | `md-k8s-imagepullbackoff` |
| Container killed for memory | `md-k8s-oomkilled-resource-limits` |
| Pod stuck in `Pending` | `md-k8s-pod-pending-failedscheduling` |
| Service not reachable inside the cluster | `md-k8s-service-no-endpoints` |
| Docker container stops at once | `md-docker-container-exits` |
| Docker permission / daemon errors | `md-docker-daemon-permission-denied` |
| Docker port or container-to-container networking | `md-docker-networking-ports` |
| Disk full | `md-linux-disk-full` |
| systemd service failing | `md-linux-systemd-service-failure` |
| Git push rejected / SSH key errors | `md-git-push-rejected-ssh` |
| GitHub Actions failures | `md-github-actions-failures` |
| GitLab CI job failures | `md-gitlab-ci-job-failures` |
| Terraform state locked | `md-terraform-state-lock` |
| Terraform init errors | `md-terraform-init-errors` |
| Ansible host unreachable / become problems | `md-ansible-unreachable-become` |
| AWS AccessDenied | `md-aws-iam-access-denied` |
| EC2 instance unreachable | `md-aws-ec2-unreachable` |

## Interpretation of Results

| Observation during triage | Meaning | Next step |
|---|---|---|
| Errors started right after a deployment or configuration change | "What touched it last" is the most likely lead [R1] | Roll back first to mitigate, then investigate [R1] |
| Errors and latency rise together with saturation | The system may be overloaded [R4] | Shed or divert load; see chapters 21-22 of the book |
| A metric correlates with the problem but there is no mechanism linking them | Possible spurious correlation [R1] | Look for a common cause before acting on it |
| A test gives a negative result | It still rules out a hypothesis (team note, consistent with the "Negative Results Are Magic" section of [R1]) | Record it, and move to the next hypothesis |
| Several teams are working without coordination | Signs of an unmanaged incident [R2] | Name an incident commander and open an incident document [R2] |

## Possible Solutions

- **Mitigations** to restore service quickly, given as examples in [R1]: divert traffic from a broken cluster, drop traffic to prevent a cascading failure, disable subsystems to reduce load. Rolling back a release or configuration is a standard on-call intervention [R3].
- **Root cause fix**: once the service is stable, apply the fix found by the diagnosis, through the domain guides listed above.
- **Coordination**: separate the roles (command, operations, communication, planning). Only the operations team should modify the system during an incident [R2].

## Prevention

- Monitor the four golden signals, and alert on symptoms that users see [R4].
- Record deployments and configuration changes so that "what changed" can be answered quickly [R1].
- Practise incident management regularly, and write blameless postmortems that focus on systems and processes rather than on individuals [R2, R3].
- Keep a history of outages and follow up on the actions identified in postmortems, so that a nearly identical outage does not happen again [R5].

## Related Concepts

- All the domain-specific guides listed in the Diagnostic Commands table.
- Corpus note: the PDF copy of *Site Reliability Engineering* found in the original document collection was excluded for provenance reasons. This guide relies only on the official online edition [R1-R5].

## References

Chapters of *Site Reliability Engineering: How Google Runs Production Systems* (Beyer, Jones, Petoff, Murphy, eds.), official online edition, © 2017 Google, licensed under CC BY-NC-ND 4.0. All pages were consulted on 2026-11-02.

- [R1] Chapter 12 — *Effective Troubleshooting*. https://sre.google/sre-book/effective-troubleshooting/
- [R2] Chapter 14 — *Managing Incidents*. https://sre.google/sre-book/managing-incidents/
- [R3] Chapter 15 — *Postmortem Culture: Learning from Failure*. https://sre.google/sre-book/postmortem-culture/
- [R4] Chapter 6 — *Monitoring Distributed Systems*. https://sre.google/sre-book/monitoring-distributed-systems/
- [R5] Chapter 13 — *Emergency Response*. https://sre.google/sre-book/emergency-response/

## Metadata

- **Nature of this document:** a summary written by the project team, with short attributed quotations, from the official online edition of the SRE book. It is **not** a copy or an adaptation of the book, and not official Google documentation.
- **Verification:** each statement followed by a reference was checked against the chapter text. Statements marked "team note" are our own reasoning.
- **Licence note:** the book is CC BY-NC-ND 4.0. Only its links and short quotations are used here; the book itself is not indexed (decision recorded in the project manifest).
