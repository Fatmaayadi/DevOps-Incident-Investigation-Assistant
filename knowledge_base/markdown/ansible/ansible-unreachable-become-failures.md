---
doc_id: md-ansible-unreachable-become
title: "Ansible: host UNREACHABLE, SSH authentication failures and privilege escalation (become) problems"
domain: ansible
technology: [ansible, ssh, linux]
category: configuration-management
document_type: troubleshooting_guide
difficulty: intermediate
keywords:
  - UNREACHABLE
  - ansible ping failed
  - SSH connection failed
  - ansible_user remote_user
  - ansible_host ansible_port
  - private key ssh-agent
  - host key checking known_hosts
  - become sudo password
  - --ask-become-pass -K
  - playbook hangs at privilege escalation
  - become_user
  - ansible_python_interpreter
  - -vvvv connection debugging
  - ansible-inventory --graph
error_messages: []
source_type: team_written_from_official_docs
language: en
references:
  - id: R1
    title: "Connection methods and details"
    publisher: Ansible Community Documentation
    url: https://docs.ansible.com/ansible/latest/inventory_guide/connection_details.html
    accessed: 2026-11-02
  - id: R2
    title: "Understanding privilege escalation: become"
    publisher: Ansible Community Documentation
    url: https://docs.ansible.com/ansible/latest/playbook_guide/playbooks_privilege_escalation.html
    accessed: 2026-11-02
  - id: R3
    title: "ansible.builtin.ping module"
    publisher: Ansible Community Documentation
    url: https://docs.ansible.com/ansible/latest/collections/ansible/builtin/ping_module.html
    accessed: 2026-11-02
  - id: R4
    title: "ansible-playbook command-line reference (-v, --private-key, -u, -k, -i)"
    publisher: Ansible Community Documentation
    url: https://docs.ansible.com/ansible/latest/cli/ansible-playbook.html
    accessed: 2026-11-02
  - id: R5
    title: "ansible-inventory command-line reference (--graph, --host, --list)"
    publisher: Ansible Community Documentation
    url: https://docs.ansible.com/ansible/latest/cli/ansible-inventory.html
    accessed: 2026-11-02
  - id: R6
    title: "How to build your inventory (connection variables)"
    publisher: Ansible Community Documentation
    url: https://docs.ansible.com/ansible/latest/inventory_guide/intro_inventory.html
    accessed: 2026-11-02
  - id: R7
    title: "Frequently Asked Questions (Python interpreter)"
    publisher: Ansible Community Documentation
    url: https://docs.ansible.com/ansible/latest/reference_appendices/faq.html
    accessed: 2026-11-02
  - id: R8
    title: "Ansible Configuration Settings (DEFAULT_TIMEOUT)"
    publisher: Ansible Community Documentation
    url: https://docs.ansible.com/ansible/latest/reference_appendices/config.html
    accessed: 2026-11-02
  - id: R9
    title: "Debugging tasks (on_unreachable, play recap example)"
    publisher: Ansible Community Documentation
    url: https://docs.ansible.com/ansible/latest/playbook_guide/playbooks_debugger.html
    accessed: 2026-11-02
  - id: R10
    title: "Building an inventory (Getting started: ping a group)"
    publisher: Ansible Community Documentation
    url: https://docs.ansible.com/projects/ansible/latest/getting_started/get_started_inventory.html
    accessed: 2026-11-02
related_corpus_documents: []
last_reviewed: 2026-11-02
review_status: reviewed by team against sources
---

# Ansible: host UNREACHABLE, SSH authentication failures and privilege escalation (become) problems

## Overview

Ansible runs tasks on managed nodes over SSH by default. "By default, Ansible uses native OpenSSH" [R1], and it "assumes you are using SSH keys to connect to remote machines" [R1]. Ansible then needs a usable Python on the target to run its modules [R3, R7]. When tasks need root, Ansible uses **privilege escalation** (`become`), for example through `sudo` [R2].

Failures therefore happen at three distinct levels:

1. **Connection**: Ansible cannot open an SSH session, and the host is counted as unreachable. The play recap has an `unreachable=` counter for each host, and the task debugger can be set to start `on_unreachable` [R9]. The usual causes are the network, the user, the key, or the host key.
2. **Module execution**: SSH works, but Python is missing or at an unexpected path [R7].
3. **Privilege escalation**: the task runs, but `become` fails or waits for a password [R2].

The `ping` module tests levels 1 and 2 together: it "always returns pong on successful contact". It is useful "to verify the ability to login and that a usable Python is configured". It "is NOT ICMP ping" [R3].

## Symptoms

- `ansible <host> -m ping` does not return `"ping": "pong"` for the host [R3].
- The play recap shows a non-zero `unreachable=` counter for a host [R9].
- A playbook using `become` seems to hang: "most likely it is stuck at the privilege escalation prompt" [R2].
- Errors about a host key that changed after a server reinstall [R1].
- An error that the Python interpreter is not found on the target [R7].

## Possible Causes

| Cause | Explanation |
|---|---|
| **Wrong remote user** | By default, Ansible connects "with the username you are using on the control node"; if it does not exist on the target, set `remote_user` or `ansible_user` [R1] |
| **Wrong address or port** | Connection variables such as `ansible_host` and `ansible_port` in the inventory [R6] |
| **SSH key not available** | Ansible cannot prompt for the passphrase of an encrypted key; "the use of ssh-agent is highly recommended" [R1]. Use `--private-key` or `ansible_ssh_private_key_file` for another key [R1, R4] |
| **Host key mismatch or unknown host** | Host key checking is on by default; a reinstalled host with a different key in `known_hosts` produces an error, and a new host may require interactive confirmation [R1] |
| **Network or firewall** | The SSH port is unreachable (see `md-net-connection-refused-timeout`) |
| **Connection timeout too short** | `DEFAULT_TIMEOUT` (`timeout`, `ANSIBLE_TIMEOUT`) is "the default timeout for connection plugins to use" [R8] |
| **Python missing or elsewhere** | Ansible needs a Python interpreter on the remote host; set `ansible_python_interpreter` [R7] |
| **sudo password required** | Without `--ask-become-pass` (`-K`), the play may hang at the privilege escalation prompt [R2] |
| **`become_user` set without `become`** | "setting become_user does not set become" [R2] |
| **sudo restricted to specific commands** | "You cannot limit privilege escalation permissions to certain commands", because Ansible runs modules from temporary files [R2] |

## Investigation Steps

1. **Check which hosts and variables Ansible actually uses**: `ansible-inventory --graph` and `--host <HOST>` [R5].
2. **Test connection and Python with the ping module** on one host [R3].
3. **Increase verbosity**: "A reasonable level to start is `-vvv`, connection debugging might require `-vvvv`" [R4].
4. **Reproduce the SSH connection by hand** with the same user, key and port as in the inventory (team recommendation).
5. **If SSH works but the module fails**, check the Python interpreter path [R7].
6. **For `become` problems**, check `become`, `become_user` and `become_method`, and run with `-K` if `sudo` needs a password [R2].

## Diagnostic Commands

```shell
# Hosts and groups as Ansible sees them, and the variables of one host
ansible-inventory -i inventory.ini --graph
ansible-inventory -i inventory.ini --host web1

# Connection + Python test on a group (expect "ping": "pong")
ansible myhosts -m ping -i inventory.ini

# Same test with connection debugging and an explicit user and key
ansible web1 -m ping -i inventory.ini -u admin --private-key ~/.ssh/deploy_key -vvvv

# Load an encrypted key into ssh-agent before running Ansible
ssh-agent bash
ssh-add ~/.ssh/id_rsa

# Playbook that needs a sudo password
ansible-playbook -i inventory.ini site.yml -K
```

Sources: `ansible-inventory --graph/--host` [R5]; `ansible myhosts -m ping -i inventory.ini` [R10]; `-u`, `--private-key`, `-v` levels [R4]; `ssh-agent`/`ssh-add` [R1]; `-K` [R2].

## Interpretation of Results

