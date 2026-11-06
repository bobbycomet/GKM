# Griffin Kernel Manager (GKM)

**A modern, multi-distro Linux kernel manager with hardware awareness and safe privileged operations.**

Install the right kernel for *your* hardware in a few clicks; without fighting repositories, guessing x86-64 levels, or risking an unbootable system. GKM speaks APT, pacman, dnf, and zypper fluently, blocks packages that cannot work on your machine, and performs every privileged action through a small, validated helper with a proper polkit prompt.

Griffin Kernel Manager lets you discover, install, remove, hold, and clean up kernels across Debian/Ubuntu, Arch, Fedora/RHEL, and openSUSE families from a single Qt interface. It understands your CPU (x86-64-v1 through v4), GPU, NVIDIA driver branch, and cloud environment so it only offers kernels and modules that will actually work on your machine.

Distributed as a portable **AppImage**.

Check [Releases](https://github.com/bobbycomet/GKM/releases)

## Why it exists

Managing kernels on Linux is fragmented. Official tools are distro-specific, third-party kernels (XanMod, Liquorix, CachyOS, etc.) live in different repositories, and hardware mismatches (wrong microarchitecture level, NVIDIA module branch conflicts, cloud-specific images) are easy to hit. Existing managers either ignore these realities or require running the entire application as root.

GKM was built to solve that: one tool, proper package-manager backends, hardware-aware filtering, and a tightly constrained privileged helper that never becomes a general root shell.

---

**The original foundation:** [github.com/bobbycomet/XKM-Multi-Kernel-Manager](https://github.com/bobbycomet/XKM-Multi-Kernel-Manager)  
**Documentation:** See the [Wiki](wiki/) for installation, supported distributions, security model, FAQ, and contributing guidelines.
