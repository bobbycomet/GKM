# Hardware Awareness

GKM probes the machine once at startup and uses the results to filter, label, and block packages.

## CPU architecture and x86-64 psABI levels

On x86_64 systems the application reads `/proc/cpuinfo` flags and determines the highest psABI level the CPU supports:

| Level | Key features | Typical CPUs |
|-------|--------------|--------------|
| v1    | Baseline SSE2 | Anything 64-bit from ~2003 onward |
| v2    | SSE4.2, POPCNT, SSSE3, CX16 | Nehalem / Westmere, Bulldozer, Bobcat, … |
| v3    | AVX, AVX2, BMI1/2, FMA, … | Haswell and later, Zen 1–3, most modern desktop/laptop chips |
| v4    | AVX-512 family | Zen 4/5, Ice Lake / Sapphire Rapids Xeons, some HEDT chips |

This information is used for:

- **XanMod** (APT and COPR) — packages are labelled with their required level (`x64v1` … `x64v4`). Higher levels than the CPU supports are blocked.
- **CachyOS** (pacman and dnf) — packages coming from `cachyos-v3`, `cachyos-v4`, or `znver4` repositories are blocked when the CPU does not meet the requirement. LTS variants of CachyOS kernels generally require only v2.
- Recommendation badges in the XanMod UI (“★ recommended for your CPU”).

Zen 4 / Zen 5 detection (via `avx512_bf16`) is also recorded for znver4 repository filtering.

## GPUs

GPUs are detected from `/sys/class/drm` (vendor IDs) with a fallback to `lspci`. Supported vendors: NVIDIA, AMD, Intel.

Consequences:

- `linux-modules-nvidia-*` (and related extra/GEP packages) are hidden or blocked on machines without an NVIDIA GPU.
- Equivalent AMD / Intel module packages are filtered the same way.
- On systems that do have an NVIDIA GPU, an additional **driver-branch filter** is applied (see below).

## NVIDIA driver major version

When an NVIDIA proprietary driver is present, GKM determines its major version by checking, in order:

1. `/proc/driver/nvidia/version` (most reliable when the module is loaded)
2. `nvidia-smi --query-gpu=driver_version`
3. Installed `nvidia-driver-*` / `nvidia-kernel-common-*` packages via `dpkg-query`

Only `linux-modules-nvidia-N-*` packages that match the running major (e.g. 580) are offered. Modules for other majors (595, 610, …) are blocked with a clear reason. This prevents the well-known APT conflicts that occur when the wrong branch’s modules are installed.

If no NVIDIA driver can be detected, all NVIDIA modules are shown (legacy behaviour).

## Cloud VMs

A best-effort check of DMI strings identifies AWS, Azure, GCP, and Oracle Cloud. The information is shown in the system info dialog and can influence default flavor selection on Ubuntu (e.g. preferring the AWS kernel on an EC2 instance).

## Immutable systems

Detection methods:

- Presence of `/run/ostree-booted`
- `VARIANT_ID` matching known immutable variants (silverblue, kinoite, sericea, onyx, coreos, iot, atomic, micro, aeon, kalpa, holo, bazzite, …)
- Read-only root filesystem reported by `/proc/self/mountinfo`

On immutable systems the helper state is reported as `unsupported` and all mutating operations are disabled.

## What is *not* filtered

- Ordinary mainline / distro kernels that do not embed a microarchitecture or GPU requirement.
- Headers, meta packages, and cloud-tools packages that are architecture-agnostic.
- Locally installed packages that are already on the system (they remain visible so they can be held or removed).

The system information dialog (toolbar “ⓘ System”) shows the exact values GKM detected for your machine.
