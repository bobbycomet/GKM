# Frequently Asked Questions

## General

**Why is it called Griffin Kernel Manager / GKM?**  
It is the successor to XanMod Kernel Manager (XKM). The project was renamed when support expanded well beyond XanMod to multiple distro families and kernel sources. Configuration and hold markers from the old name are migrated automatically.

**Is this a replacement for my distro’s kernel management tools?**  
It is a complementary UI. It uses the same package managers your distro already trusts. It does not replace `apt`, `pacman`, `dnf`, or `zypper`; it drives them.

**Does GKM compile kernels?**  
No. It only manages pre-built packages from repositories.

## Installation & helper

**Why does the AppImage ask to install a helper?**  
Polkit needs a fixed path on the system for its `exec.path` annotation, and an AppImage’s FUSE mount is not suitable for that. The helper is a small, audited binary that only performs the operations listed in the Security page. You can refuse the installation; the application will still list kernels but will not be able to install or remove them.

**Can I install the helper system-wide without the AppImage?**  
Yes. Packaging the helper and policy file for your distribution is the preferred long-term solution. The AppImage self-install path exists so users can get a working privileged path immediately.

**How do I completely remove GKM?**  
Delete the AppImage, run `--uninstall-helper` (or remove the three files under `/usr` manually), and optionally delete `~/.config/griffin-kernel-manager/`.

## Hardware & filtering

**Why are some XanMod / CachyOS packages greyed out?**  
They require a higher x86-64 microarchitecture level than your CPU supports. Installing them would produce a kernel that cannot boot. The blocked reason is shown in the UI.

**Why don’t I see NVIDIA modules for my driver version?**  
GKM only offers `linux-modules-nvidia-N-*` packages that match the major version of the driver currently installed on the system. This avoids the classic APT dependency conflicts between different NVIDIA branches.

**I have an NVIDIA GPU but modules are still blocked.**  
Confirm that the proprietary driver is actually loaded (`/proc/driver/nvidia/version` or `nvidia-smi`). If you are using the open kernel modules or a different packaging layout, detection may need adjustment—open an issue with the output of `gkm --info`.

## Operations

**Can I remove the kernel I am currently running?**  
No. The UI prevents selection of the active kernel for removal.

**What does “Hold” do?**  
It tells the package manager not to upgrade the package:

- APT → `apt-mark hold`
- pacman → `IgnorePkg` entry in a managed block inside `pacman.conf`
- dnf → versionlock plugin
- zypper → `addlock`

**What is the difference between Remove and Purge?**  
On APT and pacman, Purge also deletes configuration files / saved config backups. On dnf and zypper there is no distinct purge operation.

**After installing a new kernel, do I need to update the bootloader myself?**  
Usually no. Kernel packages normally update the bootloader. GKM runs a safety-net refresh (`update-grub`, `grub-mkconfig`, or `update-bootloader`) afterward; if the system uses BLS, systemd-boot, Limine, or rEFInd the helper simply reports that no extra step is required.

**DKMS failed after installing a new kernel.**  
The most common cause is missing headers/devel packages for that kernel. Install the matching headers package and use the “Rebuild DKMS” button. The log panel shows the exact dkms output.

## Detection problems

**The wrong distro family is detected.**  
Run `gkm --info` and compare with `/etc/os-release`. Derivatives that set unusual `ID` / `ID_LIKE` values can occasionally be mis-mapped; please report them.

**No kernels appear after Refresh.**  
Check the Details log. Common causes: package indexes are empty or out of date, network problems, or the backend could not run the package manager (missing binary, permission issues inside the cleaned AppImage environment).

**The application is slow when switching light/dark mode or changing tabs.**  
Older versions built every package row eagerly. Current versions build flavor sections and package rows lazily on first expand. If you still see lag with a very large mainline archive, collapsing unused version cards helps.

## Development

**Where is the source?**  
https://github.com/bobbycomet/XKM-Multi-Kernel-Manager

**How do I run the tests?**  
```bash
./Griffin_Kernel_Manager-*.AppImage --test
```
or, from a source checkout with dependencies installed:
```bash
python -m unittest discover
```

**How do I verify the helper syntax and contract?**  
The integration tests include a full helper contract check (subcommand list, argument rejection, protocol version, install-script checksums, etc.).
