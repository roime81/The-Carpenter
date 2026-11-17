# Infrastructure Discovery Engine

## Discovery principles

- Inventory only infrastructure the user has enrolled or explicitly authorised.
- A ping or open port does not prove administrative access or permission.
- Use an authenticated node agent or a provider API connector.
- Do not sweep arbitrary networks.
- Separate host facts, capability detection and placement eligibility.

## What the node agent reports

Heartbeat includes:
- Stable node ID and hostname.
- Operating system and architecture.
- Logical CPU count.
- Total/available memory.
- Root disk total/free space.
- IPv4 addresses.
- Failure-domain label.
- Function capabilities and versions.
- Hypervisor presence indicators (KVM device, libvirt socket/CLI, Proxmox marker).
- Last-seen timestamp maintained by the control plane.

A node is live only while its heartbeat is within `CARPENTER_AGENT_STALE_SECONDS` (default 90 seconds). Offline nodes are retained in inventory but excluded from live capacity.

## Distributed discovery functions

- `discovery.host_inventory@1.0.0`: local host facts.
- `discovery.hypervisor_probe@1.0.0`: KVM/libvirt, Proxmox and runtime presence checks.
- `discovery.storage_network@1.0.0`: mount points, filesystems, interfaces, link state, network counters.

The admin endpoint `POST /api/v1/discovery/scan` enqueues all three functions for every online node and pins each job to its target worker. Results are available through `GET /api/v1/jobs`.

## Explicit TCP discovery

`network.tcp_probe@1.0.0` accepts:
- A literal IP address (no hostname or CIDR range).
- A private, loopback or link-local target.
- 1–16 ports from a fixed allow-list.

It is a reachability indicator only. It does not authenticate or modify the target.

## Current assessment gaps

The current worker uses local read-only presence checks. It does not yet call hypervisor management APIs to enumerate all VMs or retrieve virtual CPU overcommit, pool capacity, storage IOPS/latency, network throughput, NUMA, GPU, power supply, rack power or shared storage failure domains. Those need provider-specific discovery adapters and conformance tests.
