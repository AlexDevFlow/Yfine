# Security Policy

## Supported versions

Yfine is actively developed. Security fixes target the latest `main` branch and the most recent tagged release.

## Reporting a vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Instead, report privately via GitHub's [Private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability) on this repository.

Please include:

- A description of the vulnerability and its impact
- Steps to reproduce
- Affected version(s) and platform(s)
- Any suggested mitigation, if known

You can expect an initial response within a few days. Coordinated disclosure is appreciated — please give me reasonable time to ship a fix before publishing details.

## Scope

In scope:

- The Yfine application (Python backend, templates, static assets)
- The plugin sandboxing and scanner
- Authentication, session handling, and database encryption
- LAN access mode and auto-generated TLS certificates

Out of scope:

- Vulnerabilities in third-party dependencies — please report upstream
- Social engineering or physical attacks
- Attacks requiring prior local filesystem access to the user's machine (Yfine is local-first by design)

## Security model, in brief

- Yfine is designed to run on the user's own machine. Data stays local.
- When a password is set, the SQLite DB is encrypted at rest with AES-256-GCM (key derived via PBKDF2-HMAC-SHA256). Legacy Fernet archives from older versions are still readable and re-encrypted as AES-256-GCM on next shutdown.
- Plugin management endpoints are restricted to localhost.
- Plugins are statically scanned before installation, but **users should always review plugin source before installing from untrusted authors**.
