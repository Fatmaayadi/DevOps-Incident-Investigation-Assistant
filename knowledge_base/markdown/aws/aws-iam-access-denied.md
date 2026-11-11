---
doc_id: md-aws-iam-access-denied
title: "AWS IAM AccessDenied: is not authorized to perform"
domain: aws
technology: [aws, iam, sts, aws-organizations]
category: access-permissions
document_type: troubleshooting_guide
difficulty: intermediate
keywords:
  - AccessDenied
  - is not authorized to perform
  - UnauthorizedOperation
  - explicit deny
  - implicit deny
  - identity-based policy
  - resource-based policy
  - bucket policy
  - permissions boundary
  - service control policy SCP
  - session policy
  - assumed role
  - temporary credentials expired
  - sts get-caller-identity
  - sts decode-authorization-message
  - IAM policy simulator
  - condition keys
error_messages:
  - "is not authorized to perform"
  - "because no service control policy allows the"
  - "Client.UnauthorizedOperation"
source_type: team_written_from_official_docs
language: en
references:
  - id: R1
    title: "Troubleshoot access denied error messages"
    publisher: AWS Documentation (IAM User Guide)
    url: https://docs.aws.amazon.com/IAM/latest/UserGuide/troubleshoot_access-denied.html
    accessed: 2026-11-02
  - id: R2
    title: "Policy evaluation logic"
    publisher: AWS Documentation (IAM User Guide)
    url: https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_evaluation-logic.html
    accessed: 2026-11-02
  - id: R3
    title: "AWS CLI reference — sts get-caller-identity"
    publisher: AWS Documentation
    url: https://docs.aws.amazon.com/cli/latest/reference/sts/get-caller-identity.html
    accessed: 2026-11-02
  - id: R4
    title: "AWS CLI reference — sts decode-authorization-message"
    publisher: AWS Documentation
    url: https://docs.aws.amazon.com/cli/latest/reference/sts/decode-authorization-message.html
    accessed: 2026-11-02
  - id: R5
    title: "Test IAM policies with the IAM policy simulator"
    publisher: AWS Documentation (IAM User Guide)
    url: https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_testing-policies.html
    accessed: 2026-11-02
related_corpus_documents: []
last_reviewed: 2026-11-02
review_status: reviewed by team against sources
---

# AWS IAM AccessDenied: is not authorized to perform

## Overview

"Access denied errors appear when AWS explicitly or implicitly denies an authorization request" [R1]:

- **explicit deny**: "a policy contains a `Deny` statement for the specific AWS action";
- **implicit deny**: "there is no applicable `Deny` statement and also no applicable `Allow` statement". "Because an IAM policy denies an IAM principal by default, the policy must explicitly allow the principal to perform an action" [R1].

Several **policy types** can apply to the same request. In each pair below, an explicit deny in either policy overrides an allow [R2]:

- **Identity-based and resource-based policies**, in the same account: the result is the **union** of their permissions [R2].
- **Identity-based policies and a permissions boundary**: the result is the **intersection** of the two [R2].
- **AWS Organizations SCPs/RCPs**: for a member account accessing a resource without a resource-based policy, the result is the **intersection** of the user's policies and the SCPs/RCPs [R2].

The diagnosis therefore consists of three questions:

1. **Who** made the request?
2. **Which action** on **which resource** was denied?
3. **Which policy type** blocked it, or failed to allow it?

## Symptoms

- An error such as `User: arn:aws:iam::123456789012:user/mateojackson is not authorized to perform: widgets:GetWidget on resource: my-example-widget` [R1].
- With SCPs: `… is not authorized to perform: codecommit:ListRepositories because no service control policy allows the codecommit:ListRepositories action` [R1].
- Some operations return `Client.UnauthorizedOperation` (an HTTP 403 response) with an **encoded message** that contains more details [R4].
- The same command works for one person or role but not for another, or works in one account but not in another (team observation).

## Possible Causes

| Cause | Explanation |
|---|---|
| **No `Allow` in the identity-based policy** | You must have "the identity-based policy permission to call the action and resource" [R1] |
| **Explicit `Deny`** in one of the policies | It overrides any allow [R1, R2] |
| **Resource-based policy** (S3, SNS, SQS…) | For a different account, "both your identity-based policies and the resource-based policies must grant you permission" [R1] |
| **Condition not met** | "If any conditions are set, you must also meet those conditions" [R1]. Condition key names are not case-sensitive, which can cause unexpected denials [R1] |
| **Permissions boundary** | Identity policies allow the request, but the boundary does not, so the request is denied [R1] |
| **SCP missing an `Allow`, or containing a `Deny`** | Implicit or explicit denial by AWS Organizations [R1] |
| **Temporary credentials** | Expired credentials, or session policies that limit the role session. Session permissions are "the intersection of the role's identity-based policies and the session policies" [R1] |
| **Wrong identity** | The CLI, SDK or job uses other credentials than expected (team inference; check with `get-caller-identity` [R3]) |

