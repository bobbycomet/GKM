# Supported Distributions

GKM detects the running distribution from `/etc/os-release` and maps it to a package-manager family. Derivatives are resolved to their family and nearest root distro so the correct backend and repository logic are used.

## Supported families

| Family   | Package manager | Examples |
|----------|-----------------|----------|
| Debian   | APT (`apt-get`) | Debian, Ubuntu, Linux Mint, Pop!_OS, elementary OS, Zorin, KDE neon, Kali, Raspberry Pi OS, MX Linux, Deepin, Tuxedo, PureOS, Kubuntu, Xubuntu, Lubuntu, SteamOS (Debian-based) |
| Arch     | pacman          | Arch Linux, CachyOS, Manjaro, EndeavourOS, Garuda, Artix, ArcoLinux, Archcraft, RebornOS, BigLinux, BlendOS, SteamOS (Arch-based), SnigdhaOS |
| Fedora   | dnf             | Fedora, Nobara, RHEL, CentOS Stream, Rocky Linux, AlmaLinux, Oracle Linux, Amazon Linux, Scientific Linux, EuroLinux |
| SUSE     | zypper          | openSUSE Tumbleweed, openSUSE Leap, openSUSE Slowroll, openSUSE MicroOS, SLES, SLED |

### Notes per family

**Debian / Ubuntu**
- Full support for official kernels (generic, low-latency, OEM, HWE, cloud images, Raspberry Pi, etc.).
- XanMod and Liquorix repositories can be added from inside the application.
- Meta/tracking packages (`linux-generic`, `linux-lowlatency`, `linux-oem-24.04`, …) are shown and managed.
- NVIDIA `linux-modules-nvidia-*` packages are filtered by the currently installed driver major version to avoid the classic “nvidia-kernel-common-N is not installable” conflicts.

**Arch family**
- Kernels are discovered generically: any package that has a matching `-headers` package is treated as a kernel. This picks up official Arch kernels, CachyOS variants, XanMod, Clear, TKG, Manjaro’s numbered series, and locally built AUR kernels without a hard-coded list.
- Rolling-release model: there are no “old kernels” to auto-remove; the auto-remove button is hidden.
- Chaotic-AUR can be added for pre-built third-party kernels.
- CachyOS repositories that are built for higher x86-64 levels (v3, v4, znver4) are detected and packages from them are blocked when the CPU does not support the required level.

**Fedora / RHEL family**
- Multi-version install-only kernels are fully supported. Each row is a specific build (`name=EVR`).
- CachyOS (bieszczaders COPR) and a community XanMod COPR can be enabled from the UI.
- SELinux note is shown when enabling CachyOS/XanMod COPRs on enforcing systems.
- RHEL clones are labelled “RHEL” in the UI; Fedora and Nobara keep their own names.

**openSUSE / SUSE**
- Multi-version kernels (default, preempt, rt, etc.) are supported.
- Only the newest available version of each package is offered for installation; already-installed older builds remain visible so they can be removed.
- Kernel:stable / Kernel:HEAD / Kernel:longterm repository tags are shown in group labels when present.

## Immutable systems

Systems that use ostree / rpm-ostree (Silverblue, Kinoite, Sericea, Onyx, CoreOS, IoT, Atomic, MicroOS, Aeon, Kalpa, Holo, Bazzite, etc.) or that have a read-only root filesystem are detected. Kernels can be listed, but installation, removal, holding, and helper installation are disabled because `/usr` cannot be modified.

## Unsupported or limited situations

- Distributions without one of the four package managers above.
- Systems without `pkexec` / polkit (the helper cannot be used).
- Non-x86_64 architectures for XanMod, Liquorix, and most CachyOS packages (those providers are simply not shown).
- Custom or highly modified package managers that do not speak the normal CLI of apt/pacman/dnf/zypper.

Use `gkm --info` to see exactly what the application detected on your machine.
