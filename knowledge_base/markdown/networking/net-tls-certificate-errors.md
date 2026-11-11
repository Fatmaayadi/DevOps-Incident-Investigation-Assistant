---
doc_id: md-net-tls-certificate-errors
title: TLS Handshake and Certificate Verification Errors
domain: networking
technology: [tls, openssl, curl, docker-registry, aws-elb]
category: security-tls
document_type: troubleshooting_guide
difficulty: intermediate
keywords:
  - TLS handshake failure
  - SSL handshake error
  - certificate verify failed
  - certificate expired
  - self-signed certificate
  - unknown certificate authority
  - x509 certificate signed by unknown authority
  - hostname mismatch
  - subjectAltName
  - SNI
  - incomplete certificate chain
  - CA bundle
  - openssl s_client
  - curl --cacert
error_messages:
  - "SSL connect error"
  - "NET::ERR_CERT_COMMON_NAME_INVALID"
  - "CA certificates should use the extension .crt"
  - "unable to get local issuer certificate"
  - "certificate has expired"
  - "x509: certificate signed by unknown authority"
source_type: team_written_from_official_docs
language: en
references:
  - id: R1
    title: "SSL CA Certificates — TLS Certificate Verification"
    publisher: curl project
    url: https://curl.se/docs/sslcerts.html
    accessed: 2026-11-02
  - id: R2
    title: "libcurl error codes (CURLE_SSL_CONNECT_ERROR, CURLE_PEER_FAILED_VERIFICATION)"
    publisher: curl project
    url: https://curl.se/libcurl/c/libcurl-errors.html
    accessed: 2026-11-02
  - id: R3
    title: "openssl-s_client(1)"
    publisher: OpenSSL documentation
    url: https://docs.openssl.org/master/man1/openssl-s_client/
    accessed: 2026-11-02
  - id: R4
    title: "openssl-x509(1)"
    publisher: OpenSSL documentation
    url: https://docs.openssl.org/master/man1/openssl-x509/
    accessed: 2026-11-02
  - id: R5
    title: "Verify repository client with certificates"
    publisher: Docker Docs
    url: https://docs.docker.com/engine/security/certificates/
    accessed: 2026-11-02
  - id: R6
    title: "Troubleshoot your Application Load Balancers (NET::ERR_CERT_COMMON_NAME_INVALID; HTTP 502/504 SSL handshake with targets)"
    publisher: AWS Documentation
    url: https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-troubleshooting.html
    accessed: 2026-11-02
  - id: R7
    title: "X509_STORE_CTX_get_error(3) (ERROR CODES)"
    publisher: OpenSSL documentation
    url: https://docs.openssl.org/master/man3/X509_STORE_CTX_get_error/
    accessed: 2026-11-11
  - id: R8
    title: "Troubleshooting GitLab Runner (x509: certificate signed by unknown authority)"
    publisher: GitLab Docs
    url: https://docs.gitlab.com/runner/faq/
    accessed: 2026-11-11
last_reviewed: 2026-11-02
review_status: reviewed by team against sources
---

# TLS Handshake and Certificate Verification Errors

## Overview

When a client opens an HTTPS (or other TLS) connection, it verifies the server certificate. curl, for example, does this "by verifying the signature and making sure the certificate was crafted for the server name provided in the URL" [R1]. Verification fails when [R1]:

- the server uses a **self-signed** certificate;
- the client has **no CA store** installed;
- the certificate is signed by a **CA that is not in the client's store**;
- the server is an **impostor**.

Two other frequent causes are an **expired certificate** and a **name that does not match** the certificate. In practice, the diagnosis consists of reading the certificate actually presented by the server and comparing it with the name used by the client and with the trust store of the client (team summary of [R1, R3, R4]).

## Symptoms