## Investigation Steps

1. **Identify the caller**: run `aws sts get-caller-identity`. It returns the IAM user or role whose credentials are used, and requires no permissions [R3].
2. **Read the error message carefully.** "Check if the error message includes the type and Amazon Resource Name (ARN) of the policy responsible for denying access". If so, look for a `Deny` for that action in that policy [R1].
3. **Remember that the message may be incomplete.** If several policy types deny the request, "AWS includes only one of those policy types in the error message" [R1]. Review all applicable policies [R1].
4. **Decode the authorization message** if the response contains an encoded one. Decoding requires `sts:DecodeAuthorizationMessage` [R4].
5. **Check, in order**: identity-based policies, resource-based policy (and the other account if cross-account), conditions, permissions boundary, SCPs, and session policies for assumed roles [R1, R2].
6. **Test the policies with the IAM policy simulator**. For an allow or an explicit deny, it shows which policy produced the outcome. Its results "can differ from your live AWS environment" [R5].

## Diagnostic Commands

```shell
# Which identity do these credentials belong to?
aws sts get-caller-identity

# Decode the encoded authorization message returned with an UnauthorizedOperation error
aws sts decode-authorization-message --encoded-message <encoded-message>
```

Sources: `get-caller-identity` [R3]; `decode-authorization-message --encoded-message` [R4]. Policy testing is done with the IAM policy simulator [R5].

## Interpretation of Results

| Observation | Meaning | Next step |
|---|---|---|
| `get-caller-identity` returns an unexpected user or role | The tool uses other credentials [R3] | Fix the profile, environment variables or role used by the tool |
| The error names a policy type and an ARN | That policy denies the action [R1] | Look for the `Deny` statement in that policy [R1] |
| "because no service control policy allows …" | Implicit deny by an SCP [R1] | Ask the organization administrator to add an `Allow` to the SCP [R1] |
| The decoded message says "explicit deny" | A `Deny` statement matched [R4] | Find the policy with the `Deny` |
| The decoded message indicates no explicit allow | Implicit deny [R4] | Add the missing `Allow` in the right policy type |
| Works in the same account, fails cross-account | Resource-based policy missing [R1] | Grant access in the resource-based policy too [R1] |
| Fails only with an assumed role | Session policies or expired credentials [R1] | Check the session policy and credential expiry |

## Possible Solutions

- **Add the missing `Allow`** for the exact action and resource, with the least privilege needed, in the appropriate policy type [R1].
- **Remove or narrow an explicit `Deny`** when it is wrong. Remember that a deny always wins [R2].
- **Cross-account access**: allow the action in the identity-based policy **and** in the resource-based policy [R1].
- **Permissions boundary or SCP**: adjust the boundary or the SCP. SCP changes are made in AWS Organizations [R1].
- **Temporary credentials**: refresh expired credentials, and check the role and session policies [R1].
- **Console messages**: if the AWS Management Console says you are not authorized, "you must contact your administrator for assistance" [R1].

## Prevention

- Use the IAM policy simulator before deploying policy changes, then confirm in the live environment [R5].
- Keep policies small and specific to actions and resources (team recommendation, consistent with least privilege in [R1]).
- Document the SCPs and permissions boundaries applied to each account, because they are not visible in the user's own policies (team recommendation).

## Related Concepts

- **Terraform state on S3 failing with access errors**: see `md-terraform-init-errors` and `md-terraform-state-lock`.
- **Network access to EC2, which is not an IAM problem**: see `md-aws-ec2-unreachable`.

## References

All pages were consulted on 2026-11-02, in their current version.

- [R1] AWS Documentation — *Troubleshoot access denied error messages* (IAM User Guide). https://docs.aws.amazon.com/IAM/latest/UserGuide/troubleshoot_access-denied.html
- [R2] AWS Documentation — *Policy evaluation logic* (IAM User Guide). https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_evaluation-logic.html
- [R3] AWS CLI reference — *sts get-caller-identity*. https://docs.aws.amazon.com/cli/latest/reference/sts/get-caller-identity.html
- [R4] AWS CLI reference — *sts decode-authorization-message*. https://docs.aws.amazon.com/cli/latest/reference/sts/decode-authorization-message.html
- [R5] AWS Documentation — *Test IAM policies with the IAM policy simulator*. https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_testing-policies.html

## Metadata

- **Nature of this document:** written by the project team from the official AWS documentation listed above. It is **not** official AWS documentation.
- **Verification:** each statement followed by a reference was checked against the source text. Statements marked "team observation", "team inference" or "team recommendation" are our own reasoning.
- **Scope limits:** service-specific authorization models (for example S3 ACLs or KMS key policies in detail) are not covered.
