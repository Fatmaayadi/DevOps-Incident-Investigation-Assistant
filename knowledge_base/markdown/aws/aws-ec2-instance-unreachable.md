---
doc_id: md-aws-ec2-unreachable
title: "AWS EC2 Instance Unreachable: SSH connection timed out, permission denied, status checks"
domain: aws
technology: [aws, ec2, vpc, ssh]
category: connectivity
document_type: troubleshooting_guide
difficulty: intermediate
keywords:
  - EC2 unreachable
  - cannot SSH to EC2
  - Connection timed out
  - security group inbound rule port 22
  - network ACL ephemeral ports
  - route table internet gateway
  - public IPv4 address Elastic IP
  - Permission denied (publickey) EC2
  - default username ec2-user ubuntu
  - UNPROTECTED PRIVATE KEY FILE
  - chmod 400 pem
  - status checks failed
  - console output
  - Reachability Analyzer
  - cannot ping instance ICMP
error_messages:
  - "Connection timed out"
  - "Permission denied (publickey)."
  - "WARNING: UNPROTECTED PRIVATE KEY FILE!"
  - "It is required that your private key files are NOT accessible by others."
source_type: team_written_from_official_docs
language: en
references:
  - id: R1
    title: "Troubleshoot issues connecting to your Amazon EC2 Linux instance"
    publisher: AWS Documentation (Amazon EC2 User Guide)
    url: https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/TroubleshootingInstancesConnecting.html
    accessed: 2026-11-02
  - id: R2
    title: "Troubleshoot an unreachable Amazon EC2 instance (reboot, console output, screenshot)"
    publisher: AWS Documentation (Amazon EC2 User Guide)
    url: https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/troubleshoot-unreachable-instance.html
    accessed: 2026-11-02
  - id: R3
    title: "Status checks for Amazon EC2 instances"
    publisher: AWS Documentation (Amazon EC2 User Guide)
    url: https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/monitoring-system-instance-status-check.html
    accessed: 2026-11-02
  - id: R4
    title: "What is Reachability Analyzer?"
    publisher: AWS Documentation (Amazon VPC Reachability Analyzer)
    url: https://docs.aws.amazon.com/vpc/latest/reachability/what-is-reachability-analyzer.html
    accessed: 2026-11-02
  - id: R5
    title: "AWS CLI reference — ec2 get-console-output"
    publisher: AWS Documentation
    url: https://docs.aws.amazon.com/cli/latest/reference/ec2/get-console-output.html
    accessed: 2026-11-02
  - id: R6
    title: "AWS CLI reference — ec2 describe-instance-status"
    publisher: AWS Documentation
    url: https://docs.aws.amazon.com/cli/latest/reference/ec2/describe-instance-status.html
    accessed: 2026-11-02
  - id: R7
    title: "AWS CLI reference — ec2 describe-security-groups"
    publisher: AWS Documentation
    url: https://docs.aws.amazon.com/cli/latest/reference/ec2/describe-security-groups.html
    accessed: 2026-11-02
related_corpus_documents: []
last_reviewed: 2026-11-02
review_status: reviewed by team against sources
---

# AWS EC2 Instance Unreachable: SSH connection timed out, permission denied, status checks

## Overview

When you cannot connect to an EC2 instance, the error message usually tells you which layer is failing:

- **`Connection timed out`**: the network path is blocked. AWS lists the checks in order [R1]:
  1. security group rules;
  2. the subnet route table and its internet gateway;
  3. the network ACL;
  4. the local or corporate firewall;
  5. the instance's public IPv4 address;
  6. the CPU load of the instance.
- **`Permission denied (publickey)`, `Authentication failed`, `Connection closed by [instance] port 22`**: the network works, but SSH authentication fails. Verify "that you are connecting with the appropriate username for your AMI and that you have specified the proper private key (.pem) file" [R1].
- **No response at all, even from AWS tools**: the instance itself may be impaired. Check the status checks and the console output [R2, R3].

## Symptoms

- `ssh` fails with `Connection timed out`, or `Error connecting to [instance], reason: -> Connection timed out: connect` [R1].
- `ssh` fails with `Permission denied (publickey).` [R1].
- `WARNING: UNPROTECTED PRIVATE KEY FILE!`, followed by `This private key will be ignored.` [R1].
- `ping` to the instance does not answer. Ping is ICMP traffic and must be allowed explicitly by the security group [R1].
- The EC2 console shows failed system or instance status checks [R3].

## Possible Causes

| Cause | Explanation |
|---|---|
| **Security group without an SSH rule from your IP** | "You need a security group rule that allows inbound traffic from your local computer's public IPv4 address on the proper port". The default VPC security group does not allow incoming SSH by default [R1] |
| **Changing client IP** | If the rule allows a single, non-static IP, a new IP may no longer match [R1] |
| **No route to the internet gateway** | A route `0.0.0.0/0` (and `::/0` for IPv6) to the VPC's internet gateway is required [R1] |
| **Network ACL** | It must allow inbound SSH from your IP on port 22 **and** outbound traffic to the ephemeral ports 1024-65535 [R1] |
| **No public IPv4 address** | Associate an Elastic IP address if needed [R1] |
| **Corporate or local firewall** | It must allow traffic on port 22 [R1] |
| **Overloaded instance** | High CPU load; check CloudWatch metrics [R1] |
| **Wrong username for the AMI** | For example `ec2-user` (Amazon Linux), `ubuntu` (Ubuntu), `admin` (Debian) [R1] |
| **Wrong or unprotected private key** | SSH ignores a key that others can read or write [R1] |
| **Instance or host impaired** | System status checks detect "problems with your instance that require AWS involvement to repair". Instance status checks detect problems "that require your involvement" [R3] |

