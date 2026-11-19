# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Bobby Comet
"""Running host tools from inside an AppImage.

An AppImage launches with LD_LIBRARY_PATH (and friends) pointing at bundled
libraries. Leaking that into host binaries such as pacman, dnf, zypper or
dpkg-query can make them load the wrong libssl/libcurl/libarchive and crash,
so every subprocess GKM starts goes through :func:`host_env`.
"""
import os
import subprocess

_STRIP = (
    "LD_LIBRARY_PATH", "LD_PRELOAD", "PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP",
    "PYTHONNOUSERSITE", "PYTHONDONTWRITEBYTECODE", "QT_PLUGIN_PATH",
    "QT_QPA_PLATFORM_PLUGIN_PATH", "QML2_IMPORT_PATH", "QT_QPA_PLATFORMTHEME",
    "ARGV0", "OWD",
)


def host_env(extra=None):
    env = dict(os.environ)
    orig_ld = env.pop("GKM_ORIG_LD_LIBRARY_PATH", None)
    for key in _STRIP:
        env.pop(key, None)
    if orig_ld:
        env["LD_LIBRARY_PATH"] = orig_ld
    appdir = os.environ.get("APPDIR")
    if appdir:
        env["PATH"] = ":".join(
            p for p in env.get("PATH", "").split(":") if p and not p.startswith(appdir)
        )
    for key in ("APPDIR", "APPIMAGE", "GKM_APPIMAGE"):
        env.pop(key, None)
    # Machine-parsable output: package managers translate field names.
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    env.pop("LANGUAGE", None)
    env["DEBIAN_FRONTEND"] = "noninteractive"
    env["APT_LISTCHANGES_FRONTEND"] = "none"
    env["NEEDRESTART_MODE"] = "l"
    if extra:
        env.update(extra)
    return env


def run_host(cmd, timeout=120, input_text=None, merge_stderr=False):
    """Run a host command. Returns (returncode, stdout) - stdout plus stderr when
    merge_stderr is set. Never raises for missing binaries or timeouts: those
    come back as rc 127 / 124."""
    try:
        proc = subprocess.run(
            cmd, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT if merge_stderr else subprocess.PIPE,
            text=True, timeout=timeout, env=host_env(), input=input_text, errors="replace",
        )
        return proc.returncode, proc.stdout
    except FileNotFoundError:
        return 127, ""
    except subprocess.TimeoutExpired:
        return 124, ""
    except OSError:
        return 126, ""


def capture(cmd, timeout=120):
    rc, out = run_host(cmd, timeout=timeout)
    return out if rc == 0 else ""