- curl fails with error 35, `CURLE_SSL_CONNECT_ERROR`: "A problem occurred somewhere in the SSL/TLS handshake" [R2].
- curl fails with error 60, `CURLE_PEER_FAILED_VERIFICATION`: "The remote server's SSL certificate or SSH fingerprint was deemed not OK" [R2].
- Browsers report a name error, for example `NET::ERR_CERT_COMMON_NAME_INVALID` behind an AWS load balancer [R6].
- Clients built on OpenSSL name the verification error. The OpenSSL error list includes [R7]:
  - `unable to get local issuer certificate` (`X509_V_ERR_UNABLE_TO_GET_ISSUER_CERT_LOCALLY`);
  - `certificate has expired` (`X509_V_ERR_CERT_HAS_EXPIRED`);
  - `self-signed certificate` (`X509_V_ERR_DEPTH_ZERO_SELF_SIGNED_CERT`) and `self-signed certificate in certificate chain` (`X509_V_ERR_SELF_SIGNED_CERT_IN_CHAIN`);
  - `hostname mismatch` (`X509_V_ERR_HOSTNAME_MISMATCH`).
- GitLab Runner documents the error `x509: certificate signed by unknown authority`, and points to its self-signed certificates configuration [R8] (see `md-gitlab-ci-job-failures`).
- `docker pull` or `docker login` to a private registry fails with a certificate error (team observation; the exact text depends on the client).
- A load balancer returns 502 or 504 because of an SSL handshake error or timeout **with the backend** [R6] (see `md-net-http-502-503-504`).

## Possible Causes

| Cause | Explanation |
|---|---|
| **Private or self-signed CA not trusted by the client** | The CA that signed the server certificate is not in the client's store [R1] |
| **Incomplete chain sent by the server** | The client cannot link the server certificate to a trusted root (team inference; check with `-showcerts`, which shows only what the server sent [R3]) |
| **Hostname mismatch** | The name in the URL is not covered by the certificate. On AWS, "the domain name used in the HTTPS request does not match the alternate name specified" in the certificate, or the default `*.amazonaws.com` load balancer name is used [R6] |
| **Expired (or not yet valid) certificate** | Check the `notBefore`/`notAfter` dates [R4] |
| **Missing SNI** | The server picks its certificate based on SNI; testing by IP without `-servername` may return another certificate (team inference based on [R3]) |
| **Docker registry CA misconfigured** | The CA must be placed in `/etc/docker/certs.d/<registry-host>[:port]/` with a `.crt` extension; `.cert` files are treated as client certificates [R5] |

## Investigation Steps

1. **Reproduce with a verbose client** and note the exact error: handshake error vs verification error [R2].
2. **Look at the certificate actually presented** with `openssl s_client`. Set `-servername` to the name used by real clients [R3].
3. **Read the certificate fields**: subject, issuer, validity dates, and the `subjectAltName` extension [R4].
4. **Compare the name** used by the client with the names in the certificate [R1, R6].
5. **Check the chain**: `-showcerts` displays the list "as sent by the server", which "is not a verified chain" [R3]. Look for missing intermediate certificates.
6. **Check the client's trust store**: which CA bundle does it use, and does it contain the issuing CA? curl's verbose output usually shows the path of the CA store [R1].
7. **For Docker registries**, check the `certs.d` directory for that registry's hostname and port [R5].

## Diagnostic Commands

```shell
# Handshake and verification as seen by curl (verbose)
curl -v https://api.example.com/

# Certificate chain presented by the server, with the correct SNI
openssl s_client -connect api.example.com:443 -servername api.example.com -showcerts

# Fail the handshake on verification errors (instead of continuing)
openssl s_client -connect api.example.com:443 -servername api.example.com -verify_return_error

# Read a certificate file: subject, issuer, dates, SAN
openssl x509 -in server.crt -noout -subject -issuer -dates -ext subjectAltName

# Does the certificate expire within the next 30 days? (exit code non-zero if yes)
openssl x509 -in server.crt -noout -checkend 2592000

# Test with a specific CA bundle (private CA)
curl --cacert my-ca.pem https://api.example.com/
```

Sources: `-connect`, `-servername`, `-showcerts`, `-verify_return_error` [R3]; `-noout`, `-subject`, `-issuer`, `-dates`, `-ext`, `-checkend` [R4]; `--cacert` and `curl -v` showing the CA store path [R1].

## Interpretation of Results

