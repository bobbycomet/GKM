# Griffin Kernel Manager Wiki

Welcome to the documentation for **Griffin Kernel Manager (GKM)**.

GKM is a desktop application for discovering, installing, removing, holding, and cleaning up Linux kernels across multiple distribution families. It is distributed primarily as an **AppImage**.

## Quick links

| Page | Description |
|------|-------------|
| [Installation](Installation) | Running the AppImage, first-run helper installation, desktop integration |
| [Supported Distributions](Supported-Distributions) | What works, what is limited, immutable systems |
| [Features](Features) | Full feature list and how the UI is organized |
| [Hardware Awareness](Hardware-Awareness) | CPU levels, GPU filtering, NVIDIA driver branch, cloud VMs |
| [Security Model](Security) | Privileged helper, argument validation, AppImage install process |
| [Repositories & Third-Party Kernels](Repositories) | XanMod, Liquorix, Chaotic-AUR, COPR, how they are added |
| [FAQ](FAQ) | Common questions and troubleshooting |
| [Architecture](Architecture) | Backends, data model, UI structure, privilege design |
| [Contributing](Contributing) | Building, testing, coding guidelines |
| [Changelog & Versioning](Versioning) | Protocol numbers, compatibility notes |

## What GKM is *not*

- A general package manager
- A bootloader configuration tool (it only runs the distro’s normal refresh commands as a safety net)
- A kernel compiler / source builder
- A tool that runs as root. Only a small, fixed-purpose helper ever gains elevated privileges.

## Design principles

1. **Never offer what cannot work** — hardware filtering is applied before packages are shown as selectable.
2. **Least privilege** — the GUI process never runs as root; all elevated work goes through `gkm-helper`.
3. **Validate everything twice** — the GUI sanitizes package specs; the helper re-validates every argument with strict regexes before touching a package manager.
4. **Distro-native** — each backend uses the real package manager (apt-get, pacman, dnf, zypper) instead of reinventing dependency resolution.
5. **AppImage friendly** — helper and polkit policy can be installed on first run when the AppImage cannot place files in `/usr`.

Start with [Installation](Installation) if you just want to run it, or [Features](Features) for a complete overview.
