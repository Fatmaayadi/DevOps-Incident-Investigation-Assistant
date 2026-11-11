---
doc_id: md-linux-systemd-service-failure
title: systemd Service Fails to Start or Keeps Failing
domain: linux
technology: [linux, systemd, journald]
category: service-failure
document_type: troubleshooting_guide
difficulty: intermediate
keywords:
  - systemd service failed
  - systemctl status
  - journalctl -u
  - unit failed state
  - ExecStart
  - Type=simple forking notify
  - EnvironmentFile missing
  - WorkingDirectory
  - User=
  - start rate limit
  - StartLimitBurst
  - daemon-reload
  - TimeoutStartSec
  - Restart=on-failure
error_messages: []
source_type: team_written_from_official_docs
language: en
references:
  - id: R1
    title: "systemctl(1)"
    publisher: systemd project (freedesktop.org)
    url: https://www.freedesktop.org/software/systemd/man/latest/systemctl.html
    accessed: 2026-11-02
  - id: R2
    title: "journalctl(1)"
    publisher: systemd project (freedesktop.org)
    url: https://www.freedesktop.org/software/systemd/man/latest/journalctl.html
    accessed: 2026-11-02
  - id: R3
    title: "systemd.service(5) (Type=, ExecStart=, Restart=, RestartSec=, TimeoutStartSec=)"
    publisher: systemd project (freedesktop.org)
    url: https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html
    accessed: 2026-11-02
  - id: R4
    title: "systemd.exec(5) (User=, WorkingDirectory=, EnvironmentFile=, Process Exit Codes, $SERVICE_RESULT)"
    publisher: systemd project (freedesktop.org)
    url: https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html
    accessed: 2026-11-02
  - id: R5
    title: "systemd.unit(5) (StartLimitIntervalSec=, StartLimitBurst=)"
    publisher: systemd project (freedesktop.org)
    url: https://www.freedesktop.org/software/systemd/man/latest/systemd.unit.html
    accessed: 2026-11-02
  - id: R6
    title: "systemd-analyze(1) (verify)"
    publisher: systemd project (freedesktop.org)
    url: https://www.freedesktop.org/software/systemd/man/latest/systemd-analyze.html
    accessed: 2026-11-02
last_reviewed: 2026-11-02
review_status: reviewed by team against sources
---

# systemd Service Fails to Start or Keeps Failing

## Overview

On most Linux distributions, services are managed by systemd. When a unit fails, "i.e. process exiting with non-zero error code, terminating abnormally or timing out", it "will automatically enter the 'failed' state". Its exit code and status are recorded for the administrator until the service is stopped, restarted or reset [R1].

The investigation therefore relies on two tools:

- `systemctl status`, which shows "runtime status information … followed by most recent log data from the journal" [R1];
- `journalctl -u <unit>`, which shows the messages of a given unit [R2].

The causes are usually either **in the application** (it crashes or exits at startup) or **in the unit file**: wrong command, wrong type, missing file, wrong user or directory, timeout, or start rate limiting.

## Symptoms

- `systemctl status <unit>` shows the unit as `failed`, with the exit code and the last log lines [R1].
- `systemctl --failed` lists it among the "units in failed state" [R1].
- The service starts, then stops again repeatedly, and after a few attempts systemd no longer starts it: units "started more than burst times within an interval time span are not permitted to start any more" [R5].
- The start command hangs, then the unit fails after a timeout [R3].
- The unit fails with an exit code set by systemd itself, because it could not apply the execution settings of the unit. The "Process Exit Codes" section of systemd.exec(5) lists them, for example [R4]:
  - `200` `EXIT_CHDIR`: "Changing to the requested working directory failed. See WorkingDirectory= above.";
  - `203` `EXIT_EXEC`: "The actual process execution failed (specifically, the execve(2) system call)." "Most likely this is caused by a missing or non-accessible executable file.";
  - `217` `EXIT_USER`: "Failed to determine or change user credentials, or to set up user namespacing. See User=/PrivateUsers= above."
- When the start rate limit is reached, systemd records the result `start-limit-hit`: "A start limit was defined for the unit and it was hit, causing the unit to fail to start" [R4].

## Possible Causes

| Cause | Explanation |
|---|---|
| **The application exits with an error** | Non-zero exit, abnormal termination: the unit enters `failed` [R1] |
| **Wrong `ExecStart=` command** | The first argument must be an absolute path to an executable, or a simple file name without slashes resolved in a fixed search path [R3] |
| **Wrong `Type=`** | With `Type=forking`, systemd expects the `ExecStart=` process to fork and the parent to exit when start-up is complete [R3]. A program that does not behave this way does not match the declared type (team inference) |
| **Start-up timeout** | If a daemon "does not signal start-up completion within the configured time" (`TimeoutStartSec=`), the service is considered failed [R3] |
| **Missing `EnvironmentFile=`** | "If the file does not exist, cannot be read, or contains invalid content, the service will fail to start", unless the path is prefixed with `-` [R4] |
| **Missing `WorkingDirectory=`** | A missing working directory is fatal unless the setting is prefixed with `-` [R4] |
| **Wrong `User=`/`Group=`** | The processes run as that user [R4]; it may lack permissions on files or ports (team inference) |
| **Start rate limit reached** | Too many restarts within `StartLimitIntervalSec=` / `StartLimitBurst=` [R5] |
| **Unit file edited but not reloaded** | `systemctl cat` shows the files on disk, "which might not match the system manager's understanding of these units if any unit files were updated on disk and the daemon-reload" command was not issued [R1] |
| **Disk full or missing dependency** | The application cannot write or reach what it needs (team inference; see `md-linux-disk-full`) |

## Investigation Steps

