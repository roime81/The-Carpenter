# Changelog

All notable changes to The Carpenter are documented here.

## 0.6.0 — 2026-11-18

### Live Infrastructure Network
- Replaced the conceptual linear flowchart presentation with an organic, light-background node mesh inspired by `docs/assets/8805.jpg`, with low-emphasis proximity strands and stronger semantic links.
- Added a session-scoped graph projection built from persisted conversations, deployment plans, IaC resources, FaaS jobs, enrolled workers and operation events.
- Added authenticated Server-Sent Event snapshots backed by the durable SQLite records and refreshed at a 1.5-second cadence.
- Instrumented worker claims, completions and failures with explicit event records, including function/version, worker, attempt, session/deployment scope and timestamps.
- Added one stable graph node per job and participating worker; job/worker inspectors display real status, timestamps, retry attempts and sanitized event history.
- Added resource node status derived from linked provider jobs instead of treating plan-only resources as deployed.
- Generated Infrastructure Workbook and Execution Playbook previews from the saved plan, persisted them in the deployment record and exposed authenticated preview endpoints.
- Added regression coverage for graph projection, session isolation, per-worker history and live playbook state.
- Documented that SSE is a polling-backed projection, not a message-broker push bus; artifact previews are persisted in the deployment plan record rather than as separate filesystem files.

## 0.5.1 — 2026-11-18

### White theme refinement
- Replaced the dark translucent canvas with a clean porcelain-white workspace.
- Updated the graph surface, node labels, dependency edges, legend, inspector, journal and prompt dock for light backgrounds.
- Retained distinct status semantics using restrained teal, blue, amber and red accents.
- Applied the same light theme to the sign-in surface for a consistent launch-to-workspace experience.

## 0.5.0 — 2026-11-18

### Living Infrastructure Canvas
- Replaced the narrow prompt-only home screen with a transparent, visual-first infrastructure workspace.
- Added a graph canvas that begins at the Carpenter launcher and connects intent, discovery, blueprint, playbook, native functions, IaC, approval, provisioning and reconciliation stages.
- Added interactive SVG nodes with keyboard support, dependency edges, status colors, active pulses and node selection.
- Added a contextual node inspector with type, role and dependency information.
- Added an execution journal beside the graph and a persistent prompt dock.
- Added canvas label toggle, fit control, responsive layout and translucent visual treatment (subsequently refined to the white theme in 0.5.1).
- Derived the initial status visualization from saved conversation responses; it does not yet claim live event streaming from workers.
- Documented that Blueprint and Playbook are visual workflow concepts, not persisted workbook/playbook artifacts.

### Known UI follow-ups
- Add authenticated event-stream or polling integration for live worker/job status updates.
- Persist a full per-deployment graph model with node/edge IDs and timestamps.
- Add zoom/pan, graph minimap, artifact previews and per-node logs.

undefined