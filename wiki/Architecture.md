# Architecture

Griffin Kernel Manager is a Python 3 + PyQt6 application with a small Bash privileged helper.

## High-level layout

```
gkm/
├── __main__.py          # entry point
├── app.py               # CLI flags, QApplication bootstrap, smoke test
├── config.py            # user config + legacy migration
├── distro.py            # /etc/os-release parsing, family/base resolution
├── hardware.py          # CPU flags → psABI, GPU, NVIDIA major, cloud
├── hostenv.py           # cleaned environment for host tools (AppImage safety)
├── model.py             # KernelPackage, Provider, RepoOffer
├── privilege.py         # helper state, install/uninstall scripts, pkexec wrapper
├── vercmp.py            # pure-Python deb / rpm / evr comparison
├── backends/
│   ├── base.py          # Backend interface, auto-remove logic, helpers
│   ├── apt.py           # Debian/Ubuntu family
│   ├── pacman.py        # Arch family
│   ├── dnf.py           # Fedora/RHEL family
│   ├── zypper.py        # openSUSE/SUSE family
│   └── rpm_common.py    # shared RPM helpers
├── ui/
│   ├── window.py        # main window, theme application
│   ├── manager.py       # KernelManager – tabs, selection, actions, logging
│   ├── cards.py         # expandable version / flavor / group cards
│   ├── widgets.py       # dispatcher, clickable frames, toasts
│   └── theme.py         # palettes and class-selector stylesheets
└── resources/
    ├── gkm-helper       # the privileged Bash script
    ├── com.griffin.kernel.manager.policy
    └── icons
```

## Backend contract

Every backend implements:

- `providers()` → list of `Provider` (tabs)
- `repos()` → list of `RepoOffer` (optional “add repository” banners)
- `collect(refresh=False)` → flat list of `KernelPackage`
- `version_cmp(a, b)` → negative / zero / positive
- `running_release()` (usually `platform.uname().release`)
- optional `auto_remove_candidates(rows)`

The UI never talks to a package manager directly. It only consumes the list of `KernelPackage` objects and later hands validated package *specs* to the helper.

## Data model

`KernelPackage` carries:

- identity (`name`, `version`, `spec`)
- state (`installed`, `active`, `held`, `is_selected`)
- presentation (`flavor`, `role`, `kgroup`, `group_label`, `size`, `repo`)
- safety (`blocked_reason`, `is_meta`)

Selection state lives on the model objects, not on the widgets. This is what allows group-header clicks to work even before a card’s package rows have been built.

## Privilege flow

1. GUI decides an action is needed and calls `_require_helper`.
2. If the helper is missing/outdated and the process is an AppImage → offer installation.
3. If the system is immutable or lacks pkexec → show an error and stop.
4. Otherwise build a command line: `pkexec /usr/lib/gkm/gkm-helper <subcommand> [validated args…]`
5. Stream stdout/stderr into the log panel on the main thread via a queued dispatcher.
6. On completion, refresh the kernel list and run any post-actions (bootloader, DKMS, reboot prompt).

## UI performance notes

- Theme switching uses a `QPalette` plus **class-selector-only** stylesheets. A bare `QWidget { … }` rule would force Qt to re-polish every widget and becomes expensive when thousands of package rows exist.
- Version cards, flavor sections, and package rows are created lazily on first expand and then cached.
- Search and flavor filtering rebuild only the visible structure of the current tab; they do not re-query the package manager.

## Version comparison

Three pure-Python implementations live in `vercmp.py`:

- `deb_vercmp` — matches dpkg’s algorithm (epochs, upstream, revision, `~` semantics)
- `rpmvercmp` / `evr_vercmp` — matches the algorithm used by rpm, dnf, zypper, and pacman
- `version_newer` — simple dotted-numeric comparison used only for AppImage update checks

python-apt and similar bindings are deliberately avoided so the application can be bundled as a self-contained AppImage.

## Testing

The test suite covers:

- Distro detection edge cases and derivative mapping
- Hardware flag → psABI calculation
- Version comparison for all three schemes
- APT name parsing, flavor extraction, GPU/NVIDIA filtering, auto-remove policy
- Pacman / dnf / zypper collection logic with realistic fixture data
- Full helper contract (subcommand surface, argument rejection, protocol, install-script checksums, legacy hold migration)
- GUI smoke tests that instantiate the real window and expand cards for every backend

Tests that need a display use `QT_QPA_PLATFORM=offscreen`.
