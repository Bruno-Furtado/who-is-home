# Security Policy

This is a personal open-source project. There is no formal SLA, but security reports are welcome and taken seriously.

## Reporting a vulnerability

Please report vulnerabilities privately by opening a
[private security advisory](https://github.com/Bruno-Furtado/who-is-home/security/advisories/new),
or by email to **brunotfurtado@gmail.com**. Include steps to reproduce and the affected files when possible.
Please don't open a public issue for security matters.

## Scope

who-is-home runs a small HTTP server meant for a **trusted home network**. It has no login, and it shows which sites each
device looks up, so anyone who can reach the dashboard can read that history. Exposing its port to the internet is out of scope.
Things that are in scope include:

- reading data or triggering actions from another website (DNS rebinding, CSRF);
- script injection in the dashboard through domain names, mDNS/NetBIOS host names or device names;
- reading files outside `static/`, including `dados/config.json`;
- leaking the AdGuard Home credentials through the API or the logs;
- command injection through the scan (`ping`, `arp`, `ifconfig`, `ip`, `launchctl`, `systemctl`).

The repository stores no credentials. The AdGuard login and the ntfy topic live in `dados/config.json` (mode 600), which is git-ignored.
