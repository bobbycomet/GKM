# Contributing

Thank you for your interest in improving Griffin Kernel Manager.

## Development setup

1. Clone the repository.
2. Create a virtual environment and install dependencies (PyQt6 and the standard library are the main requirements; the test suite also needs the usual unittest tooling).
3. For a quick syntax and unit-test check:
   ```bash
   python -m unittest discover -s tests -v
   ```
4. The AppImage build and the `--smoke-test` flag exercise the real GUI with an offscreen platform plugin.

## Coding guidelines

- Prefer clarity over cleverness. The privilege and validation paths in particular should remain easy to audit.
- All package names, versions, and kernel versions that reach the helper must be validated with the same strict regular expressions the helper itself uses.
- Do not introduce new helper subcommands that accept free-form strings, paths, or URLs.
- Hardware filtering decisions belong in the backend’s `collect()` method (or in small pure functions it calls). The UI should only respect the `blocked_reason` field.
- Keep stylesheets limited to class selectors (`QPushButton`, `QFrame#card`, …). Avoid bare `QWidget` rules.
- When adding support for a new third-party repository, implement the recipe inside the helper and expose it only through a hard-coded `RepoOffer`. Never let the GUI supply an arbitrary repository definition.

## Testing expectations

- New package-name or flavor-parsing logic should come with unit tests (see `test_apt.py`, `test_rpm_arch.py`).
- Changes to the helper must keep the contract tests in `test_integration.py` passing. In particular:
  - Every subcommand the GUI can emit must exist in the helper.
  - Hostile arguments must still be rejected.
  - The install script must remain valid shell and must verify checksums.
- If you touch multi-version auto-remove logic, verify that the running kernel, held packages, and meta packages remain protected.

## Pull requests

- Keep PRs focused. Separate pure refactors from behavioural changes when practical.
- Mention any user-visible changes so the release notes can be updated.
- If the helper protocol needs to be bumped, say so explicitly; the GUI and helper must stay in sync.

## Reporting bugs

Please include:

- Output of `gkm --info`
- Distribution and desktop environment
- Whether you are running the AppImage or a packaged build
- Relevant section of the Details log (or the log file under `~/.config/griffin-kernel-manager/logs/`)
- Steps to reproduce

Security-related reports should be handled privately if they involve privilege escalation or validation bypasses.

## Code of conduct

Be respectful. This is a small project maintained primarily by one developer; constructive, concrete feedback is appreciated.
