# Security Policy

## Supported Versions

| Version | Supported |
| --- | --- |
| 1.x | Yes |
| < 1.0 | No |

## Reporting a Vulnerability

Please do not report security vulnerabilities in public GitHub issues.

Report suspected vulnerabilities by opening a private security advisory on
GitHub, or by contacting the maintainers through the security contact configured
for the repository.

Please include:

- Affected version or commit.
- A clear description of the vulnerability.
- Steps to reproduce or proof of concept, when safe to share.
- Potential impact.
- Any known mitigations.

## Response Expectations

Maintainers will acknowledge valid reports within 7 days, provide a remediation
plan when possible, and coordinate disclosure timing with the reporter.

## Security Scope

ChokePoint parses local infrastructure files and may invoke Graphviz without a
shell for visualization rendering. Reports should focus on vulnerabilities in
parsing, graph/report generation, CLI behavior, packaging, or generated output.
