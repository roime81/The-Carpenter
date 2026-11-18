# Changelog

All notable changes to The Carpenter are documented here.

## 0.5.0 — 2026-11-18

### Living Infrastructure Canvas
- Replaced the narrow prompt-only home screen with a transparent, visual-first infrastructure workspace.
- Added a graph canvas that begins at the Carpenter launcher and connects intent, discovery, blueprint, playbook, native functions, IaC, approval, provisioning and reconciliation stages.
- Added interactive SVG nodes with keyboard support, dependency edges, status colors, active pulses and node selection.
- Added a contextual node inspector with type, role and dependency information.
- Added an execution journal beside the graph and a persistent prompt dock.
- Added canvas label toggle, fit control, responsive layout and dark translucent visual treatment.
- Derived the initial status visualization from saved conversation responses; it does not yet claim live event streaming from workers.
- Documented that Blueprint and Playbook are visual workflow concepts, not persisted workbook/playbook artifacts.

### Known UI follow-ups
- Add authenticated event-stream or polling integration for live worker/job status updates.
- Persist a full per-deployment graph model with node/edge IDs and timestamps.
- Add zoom/pan, graph minimap, artifact previews and per-node logs.

undefined