# Security Model

## MVP safety boundary

The current application performs inventory intake and non-mutating capacity planning only. It does not create VMs, alter networks, install hypervisors, bootstrap GAMGEE, or run remote shell commands.

The node agent sends inventory over HTTPS when deployed behind a TLS endpoint. The sample uses a shared enrollment token for development; this is not sufficient for a multi-tenant production environment.

## Production requirements before privileged operations

1. TLS everywhere; reject cleartext production endpoints.
2. Unique node identity and short-lived enrollment credentials per server.
3. Mutual TLS or signed workload identity for node-to-control-plane communication.
4. Rotate and revoke credentials; never place secrets in prompts or logs.
5. Tenant isolation for sessions, node inventory, plans, approvals and audit events.
6. Role-based access and explicit human approval for provisioning, deletion, network and storage mutation.
7. Signed, versioned function packages and allow-listed function invocation.
8. No arbitrary shell, Python eval, dynamic imports or model-generated executable code.
9. Egress restrictions and network segmentation for node agents.
10. Append-only audit trails, redaction, retention limits and security monitoring.
11. Backups and tested recovery for the control-plane database.
12. Rate limits, request-size limits, CSRF protection for browser forms and secure cookie settings.

## Agent deployment cautions

- Enroll only servers the operator owns or is authorised to administer.
- Do not expose the node agent to untrusted networks.
- Do not run it as root unless a specific, documented capability requires it.
- The current agent reports host-level inventory only. It does not accept remote commands.
- Keep the enrollment token out of source control and shell history where possible.

## Approval classes

- Read-only discovery: can run under an approved enrolment policy.
- Reversible changes: require a plan and an authorised approval.
- Privileged or destructive actions: require explicit confirmation, stronger authorisation and a tested rollback/compensation path.