| Observation | Meaning | Next step |
|---|---|---|
| `unable to get local issuer certificate` [R7] | The client cannot find the issuer of the certificate in its trust store: private CA not trusted, or intermediate certificate not sent (team inference based on [R1, R3]) | Check the chain with `-showcerts`, then the client's CA store |
| `certificate has expired` [R7] | The `notAfter` date is in the past [R4] | Renew and deploy the certificate |
| `self-signed certificate` or `x509: certificate signed by unknown authority` [R7, R8] | The issuing CA is not trusted by the client [R1] | Add the CA to the client's trust store [R1, R8] |
| curl error 60, and the issuer is your company's CA | The client does not trust that CA [R1, R2] | Add the CA to the client trust store, or use `--cacert` [R1] |
| `-showcerts` shows only the leaf certificate | The server may not send its intermediate certificates (team inference) | Configure the full chain on the server |
| `notAfter` is in the past | Certificate expired [R4] | Renew and deploy the certificate |
| The URL name is absent from `subjectAltName` | Hostname mismatch [R1, R6] | Use a covered name, or reissue the certificate |
| Different certificate with and without `-servername` | SNI-based selection on the server (team inference) | Make sure clients send the right name |
| Docker registry error only on one host | That host lacks the CA in `certs.d` [R5] | Install `ca.crt` in the registry's directory |
| curl error 35 without a verification message | Handshake problem other than trust (protocol, configuration) [R2] | Read the full error buffer as curl advises [R2] |

## Possible Solutions

- **Trust the right CA**: add the private CA to the system or application trust store, or point the client to it (`--cacert`, `CURL_CA_BUNDLE`) [R1].
- **Serve the complete chain** (server certificate + intermediates) from the server or load balancer (team recommendation, consistent with [R3]).
- **Renew expired certificates**, and automate the check with `openssl x509 -checkend` [R4].
- **Use a name covered by the certificate**. On AWS, use a custom domain covered by the certificate rather than the default load balancer DNS name [R6].
- **Docker registry**: put the registry's root CA as `ca.crt` under `/etc/docker/certs.d/<hostname>[:port]/` (on native Linux). Do not add a port to the directory name if the registry is used without a port [R5].
- **Do not disable verification in production.** curl's documentation says to avoid `-k/--insecure` and to "never skip verification in production" [R1].

## Prevention

- Monitor certificate expiry, for example with scheduled `openssl x509 -checkend` checks [R4], and renew well in advance.
- Keep the list of internal CAs and distribute them to all clients, including container images and CI runners (team recommendation).
- Test new certificates with `openssl s_client -servername …` before switching traffic [R3].

## Related Concepts

- **TCP connection problems before TLS**: see `md-net-connection-refused-timeout`.
- **Proxy errors caused by TLS to the backend**: see `md-net-http-502-503-504`.
- **Image pulls from private registries in Kubernetes**: see `md-k8s-imagepullbackoff`.

## References

All pages were consulted on 2026-11-02, in their current version. The Docker page was checked against its source in the `docker/docs` repository.

- [R1] curl project — *SSL CA Certificates*. https://curl.se/docs/sslcerts.html
- [R2] curl project — *libcurl error codes*. https://curl.se/libcurl/c/libcurl-errors.html
- [R3] OpenSSL documentation — *openssl-s_client(1)*. https://docs.openssl.org/master/man1/openssl-s_client/
- [R4] OpenSSL documentation — *openssl-x509(1)*. https://docs.openssl.org/master/man1/openssl-x509/
- [R5] Docker Docs — *Verify repository client with certificates*. https://docs.docker.com/engine/security/certificates/
- [R6] AWS Documentation — *Troubleshoot your Application Load Balancers*. https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-troubleshooting.html
- [R7] OpenSSL documentation — *X509_STORE_CTX_get_error(3)*, section ERROR CODES (consulted on 2026-11-11, checked against `doc/man3/X509_STORE_CTX_get_error.pod` in the `openssl/openssl` repository). https://docs.openssl.org/master/man3/X509_STORE_CTX_get_error/
- [R8] GitLab Docs — *Troubleshooting GitLab Runner* (consulted on 2026-11-11). https://docs.gitlab.com/runner/faq/

## Metadata

- **Nature of this document:** written by the project team from the official sources listed above. It is **not** official documentation of curl, OpenSSL, Docker or AWS.
- **Verification:** each statement followed by a reference was checked against the source text. Statements marked "team observation", "team inference", "team summary" or "team recommendation" are our own reasoning.
- **Scope limits:** error messages differ between TLS libraries and programming languages (OpenSSL, Go, Java…). This guide quotes only the messages found in the cited sources.
