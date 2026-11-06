# Repositories & Third-Party Kernels

GKM can add several well-known third-party kernel repositories through the privileged helper. Banners appear on the relevant provider tabs when a repository is missing.

## Debian / Ubuntu family (APT)

### XanMod

- Subcommand: `add-repo-xanmod`
- Adds the official XanMod repository (`deb.xanmod.org`) and its signing key.
- Uses the distribution’s codename (Ubuntu or Debian).
- Older-style source files from previous GKM/XKM versions are replaced.
- Packages are filtered by the detected x86-64 level of the CPU.

### Liquorix

- Subcommand: `add-repo-liquorix`
- On Ubuntu-based systems: enables the `damentz/liquorix` PPA (installs `software-properties-common` if needed).
- On Debian-based systems: adds the liquorix.net repository and keyring.
- Liquorix is treated as a separate provider tab with its own cards.

## Arch family (pacman)

### Chaotic-AUR

- Subcommand: `add-repo-chaotic-aur`
- Imports the Chaotic-AUR signing key, installs `chaotic-keyring` and `chaotic-mirrorlist`, and appends a `[chaotic-aur]` section to `/etc/pacman.conf`.
- A backup of `pacman.conf` is created before modification.
- Provides pre-built packages for many AUR kernels (linux-cachyos*, linux-xanmod*, linux-tkg, etc.).
- Warning is shown that Chaotic-AUR is an unofficial third-party repository.

CachyOS users who already have the official CachyOS repositories do not need Chaotic-AUR for CachyOS kernels; it is mainly useful on vanilla Arch or other derivatives.

## Fedora family (dnf)

### CachyOS (COPR)

- Subcommand: `add-repo-copr-cachyos`
- Enables `bieszczaders/kernel-cachyos`.
- Installs the COPR plugin if it is missing.
- On SELinux-enforcing systems a note is printed about the required boolean:
  ```bash
  sudo setsebool -P domain_kernel_load_modules on
  ```
- Default CachyOS kernels require x86-64-v3; LTS variants run on v2.

### XanMod (community COPR)

- Subcommand: `add-repo-copr-xanmod`
- Enables `rmnscnce/kernel-xanmod` (community-maintained, not official XanMod).
- Only offered on Fedora and Nobara.

## openSUSE

No third-party repository helpers are currently implemented. Users can add Kernel:stable / Kernel:HEAD / Kernel:longterm repositories through the normal YaST or zypper workflow; GKM will pick up the packages and display the repository tag in group labels.

## Detection of existing repositories

GKM does not rely solely on the presence of a helper-added file. It also scans:

- APT sources lists and `.sources` files for known hostnames / PPAs
- `pacman-conf --repo-list` and `/etc/pacman.conf` for `[chaotic-aur]`
- `/etc/yum.repos.d/*.repo` for COPR identifiers

If packages from a third-party source are already present in the package cache, the corresponding provider tab is populated even if the repository was added by other means.

## Safety notes

- All repository-addition commands run exclusively through the privileged helper.
- The helper never accepts a free-form URL or repository definition from the GUI; only the hard-coded, reviewed recipes above are available.
- Users should understand that third-party kernels and repositories carry their own trust and update policies.
