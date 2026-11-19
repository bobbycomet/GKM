# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Bobby Comet
"""Privileged-helper plumbing.

Every root operation is `pkexec /usr/lib/gkm/gkm-helper <subcommand> ...` so
polkit can show an GKM-specific prompt (action com.griffin.kernel.manager.helper).
That requires the helper and the polkit policy to live at fixed system paths.

A distro package puts them there. An AppImage cannot: its payload sits in a
per-user FUSE mount that root (and polkit's exec.path annotation) cannot use.
So on first run the AppImage offers to install them itself, through ONE generic
`pkexec /bin/sh -s` prompt whose script it feeds over stdin. The script is
fully shown to the user first; afterwards only the fixed, validating helper
ever runs as root.
"""
import base64
import hashlib
import os
import subprocess
from enum import Enum
from pathlib import Path

from . import HELPER_PROTOCOL
from .hostenv import host_env, run_host

SYSTEM_HELPER = "/usr/lib/gkm/gkm-helper"
SYSTEM_POLICY = "/usr/share/polkit-1/actions/com.griffin.kernel.manager.policy"
SYSTEM_ICON = "/usr/share/icons/hicolor/256x256/apps/gkm.png"
POLICY_NAME = "com.griffin.kernel.manager.policy"


def resource_dir():
    env = os.environ.get("GKM_RESOURCE_DIR")
    return Path(env) if env else Path(__file__).resolve().parent / "resources"


def bundled(name):
    return resource_dir() / name


def is_appimage():
    return bool(os.environ.get("GKM_APPIMAGE") or os.environ.get("APPIMAGE"))


def sha256(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return ""


class HelperState(Enum):
    OK = "ok"
    MISSING = "missing"
    OUTDATED = "outdated"
    UNSUPPORTED = "unsupported"     # immutable system / pkexec missing


def installed_protocol():
    """Protocol number reported by the installed helper (0 = absent / too old)."""
    if not os.path.exists(SYSTEM_HELPER):
        return 0
    rc, out = run_host([SYSTEM_HELPER, "version"], timeout=10)
    if rc == 0 and "protocol" in out:
        try:
            return int(out.split("protocol")[1].split()[0])
        except (ValueError, IndexError):
            return 0
    return 0


def helper_state(distro=None):
    if distro is not None and distro.immutable:
        return HelperState.UNSUPPORTED
    from shutil import which
    if not which("pkexec", path=host_env().get("PATH")):
        return HelperState.UNSUPPORTED
    if not os.path.exists(SYSTEM_HELPER):
        return HelperState.MISSING
    if installed_protocol() < HELPER_PROTOCOL:
        return HelperState.OUTDATED
    if is_appimage() and (sha256(SYSTEM_HELPER) != sha256(bundled("gkm-helper"))
                          or sha256(SYSTEM_POLICY) != sha256(bundled(POLICY_NAME))):
        return HelperState.OUTDATED
    return HelperState.OK


def helper_path():
    """Path pkexec is pointed at. Env override and a source-tree fallback exist
    for development: pkexec accepts any path, just with the generic prompt."""
    env = os.environ.get("GKM_HELPER_PATH")
    if env:
        return env
    if os.path.exists(SYSTEM_HELPER):
        return SYSTEM_HELPER
    return str(bundled("gkm-helper"))


def _b64(path):
    return base64.encodebytes(Path(path).read_bytes()).decode()


def build_install_script():
    """POSIX sh script, run as root via `pkexec /bin/sh -s`. Payloads are
    embedded base64 and verified against SHA-256 values computed here before
    anything is moved into place."""
    items = [
        ("HELPER", bundled("gkm-helper"), SYSTEM_HELPER, "0755"),
        ("POLICY", bundled(POLICY_NAME), SYSTEM_POLICY, "0644"),
        ("ICON", bundled("gkm.png"), SYSTEM_ICON, "0644"),
    ]
    lines = ["set -eu", "umask 022",
             'T=$(mktemp -d /run/gkm-install.XXXXXX) || T=$(mktemp -d)',
             'trap \'rm -rf "$T"\' EXIT']
    for tag, src, _dst, _mode in items:
        lines.append(f"base64 -d > \"$T/{tag}\" <<'GKM_EOF_{tag}'")
        lines.append(_b64(src).rstrip("\n"))
        lines.append(f"GKM_EOF_{tag}")
    for tag, src, dst, mode in items:
        d = os.path.dirname(dst)
        lines += [
            f'[ "$(sha256sum "$T/{tag}" | cut -d" " -f1)" = "{sha256(src)}" ] || {{ echo "checksum mismatch ({tag})" >&2; exit 1; }}',
            f"install -d -m 0755 -o root -g root {d}",
            f"install -m {mode} -o root -g root \"$T/{tag}\" {dst}.new",
            f"mv -f {dst}.new {dst}",
        ]
    lines += [
        "command -v restorecon >/dev/null 2>&1 && restorecon -R /usr/lib/gkm /usr/share/polkit-1/actions 2>/dev/null || true",
        "command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t /usr/share/icons/hicolor 2>/dev/null || true",
        'echo "GKM helper installed: /usr/lib/gkm/gkm-helper"',
    ]
    return "\n".join(lines) + "\n"


def build_uninstall_script():
    return ("set -eu\n"
            f"rm -f {SYSTEM_HELPER} {SYSTEM_POLICY} {SYSTEM_ICON}\n"
            "rmdir /usr/lib/gkm 2>/dev/null || true\n"
            'echo "GKM helper removed."\n')


def describe_install():
    return (
        "GKM needs a small privileged helper so that kernel changes can be authorised with a proper "
        "polkit prompt instead of running the whole app as root.\n\n"
        "One administrator prompt will copy:\n"
        f"  • {SYSTEM_HELPER}  (fixed set of validated commands)\n"
        f"  • {SYSTEM_POLICY}\n"
        f"  • {SYSTEM_ICON}\n\n"
        "After that, only this helper runs as root. You can remove it any time with "
        "'GKM --uninstall-helper'."
    )


def run_privileged_script(script, on_line):
    """Run `script` as root via pkexec /bin/sh -s, streaming output to on_line.
    Returns the exit status."""
    try:
        proc = subprocess.Popen(["pkexec", "/bin/sh", "-s"], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, env=host_env(), bufsize=1)
    except OSError as e:
        on_line(f"ERROR: could not start pkexec: {e}\n")
        return 127
    proc.stdin.write(script)
    proc.stdin.close()
    for line in proc.stdout:
        on_line(line)
    return proc.wait()
