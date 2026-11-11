---
doc_id: md-linux-disk-full
title: "Linux Disk Full: No space left on device"
domain: linux
technology: [linux, filesystem, systemd-journald]
category: resource-exhaustion
document_type: troubleshooting_guide
difficulty: beginner
keywords:
  - No space left on device
  - ENOSPC
  - disk full
  - filesystem full
  - inodes exhausted
  - df -h
  - df -i
  - du
  - deleted files still open
  - lsof +L1
  - journal disk usage
  - log rotation
error_messages:
  - "No space left on device"
source_type: team_written_from_official_docs
language: en
references:
  - id: R1
    title: "errno(3) — Linux manual page (ENOSPC)"
    publisher: man7.org (Linux man-pages project)
    url: https://man7.org/linux/man-pages/man3/errno.3.html
    accessed: 2026-11-02
  - id: R2
    title: "df(1) — Linux manual page"
    publisher: man7.org (Linux man-pages project)
    url: https://man7.org/linux/man-pages/man1/df.1.html
    accessed: 2026-11-02
  - id: R3
    title: "du(1) — Linux manual page"
    publisher: man7.org (Linux man-pages project)
    url: https://man7.org/linux/man-pages/man1/du.1.html
    accessed: 2026-11-02
  - id: R4
    title: "unlink(2) — Linux manual page"
    publisher: man7.org (Linux man-pages project)
    url: https://man7.org/linux/man-pages/man2/unlink.2.html
    accessed: 2026-11-02
  - id: R5
    title: "lsof(8) manual page (+L1 option)"
    publisher: lsof project (lsof-org on GitHub)
    url: https://github.com/lsof-org/lsof/blob/master/Lsof.8
    accessed: 2026-11-02
  - id: R6
    title: "journalctl(1) (--disk-usage, --vacuum-size)"
    publisher: systemd project (freedesktop.org)
    url: https://www.freedesktop.org/software/systemd/man/latest/journalctl.html
    accessed: 2026-11-02
  - id: R7
    title: "Node-pressure Eviction (DiskPressure node condition)"
    publisher: Kubernetes Documentation
    url: https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/
    accessed: 2026-11-02
last_reviewed: 2026-11-02
review_status: reviewed by team against sources
---

# Linux Disk Full: No space left on device

## Overview

`ENOSPC` is the error code meaning "No space left on device" [R1]. Programs receive it when they try to write to a filesystem that cannot accept more data. Typical consequences in production are services that crash or refuse to start, databases that stop writing, failed builds, and missing logs (team observation).

A filesystem can be "full" in two different ways:

1. **No free blocks**: the data space is used up. `df` shows the usage [R2].
2. **No free inodes**: every file needs an inode, so millions of tiny files can exhaust inodes while space remains. `df -i` lists "inode information instead of block usage" [R2].

A third, confusing case is **space used by deleted files that are still open**. "If the name was the last link to a file but any processes still have the file open, the file will remain in existence until the last file descriptor referring to it is closed" [R4]. Deleting a large log file that a running process still writes to therefore does **not** free the space.

## Symptoms

- Commands or applications fail with `No space left on device` [R1].
- `df -h` shows a filesystem at or near 100 % [R2].
- `df -h` shows free space, but file creation still fails: check inodes with `df -i` [R2].
- `df` reports much more used space than `du` finds in the files: typical of deleted files still held open (team inference based on [R4, R5]).
- On a Kubernetes node, the `DiskPressure` condition appears when available disk space or inodes satisfy an eviction threshold [R7].

## Possible Causes

| Cause | Explanation |
|---|---|
| **Logs growing without rotation** | Application or system logs fill the filesystem (team observation) |
| **System journal too large** | `journalctl --disk-usage` shows the space used by journal files [R6] |
| **Many small files** (cache, sessions, mail queues) | Inodes exhausted while blocks remain [R2] |
| **Deleted files still open** | The space is released only when the last file descriptor is closed [R4] |
| **Wrong filesystem** | Data written to `/` instead of a dedicated volume, for example after a mount failed (team inference) |
| **Container images, volumes and build caches** | On container hosts, images and volumes accumulate (team observation; see `md-docker-container-exits` for container-side checks) |

## Investigation Steps

