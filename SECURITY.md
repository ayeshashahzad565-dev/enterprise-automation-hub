# Security Policy

## Supported Versions

Enterprise Automation Hub is currently developed and maintained as a single, continuously updated main line. Security fixes are applied to the latest released version.

| Version | Supported |
|---|---|
| Latest release (`main`) | :white_check_mark: |
| Prior releases | :x: |

Once a formal release/versioning process is established, this table will be updated to reflect which specific version lines receive security patches.

## Reporting a Vulnerability

If you discover a security vulnerability in Enterprise Automation Hub, please report it privately rather than opening a public GitHub issue or pull request.

- **Preferred method:** Use GitHub's private vulnerability reporting feature on this repository (Security tab → "Report a vulnerability"), if enabled.
- **Alternative method:** Contact the maintainers directly through the contact method listed in this repository's profile or organization page.

Please do not disclose the vulnerability publicly, including in issues, discussions, or pull requests, until it has been investigated and, where applicable, a fix has been released.

When reporting, please include as much of the following as possible:

- A description of the vulnerability and its potential impact
- Steps to reproduce, or a proof of concept
- The affected component or endpoint (e.g., a specific API route, service, or database policy)
- Any relevant logs or error output (with sensitive data redacted)

## Security Expectations

Enterprise Automation Hub's security model is documented in full in the [Architecture Design Document](docs/architecture.md#9-security-architecture), [Database Schema Design Document](docs/database_schema.md#9-row-level-security), [API Design Document](docs/api_design.md#24-security-considerations), and [Deployment Guide](docs/deployment.md#19-security-hardening). Reporters and contributors should be aware of the following baseline expectations:

- **Authentication** is delegated entirely to Supabase Auth; this project does not implement its own credential storage.
- **Authorization** is enforced both in application code and independently via PostgreSQL Row-Level Security. A report demonstrating that either layer alone can be bypassed to access unauthorized data is a valid and significant finding.
- **Audit logs are immutable.** A report demonstrating that any code path can update or delete an audit log entry is treated as a critical finding.
- **Secrets** (Supabase service-role key, SMTP credentials) must never be reachable from client-facing code or logged in plaintext. A report demonstrating either is treated as a critical finding.
- **File uploads** are validated by content-type allow-list, size limit, MIME sniffing, and checksum. A report demonstrating a bypass of any of these controls is a valid finding.

Reports of theoretical concerns without a demonstrated, practical impact are still welcome, but will be triaged accordingly.

## Disclosure Policy

This project follows a coordinated disclosure process:

1. **Acknowledgment.** We aim to acknowledge receipt of a vulnerability report within a reasonable timeframe.
2. **Investigation.** The report is reviewed and, where necessary, reproduced against the architecture documented in `/docs`.
3. **Remediation.** A fix is developed and tested per the [Testing Strategy Document](docs/testing_strategy.md), including a regression test reproducing the original vulnerability.
4. **Release.** The fix is released, and the reporter is credited (if desired) once the fix is available.
5. **Public disclosure.** Details of the vulnerability are only published after a fix has been released, and only with the reporter's coordination.

We ask that reporters give us a reasonable opportunity to investigate and address a reported vulnerability before any public disclosure.