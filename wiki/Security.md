# Security Model

Griffin Kernel Manager is designed so that the GUI process **never runs as root**. All privileged work is performed by a small, purpose-built helper that is invoked through polkit.

## The privileged helper

Location after installation:

```
/usr/lib/gkm/gkm-helper
```

Polkit action:

```
com.griffin.kernel.manager.helper
```

Policy file:

```
/usr/share/polkit-1/actions/com.griffin.kernel.manager.policy
```

The helper accepts only a fixed set of subcommands. Unknown subcommands are rejected. Every package name, version, and kernel version argument is validated with strict regular expressions *before* any package manager is invoked:

- Package names must match `^[A-Za-z0-9][A-Za-z0-9+._@-]*$`
- Versions must match `^[A-Za-z0-9][A-Za-z0-9+._:~^-]*$`
- Kernel versions for DKMS must match `^[A-Za-z0-9][A-Za-z0-9.+_~-]*$`

Arguments that look like options (`-o…`, `--force-all`, …), contain shell metacharacters, or fail the regexes are rejected with an explicit error. No argument is ever passed through a shell or `eval`.

Supported subcommands (high level):

- `version` — report helper version and protocol number
- `update-sources` — refresh package indexes
- `install` / `remove` / `hold` / `unhold`
- `dkms-autoinstall`
- `update-bootloader` (or `update-grub`)
- `reboot`
- `add-repo-xanmod`, `add-repo-liquorix`, `add-repo-chaotic-aur`, `add-repo-copr-cachyos`, `add-repo-copr-xanmod`

The protocol number (`HELPER_PROTOCOL`) is incremented when the helper’s interface changes in a way that older GUI versions cannot safely use. The GUI refuses to call an outdated helper and offers to reinstall it.

## AppImage helper installation

An AppImage cannot place files in `/usr` itself, and polkit’s `exec.path` annotation cannot point into a per-user FUSE mount. Therefore the first run of the AppImage offers to install the helper with a single generic `pkexec /bin/sh -s` prompt.

The install script:

1. Is generated at runtime by the GUI.
2. Embeds the helper binary, polkit policy, and icon as base64.
3. Verifies SHA-256 checksums of every payload against values computed when the script was built.
4. Writes the three files with correct ownership and modes.
5. Optionally runs `restorecon` and updates the icon cache.

The complete script is shown to the user before it is executed. After installation only the fixed, validated helper is ever run as root.

Uninstallation is equally simple and removes only the three files GKM created.

## What the helper deliberately does *not* do

- Accept arbitrary commands or shell scripts
- Accept paths, URLs, or free-form strings outside the validated package/kernel-version vocabulary
- Modify files outside the package manager’s normal scope (except the three files it installs for itself and the controlled edits to `pacman.conf` / versionlock lists for holds)
- Disable security features or change SELinux mode

## GUI-side validation

Before any package list is handed to the helper the GUI:

- Drops packages that have a `blocked_reason` (wrong hardware / driver branch)
- Resolves the classic signed vs. unsigned image conflict (prefers the signed image)
- Re-validates every package specification with the same style of regex the helper uses
- Refuses to remove the currently running kernel

## Environment isolation (AppImage)

When GKM is running from an AppImage it strips `LD_LIBRARY_PATH`, `PYTHONPATH`, Qt plugin paths, and other variables that would cause host tools (`apt-get`, `pacman`, `dnf`, `zypper`, `dpkg-query`, …) to load libraries from the AppImage bundle. Host commands are always executed with a cleaned environment.

## Reporting issues

If you believe you have found a way to make the helper execute unintended commands or bypass its validation, please open a security-focused issue or contact the maintainer privately. The helper is intentionally small and easy to audit; the full source is in the repository under `resources/gkm-helper`.