1. **Identify the full filesystem** and its mount point with `df -h`. Add `-T` to see the filesystem type [R2].
2. **Check inodes** on the same filesystem with `df -i` [R2].
3. **Find what uses the space**, one level at a time, without crossing into other filesystems: `du -x` with `--max-depth` and human-readable sizes [R3].
4. **Look for deleted files that are still open** with `lsof +L1`, which selects "open files that have been unlinked" [R5].
5. **Check the system journal size** with `journalctl --disk-usage` [R6].
6. **Find the writer**: which service writes there, and since when? Correlate with recent deployments or configuration changes (team recommendation).

## Diagnostic Commands

```shell
# Usage per filesystem, human-readable, with filesystem type
df -h -T

# Inode usage per filesystem
df -i

# Biggest directories under /var, staying on the same filesystem, one level deep
sudo du -x -h --max-depth=1 /var | sort -h

# Total size of a directory
du -s -h /var/log

# Deleted files still held open by a process
sudo lsof +L1

# Disk space used by the systemd journal
journalctl --disk-usage
```

Sources: `df -h`, `-i`, `-T` [R2]; `du -x`, `-h`, `--max-depth`, `-s` [R3]; `lsof +L1` [R5]; `journalctl --disk-usage` [R6]. Piping `du` into `sort -h` is a team addition to rank the results.

## Interpretation of Results

| Observation | Meaning | Next step |
|---|---|---|
| `df -h` shows `Use%` 100 % on one mount point | That filesystem is out of blocks [R2] | Find the large directories with `du -x` [R3] |
| `df -i` shows `IUse%` 100 % | Inodes exhausted [R2] | Look for directories with huge numbers of small files |
| `lsof +L1` lists large files with a process | Deleted files are still open; their space is not freed [R4, R5] | Restart or signal the process so that it closes the file |
| `journalctl --disk-usage` reports several GB | The journal takes a large share [R6] | Vacuum the journal (see below) |
| `du` total is much smaller than `df` usage | Space used by open deleted files, or hidden under a mount point (team inference) | Check `lsof +L1` first |

## Possible Solutions

- **Free space safely**: compress or move old logs and remove unneeded artefacts. Prefer truncating a log file that a process still writes to over deleting it, because deleting does not free space while the file is open [R4] (team recommendation).
- **Release deleted-but-open files**: restart the process that holds them, so that the last file descriptor is closed [R4, R5].
- **Shrink the journal**: `journalctl --vacuum-size=500M` "removes the oldest archived journal files until the disk space they use falls below the specified size" [R6].
- **Inodes**: delete or archive the directories that contain very many small files, and fix the application that creates them (team recommendation).
- **Add capacity**: extend the volume or move the data to a dedicated filesystem (team recommendation).

## Prevention

- Configure log rotation for application logs, and size limits for the journal (team recommendation).
- Alert on both disk usage and inode usage, from `df -h` and `df -i` metrics [R2].
- Put fast-growing data (logs, databases, container storage) on dedicated filesystems, so that a full volume does not stop the whole system (team recommendation).
- On Kubernetes nodes, watch the `DiskPressure` condition [R7].

## Related Concepts

- **Services that fail to start because they cannot write**: see `md-linux-systemd-service-failure`.
- **Kubernetes node disk pressure and eviction**: see `md-k8s-oomkilled-resource-limits` for the memory counterpart, and [R7].

## References

All pages were consulted on 2026-11-02, in their current version.

- [R1] Linux man-pages — *errno(3)*. https://man7.org/linux/man-pages/man3/errno.3.html
- [R2] Linux man-pages — *df(1)*. https://man7.org/linux/man-pages/man1/df.1.html
- [R3] Linux man-pages — *du(1)*. https://man7.org/linux/man-pages/man1/du.1.html
- [R4] Linux man-pages — *unlink(2)*. https://man7.org/linux/man-pages/man2/unlink.2.html
- [R5] lsof project — *lsof(8)* manual page source. https://github.com/lsof-org/lsof/blob/master/Lsof.8
- [R6] systemd project — *journalctl(1)*. https://www.freedesktop.org/software/systemd/man/latest/journalctl.html
- [R7] Kubernetes Documentation — *Node-pressure Eviction*. https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/

## Metadata

- **Nature of this document:** written by the project team from the official sources listed above. It is **not** official documentation of these projects.
- **Verification:** each statement followed by a reference was checked against the source text. Statements marked "team observation", "team inference" or "team recommendation" are our own reasoning.
- **Scope limits:** filesystem-specific behaviour (reserved blocks, quotas, copy-on-write filesystems) is not covered.
