# Features

## Core operations

- **List kernels** from official repositories and any third-party sources that are already configured.
- **Install** selected packages (or whole kernel groups) with a single click.
- **Remove / Purge** selected packages (purge is available on APT and pacman).
- **Hold / Unhold** packages so they are not upgraded by the normal package manager (uses `apt-mark`, `IgnorePkg`, `dnf versionlock`, or `zypper addlock` as appropriate).
- **Install + Hold** in one action.
- **Auto-remove old kernels** — keeps the running kernel and the two newest builds of each flavor/series; never touches meta packages or held packages. Only available on multi-version families (Debian, Fedora, openSUSE).
- **Rebuild DKMS** modules for newly installed kernels (or for every installed kernel).
- **Refresh package sources** through the privileged helper.
- **Bootloader safety-net refresh** after install/remove (runs the distro’s normal `update-grub`, `grub-mkconfig`, or `update-bootloader` when appropriate; otherwise reports that the kernel packages already handle it).

## UI organisation

Kernels are organised into **provider tabs** (e.g. Ubuntu / Debian, XanMod, Liquorix, Arch, CachyOS, …). Each tab can be filtered by flavor and searched.

### Nested layout (mainline / official kernels)

Version cards → flavor sub-sections (Generic, Low Latency, OEM, AWS, …) → individual packages (Image, Headers, Modules, Modules NVIDIA, Meta, …).

- Clicking a version or flavor header selects exactly the packages that are still missing (or, if everything is already installed, selects them for removal).
- Package rows and flavor sections are built **lazily** on first expand so that large mainline archives do not create tens of thousands of widgets up front.

### Flat / grouped layout (XanMod, Liquorix, CachyOS, Arch rolling kernels)

Each card represents one concrete, installable kernel (version + flavor / base). The header selects the whole set of packages belonging to that kernel.

## Hardware-aware presentation

- Packages that require a higher x86-64 level than the CPU supports are shown but **blocked** (cannot be selected for install).
- NVIDIA modules that belong to a different driver major than the one currently installed are blocked.
- Modules for GPUs that are not present on the machine are blocked.
- Recommended XanMod / CachyOS levels for the detected CPU are highlighted.

See [Hardware Awareness](Hardware-Awareness) for details.

## Repository management

From inside the application you can add:

- Official XanMod APT repository
- Liquorix (PPA on Ubuntu derivatives, liquorix.net on Debian)
- Chaotic-AUR (Arch family)
- CachyOS COPR and a community XanMod COPR (Fedora family)

Banners appear on the relevant tabs when a repository is missing. Adding a repository always goes through the privileged helper.

## Other UI features

- Dark / light mode (persisted)
- Search across all kernels
- Flavor filter combo box per tab
- System information dialog (detected distro, hardware, helper state, running kernel)
- Live log panel for privileged operations
- Toast notifications for non-blocking messages
- Optional automatic check for new AppImage releases on GitHub
- Configurable auto-remove-after-install checkbox
- Window size and preferences persisted across runs

## Safety behaviours

- The currently running kernel cannot be removed.
- Blocked packages (wrong hardware) are never passed to the helper even if somehow selected.
- Conflicting signed / unsigned image packages of the same version are de-duplicated on install.
- Package specs are validated with a strict regex both in the GUI and again inside the helper.
- On immutable systems all mutating actions are disabled with a clear explanation.
