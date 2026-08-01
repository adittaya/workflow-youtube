# Testing

The installer ships a dependency-free test suite (stdlib `unittest`) — no
pytest, no mocks framework, no network requirements.

## Run the suite

```bash
python3 installer/tests/run_tests.py
```

Expected result: **52 tests, all passing** (varies as tests are added).

Coverage:

| Area | File | What's covered |
| --- | --- | --- |
| Config | `test_config.py` | JSON/YAML/TOML round-trips, corrupt-file errors, `0600` modes, merge semantics |
| Env + packages | `test_env.py` | OS/arch detection, registry parsing, version comparison, package mapping |
| Shell profiles | `test_shellprofile.py` | bash/zsh/fish/pwsh syntax, idempotency, reversibility |
| State + rollback | `test_state.py` | stage lifecycle, repair detection, undo of remove/restore, persistence |
| Downloads | `test_downloads.py` | local HTTP server: sha256, size, wrong-checksum, resume, URL safety |
| UI + updates | `test_interactive.py` | non-interactive defaults, menus, version compare, changelog |

## Integration smoke test (safe)

The full pipeline can be exercised against a throwaway environment without
touching your real config or system packages:

```bash
rm -rf /tmp/inst-{home,cfg,data}
mkdir -p /tmp/inst-home
XDG_CONFIG_HOME=/tmp/inst-cfg XDG_DATA_HOME=/tmp/inst-data HOME=/tmp/inst-home \
  python3 -m installer --non-interactive install --dry-run

# real install with zero system changes (empty package set):
mkdir -p /tmp/inst-cfg/installer
printf '{"packages": [], "pip_packages": [], "shell_profile": "no"}' \
  > /tmp/inst-cfg/installer/config.json
XDG_CONFIG_HOME=/tmp/inst-cfg XDG_DATA_HOME=/tmp/inst-data HOME=/tmp/inst-home \
  python3 -m installer --non-interactive install

# verify the installed shim end-to-end:
HOME=/tmp/inst-home /tmp/inst-home/.local/bin/installer verify
```

## Verification commands

```bash
python3 -m py_compile installer/**/*.py          # every module compiles
python3 -m installer --non-interactive doctor     # environment diagnostics
python3 -m installer --non-interactive verify     # tool + install checks
```

## CI

`.github/workflows/ci.yml` runs the full suite on Linux, macOS and Windows for
every push/PR. `.github/workflows/release.yml` builds a GitHub Release from a
tag, which the `installer update` command consumes.