1. **Read the status**: state, exit code, and the most recent log lines [R1].
2. **Read the full logs of the unit**, starting from the end, with explanatory catalog texts when available (`-x`) [R2].
3. **Read the unit definition actually used**, including drop-in files, with `systemctl cat` [R1].
4. **Validate the unit file** with `systemd-analyze verify`, which "will load unit files and print warnings if any errors are detected" [R6].
5. **Check the referenced files and identity**: the `ExecStart=` path, `EnvironmentFile=`, `WorkingDirectory=` and `User=` [R3, R4].
6. **Run the command by hand** as the service user, with the same environment, to see the error directly (team recommendation).
7. **If the unit no longer starts at all**, check whether the start rate limit was hit, then reset it after fixing the cause [R1, R5].

## Diagnostic Commands

```shell
# State, exit code, last journal lines
systemctl status myapp.service

# All failed units
systemctl --failed

# Logs of the unit, jump to the end, with catalog explanations
journalctl -u myapp.service -e -x

# Follow new messages while restarting the service in another terminal
journalctl -u myapp.service -f

# Unit file and drop-ins as stored on disk
systemctl cat myapp.service

# Check the unit file for errors
systemd-analyze verify /etc/systemd/system/myapp.service

# After editing a unit file: reload, then restart
sudo systemctl daemon-reload
sudo systemctl restart myapp.service

# After fixing the cause: clear the failed state and the start rate limit counter
sudo systemctl reset-failed myapp.service
```

Sources: `status`, `--failed`, `cat`, `daemon-reload`, `reset-failed` [R1]; `-u`, `-e`, `-x`, `-f` [R2]; `verify` [R6].

## Interpretation of Results

| Observation | Meaning | Next step |
|---|---|---|
| Status `failed` with a non-zero exit code and an application error in the logs | The application itself fails [R1, R2] | Fix the application error (configuration, dependency, permission) |
| Exit code `203` (`EXIT_EXEC`) | `execve` failed, most likely a missing or non-accessible executable [R4] | Check the `ExecStart=` path and the file's permissions [R3] |
| Exit code `200` (`EXIT_CHDIR`) or `217` (`EXIT_USER`) | `WorkingDirectory=` or `User=` could not be applied [R4] | Fix the directory or the user [R4] |
| Logs mention a missing executable or file | `ExecStart=` path, `EnvironmentFile=` or `WorkingDirectory=` problem [R3, R4] | Fix the path, or make the file optional with `-` if appropriate [R4] |
| The unit fails after waiting for a long time | Start-up timeout, possibly a `Type=` mismatch [R3] | Check `Type=` and `TimeoutStartSec=` |
| The unit refuses to start after several quick failures | Start rate limit reached [R5] | Fix the cause, then `systemctl reset-failed` [R1] |
| `systemd-analyze verify` prints warnings | Syntax or reference errors in the unit file [R6] | Correct the unit file, then `daemon-reload` [R1] |
| `systemctl cat` shows the new content, but the behaviour is old | The manager has not reloaded the files [R1] | Run `systemctl daemon-reload` [R1] |

## Possible Solutions

- **Fix the application error** shown in the journal, then restart the unit.
- **Correct the unit file**: absolute `ExecStart=` path, appropriate `Type=` (the documentation discourages `forking` and recommends `notify`, `notify-reload` or `dbus` instead [R3]), existing `WorkingDirectory=` and `EnvironmentFile=`, correct `User=` [R3, R4].
- **Reload after every edit**: `systemctl daemon-reload` "reload[s] all unit files, and recreate[s] the entire dependency tree" [R1].
- **Use automatic restarts with care**: `Restart=` configures restarts when the process exits, is killed or times out [R3], and `RestartSec=` sets the delay before restarting (100 ms by default) [R3]. Combined with the start rate limit [R5], this avoids tight restart loops.
- **Reset the failed state** once the cause is fixed: `systemctl reset-failed` also resets the start rate limit counter [R1].

## Prevention

- Validate unit files with `systemd-analyze verify` before deploying them [R6].
- Keep unit files in configuration management (for example Ansible), and always follow an edit with `daemon-reload` (team recommendation).
- Make the application log a clear message before exiting on a configuration error, so that the journal shows the cause (team recommendation).

## Related Concepts

- **Disk full preventing a service from writing**: see `md-linux-disk-full`.
- **The same "process exits, supervisor restarts it" pattern in containers**: see `md-docker-container-exits` and `md-k8s-crashloopbackoff`.
- **Service running but not reachable**: see `md-net-connection-refused-timeout`.

## References

All pages were consulted on 2026-11-02, in their current version ("latest" systemd manual pages on freedesktop.org).

- [R1] systemd — *systemctl(1)*. https://www.freedesktop.org/software/systemd/man/latest/systemctl.html
- [R2] systemd — *journalctl(1)*. https://www.freedesktop.org/software/systemd/man/latest/journalctl.html
- [R3] systemd — *systemd.service(5)*. https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html
- [R4] systemd — *systemd.exec(5)*. https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html
- [R5] systemd — *systemd.unit(5)*. https://www.freedesktop.org/software/systemd/man/latest/systemd.unit.html
- [R6] systemd — *systemd-analyze(1)*. https://www.freedesktop.org/software/systemd/man/latest/systemd-analyze.html

## Metadata

- **Nature of this document:** written by the project team from the official systemd manual pages listed above. It is **not** official systemd documentation.
- **Verification:** each statement followed by a reference was checked against the source text. Statements marked "team inference" or "team recommendation" are our own reasoning.
- **Scope limits:** options and defaults can differ on older systemd versions shipped by some distributions; check `man systemd.service` on the affected host.
