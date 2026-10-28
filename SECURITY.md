# Security Policy

EpicWing is in beta. Please report vulnerabilities privately and do not open a
public issue.

**Contact:** support@epicwing.de

Include what you found, how to reproduce it and the version or commit. We aim to
answer within a few days. Please give us a reasonable time to fix the problem
before you publish details.

## Scope notes

- The agent has access to the Docker socket. Run nodes on dedicated machines.
- Egg install scripts run as code in an installer container. Only administrators
  can create or change eggs. Only import eggs you trust.