## Investigation Steps

1. **Classify the error**: timeout (network), authentication (user/key), or no response at all (instance health) [R1, R3].
2. **For timeouts**, check in this order [R1]:
   - the security group inbound rule for port 22 from your current public IP;
   - the subnet route table and internet gateway;
   - the network ACL, in both directions, including ephemeral ports;
   - the local or corporate firewall;
   - the instance's public IPv4 address.
3. **Use Reachability Analyzer** when the path is complex. When the destination is not reachable, it "identifies the blocking component", such as a security group, network ACL, route table or load balancer [R4].
4. **For authentication errors**, check the default username of the AMI, the `.pem` file used, and its permissions [R1].
5. **For an unresponsive instance**, read the status checks [R3]. Then read the console output, which is "especially useful for troubleshooting kernel problems and service configuration issues that could cause an instance to terminate or become unreachable before its SSH daemon can be started" [R2].

## Diagnostic Commands

```shell
# Verbose SSH attempt with the AMI's default user and the instance key
ssh -v -i ~/.ssh/my-key.pem ec2-user@<public-ip>

# Fix permissions of a private key ignored by SSH (macOS/Linux)
chmod 0400 ~/.ssh/my-key.pem

# Status checks of the instance
aws ec2 describe-instance-status --instance-ids <instance-id>

# Console output (boot messages), useful when SSH never starts
aws ec2 get-console-output --instance-id <instance-id>

# Inbound rules of the instance's security group
aws ec2 describe-security-groups --group-ids <sg-id>
```

Sources: `chmod 0400` [R1]; `describe-instance-status` [R6]; `get-console-output` [R5]; `describe-security-groups` [R7]. The `ssh -v -i` command is a team-selected way to apply the username and key checks of [R1].

## Interpretation of Results

| Observation | Meaning | Next step |
|---|---|---|
| SSH waits, then `Connection timed out` | Network path blocked [R1] | Security group, route table, network ACL, firewall, public IP [R1] |
| Reachability Analyzer reports a blocking component | That component blocks the path [R4] | Fix the indicated rule or route |
| `Permission denied (publickey)` with the right key | Wrong username for the AMI [R1] | Use the default user (for example `ec2-user`, `ubuntu`) [R1] |
| `UNPROTECTED PRIVATE KEY FILE` | SSH ignored the key because of its permissions [R1] | `chmod 0400` on the key (or fix the ACL on Windows) [R1] |
| System status check failed | Problem on the AWS side [R3] | Wait for AWS, or, for EBS-backed instances, stop and start the instance, which in most cases moves it to a new host [R3] |
| Instance status check failed | Problem inside the instance [R3] | Reboot or fix its configuration; read the console output [R2, R3] |
| Ping fails but SSH works | ICMP not allowed by the security group [R1] | Allow ICMP Echo Request if ping is needed [R1] |

## Possible Solutions

- **Security group**: add an inbound rule for TCP 22 from your IP, or from the range of IPs used by your client computers if your IP is not static [R1].
- **Routing**: attach an internet gateway to the VPC, and add a `0.0.0.0/0` route to it in the subnet's route table [R1].
- **Network ACL**: allow inbound port 22 and outbound ephemeral ports 1024-65535 [R1].
- **Public address**: associate an Elastic IP address [R1].
- **Key and user**: use the AMI's default username and the right `.pem`, with permissions `0400` [R1].
- **Unhealthy instance**: reboot it, read its console output, or stop/start an EBS-backed instance after a failed system status check [R2, R3].

## Prevention

- Restrict SSH rules to known source ranges rather than opening port 22 to everyone (team recommendation, consistent with the source-range advice in [R1]).
- Monitor status checks with the `StatusCheckFailed_System` metric and alarms [R3].
- Keep private keys protected (`0400`) and stored safely [R1].

## Related Concepts

- **Refused vs timed-out connections in general**: see `md-net-connection-refused-timeout`.
- **IAM errors, a different "access denied" family**: see `md-aws-iam-access-denied`.
- **Configuration management over SSH**: see `md-ansible-unreachable-become`.

## References

All pages were consulted on 2026-11-02, in their current version.

- [R1] AWS Documentation — *Troubleshoot issues connecting to your Amazon EC2 Linux instance*. https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/TroubleshootingInstancesConnecting.html
- [R2] AWS Documentation — *Troubleshoot an unreachable Amazon EC2 instance*. https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/troubleshoot-unreachable-instance.html
- [R3] AWS Documentation — *Status checks for Amazon EC2 instances*. https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/monitoring-system-instance-status-check.html
- [R4] AWS Documentation — *What is Reachability Analyzer?* https://docs.aws.amazon.com/vpc/latest/reachability/what-is-reachability-analyzer.html
- [R5] AWS CLI reference — *ec2 get-console-output*. https://docs.aws.amazon.com/cli/latest/reference/ec2/get-console-output.html
- [R6] AWS CLI reference — *ec2 describe-instance-status*. https://docs.aws.amazon.com/cli/latest/reference/ec2/describe-instance-status.html
- [R7] AWS CLI reference — *ec2 describe-security-groups*. https://docs.aws.amazon.com/cli/latest/reference/ec2/describe-security-groups.html

## Metadata

- **Nature of this document:** written by the project team from the official AWS documentation listed above. It is **not** official AWS documentation.
- **Verification:** each statement followed by a reference was checked against the source text. Statements marked "team recommendation" are our own reasoning.
- **Scope limits:** Windows instances (RDP), EC2 Instance Connect and Session Manager are not covered in detail.
