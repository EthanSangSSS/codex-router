# Security Policy

## Supported line

Security fixes target the current `main` branch and the recommended Native PRIMARY + Luna mode described in `README.md`.

Historical `global-*`, Hook/K1, and staged pipeline surfaces remain in the repository for compatibility and regression coverage, but they are not the recommended deployment path.

## Reporting a vulnerability

Please do **not** disclose a suspected vulnerability, exploit details, credentials, private repository content, or sensitive local paths in a public issue.

Preferred reporting path:

1. Use GitHub private vulnerability reporting / Security Advisories for this repository when available.
2. If private reporting is unavailable, open a minimal public issue asking the maintainer for a private contact channel. Do not include vulnerability details in that issue.

Include only the information needed to reproduce and assess the issue:

- affected commit or version;
- affected command or Native lifecycle stage;
- expected vs. observed behavior;
- minimal reproduction steps;
- security impact and required preconditions;
- whether the issue affects the recommended Native mode or only a historical compatibility surface.

Never send real credentials or production secrets as reproduction material. Use synthetic values and a disposable Codex home/workspace whenever possible.

## Security model and boundaries

Codex Router does not replace Codex's native sandbox or approval system. Native mode installs orchestration instructions and a bounded `luna_worker` profile; effective filesystem, process, network, and external-action permissions remain controlled by the Codex runtime and the user's configuration.

The recommended Native mode intentionally installs no Router routing Hooks and does not rely on the historical K1 / generation-lease control plane.

The installer is designed to preserve unrelated user configuration, keep reversible ownership evidence, and fail closed when managed content or legacy Router ownership is ambiguous.

## Disclosure handling

Please allow time for triage and remediation before public disclosure. Once a fix is available, the repository may publish a security advisory describing affected versions, impact, and upgrade guidance.