| Observation | Meaning | Next step |
|---|---|---|
| `"ping": "pong"` | Login and Python work [R3] | Look at the failing task or at `become` |
| Ping fails, and `-vvvv` shows a refused or timed-out connection | Network or SSH daemon problem | See `md-net-connection-refused-timeout` |
| `-vvvv` shows authentication failures | Wrong user or key [R1] | Set `ansible_user`, load the key into ssh-agent, or use `--private-key` [R1, R4] |
| Host key error after a server reinstall | `known_hosts` contains the old key [R1] | Update `known_hosts` after verifying the new key |
| Python interpreter not found | Python missing or at another path [R7] | Set `ansible_python_interpreter` [R7] |
| The play hangs on a `become` task | Waiting for the sudo password [R2] | Stop with Ctrl-C and rerun with `-K` [R2] |
| A `become` task fails with a restricted sudoers file | sudo restricted to specific commands [R2] | Use an account without this constraint [R2] |

## Possible Solutions

- **Set the right connection variables** in the inventory: `ansible_host`, `ansible_port`, `ansible_user` [R1, R6].
- **Use SSH keys with ssh-agent** for encrypted keys [R1].
- **Host keys**: update `known_hosts` with the verified new key. Disabling host key checking (`host_key_checking = False`) is possible only "if you understand the implications", because checking "guards against server spoofing and man-in-the-middle attacks" [R1].
- **Python**: point `ansible_python_interpreter` to the interpreter available on the host [R7].
- **Privilege escalation**: set `become: true` explicitly (not only `become_user`), provide the password with `-K` when needed, and avoid restricting sudo to a fixed list of commands [R2].
- **Slow networks**: raise the connection timeout (`timeout` / `ANSIBLE_TIMEOUT`) [R8].

## Prevention

- Keep connection settings in the inventory rather than in individual commands [R6].
- Test new hosts with `ansible <host> -m ping` before running playbooks [R3].
- Use privilege escalation only on the tasks that need it (team recommendation, consistent with [R2]).

## Related Concepts

- **SSH and network reachability**: see `md-net-connection-refused-timeout`, and `md-aws-ec2-unreachable` for EC2 instances.
- **SSH key authentication errors with Git hosting**: see `md-git-push-rejected-ssh`.

## References

All pages were consulted on 2026-11-02, in their current version ("latest" Ansible community documentation).

- [R1] Ansible — *Connection methods and details*. https://docs.ansible.com/ansible/latest/inventory_guide/connection_details.html
- [R2] Ansible — *Understanding privilege escalation: become*. https://docs.ansible.com/ansible/latest/playbook_guide/playbooks_privilege_escalation.html
- [R3] Ansible — *ansible.builtin.ping module*. https://docs.ansible.com/ansible/latest/collections/ansible/builtin/ping_module.html
- [R4] Ansible — *ansible-playbook*. https://docs.ansible.com/ansible/latest/cli/ansible-playbook.html
- [R5] Ansible — *ansible-inventory*. https://docs.ansible.com/ansible/latest/cli/ansible-inventory.html
- [R6] Ansible — *How to build your inventory*. https://docs.ansible.com/ansible/latest/inventory_guide/intro_inventory.html
- [R7] Ansible — *Frequently Asked Questions*. https://docs.ansible.com/ansible/latest/reference_appendices/faq.html
- [R8] Ansible — *Ansible Configuration Settings*. https://docs.ansible.com/ansible/latest/reference_appendices/config.html
- [R9] Ansible — *Debugging tasks*. https://docs.ansible.com/ansible/latest/playbook_guide/playbooks_debugger.html
- [R10] Ansible — *Building an inventory* (getting started). https://docs.ansible.com/projects/ansible/latest/getting_started/get_started_inventory.html

## Metadata

- **Nature of this document:** written by the project team from the official Ansible community documentation listed above. It is **not** official Ansible documentation.
- **Verification:** each statement followed by a reference was checked against the source text. Statements marked "team observation" or "team recommendation" are our own reasoning.
- **Scope limits:** the exact text of Ansible's UNREACHABLE error is not quoted, because it is not reproduced in the cited pages. Windows (WinRM) and network devices are not covered.
