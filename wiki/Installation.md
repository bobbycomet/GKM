# Installation

Griffin Kernel Manager is distributed as a portable **AppImage**. No system-wide installation is required to try it.

## Requirements

- x86_64 (amd64) or aarch64 Linux (most testing is on x86_64)
- A graphical session with a working polkit authentication agent (most desktop environments provide one)
- One of the supported package managers: `apt-get`, `pacman`, `dnf`, or `zypper`
- FUSE (for AppImage) — almost always already present on modern distributions

Immutable systems (Silverblue, Kinoite, MicroOS, Bazzite, SteamOS immutable variants, etc.) can list kernels but cannot install or remove them, because `/usr` is read-only and the helper cannot be placed.

## Running the AppImage

1. Download the latest AppImage from the [Releases](https://github.com/bobbycomet/XKM-Multi-Kernel-Manager/releases) page.
2. Make it executable:
   ```bash
   chmod +x Griffin_Kernel_Manager-*.AppImage
   ```
3. Run it:
   ```bash
   ./Griffin_Kernel_Manager-*.AppImage
   ```

On first launch the application detects whether the privileged helper is present.

### First-run helper installation (AppImage)

Because an AppImage lives in a per-user FUSE mount that root and polkit cannot reliably execute from, GKM offers to install a small helper and polkit policy into fixed system locations:

- `/usr/lib/gkm/gkm-helper`
- `/usr/share/polkit-1/actions/com.griffin.kernel.manager.policy`
- `/usr/share/icons/hicolor/256x256/apps/gkm.png`

This is done with a single `pkexec /bin/sh -s` prompt. The script is fully visible before it runs, payloads are base64-encoded and verified with SHA-256 checksums computed at build time, and only those three files are written. After installation, every subsequent elevated action uses the fixed helper path with a GKM-specific polkit prompt.

You can install or remove the helper at any time from the command line:

```bash
./Griffin_Kernel_Manager-*.AppImage --install-helper
./Griffin_Kernel_Manager-*.AppImage --uninstall-helper
```

Or from inside the application when it detects a missing or outdated helper.

## Desktop integration

Most desktop environments will offer to integrate the AppImage (menu entry, icon, file association) when you run it. You can also use tools such as AppImageLauncher or Gear Lever if you prefer automatic updates and integration.

## Command-line options

```
gkm                      start the GUI
gkm --info               print detected distribution / hardware / kernel sources
gkm --install-helper     install the privileged helper + polkit policy
gkm --uninstall-helper   remove them again
gkm --test               run the built-in unit tests
gkm --smoke-test         headless GUI start-up check (used for build verification)
gkm --version
gkm --help
```

`--info` is useful for diagnosing detection problems without starting the full UI.

## Configuration location

User settings live in:

```
~/.config/griffin-kernel-manager/config.json
```

Logs from privileged operations are written under:

```
~/.config/griffin-kernel-manager/logs/
```

On first run after the XKM → GKM rename, settings are automatically migrated from the old `~/.config/xanmod-kernel-manager/` directory (the old directory is left untouched).

## Updating

When a newer release is published on GitHub, the application can detect it and offer a toast with a link to the release page. Because it is an AppImage, updating consists of downloading the new file and replacing the old one. The helper is versioned via a protocol number; if the installed helper is older than the AppImage expects, GKM will offer to update it.
