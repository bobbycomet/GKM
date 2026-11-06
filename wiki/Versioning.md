# Versioning & Compatibility

## Application version

The GUI reports its version via `--version` and in the System information dialog. Release tags on GitHub follow normal semantic versioning.

The AppImage update check queries:

```
https://api.github.com/repos/bobbycomet/XKM-Multi-Kernel-Manager/releases/latest
```

and compares the remote tag against the running version with a simple dotted-numeric comparison.

## Helper protocol

The privileged helper declares:

```bash
readonly HELPER_VERSION="4.0.0"
readonly HELPER_PROTOCOL=2
```

`HELPER_PROTOCOL` is the important number. It is incremented whenever the helper’s command-line interface changes in a way that would make an older GUI unsafe or incorrect (new required arguments, changed semantics of an existing subcommand, stricter validation that older GUIs do not expect, etc.).

On startup (and before any privileged action) the GUI asks the installed helper for its protocol. If the installed protocol is lower than the protocol the GUI was built against, the helper is considered **outdated** and the user is offered a reinstall.

This mechanism allows the AppImage and the system helper to evolve independently while remaining safe.

## Configuration migration

When the project was renamed from XanMod Kernel Manager (XKM) to Griffin Kernel Manager (GKM):

- User configuration is copied once from `~/.config/xanmod-kernel-manager/` to `~/.config/griffin-kernel-manager/` if the new location does not yet exist. The old directory is left in place.
- Managed `IgnorePkg` blocks in `pacman.conf` that still use the old XKM markers are read and rewritten with the new GKM markers on the next hold/unhold operation. User-defined `IgnorePkg` lines outside the managed block are never touched.

## Backward compatibility guarantees

- An older AppImage can still talk to a newer helper as long as the protocol number has not been increased.
- A newer AppImage will refuse to use an older helper and will offer to replace it.
- Kernel package lists produced by older backends remain understandable by newer UIs because the `KernelPackage` model fields have been additive.

## Building releases

Release engineering details live in the repository’s packaging scripts (not covered in this wiki). The important artefacts for each release are:

- The AppImage itself
- The `gkm-helper` script (embedded and also installable)
- The polkit policy file
- Matching icons

Checksums of the helper and policy are embedded in the install script that the AppImage generates, so a tampered payload is rejected at install time.
