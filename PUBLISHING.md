# Publishing to PyPI

This document walks the maintainer through a release of `opentext-pa-mcp` to PyPI. It assumes you already have `uv` installed (`pip install uv`).

## One-time setup

### 1. Create a PyPI account

- Go to https://pypi.org/account/register/
- Verify your email
- (Recommended) Enable 2FA at https://pypi.org/manage/account/

### 2. (Recommended) Reserve the name on TestPyPI first

TestPyPI is a sandbox copy of PyPI for trial runs. Sign up at https://test.pypi.org/account/register/. The accounts on PyPI and TestPyPI are separate.

### 3. Generate a PyPI API token

PyPI no longer accepts password-based uploads — you need an API token.

- Visit https://pypi.org/manage/account/token/
- Click "Add API token"
- Name: `opentext-pa-mcp upload` (or anything)
- Scope: `Project: opentext-pa-mcp` once the project exists; for the first release select "Entire account" (PyPI requires this for the first upload), then rotate to a project-scoped token afterwards.
- **Copy the token immediately** — it starts with `pypi-` and is shown only once.

Optionally save it to `~/.pypirc`:

```ini
[pypi]
  username = __token__
  password = pypi-AgEI...your-token-here...
```

Or pass it on the command line each time (next section).

## Publish a release

From the project root with a clean working tree.

### 1. Make sure tests are green

```powershell
uv run pytest tests/unit
```

(Integration tests require a live tenant — skip them for a release if you don't have one in front of you.)

### 2. Bump the version

Edit `pyproject.toml`:

```toml
version = "0.1.0"   # change this
```

Versioning follows semver. For early development, bumping the patch (`0.1.0` → `0.1.1`) is fine.

Also update `src/opentext_pa_mcp/__init__.py`:

```python
__version__ = "0.1.0"
```

(Yes, the two have to be kept in sync for now. A `__version__` reflection trick can be added later.)

Commit the bump:

```powershell
git add pyproject.toml src/opentext_pa_mcp/__init__.py
git commit -m "chore: bump version to 0.1.1"
```

### 3. Build the artifacts

```powershell
# Remove old builds (optional but clean):
Remove-Item -Recurse -Force dist -ErrorAction SilentlyContinue

uv build
```

You should see two files in `dist/`:
- `opentext_pa_mcp-X.Y.Z-py3-none-any.whl`  ← the wheel
- `opentext_pa_mcp-X.Y.Z.tar.gz`            ← the sdist

### 4. (Recommended) Test-upload to TestPyPI first

```powershell
uv publish --publish-url https://test.pypi.org/legacy/ --token pypi-YOUR-TEST-TOKEN dist/*
```

Then install from TestPyPI into a throwaway venv to confirm it works:

```powershell
uv venv .venv-testpypi
uv pip install --python .venv-testpypi\Scripts\python.exe `
  --index-url https://test.pypi.org/simple/ `
  --extra-index-url https://pypi.org/simple/ `
  opentext-pa-mcp

.\.venv-testpypi\Scripts\opentext-pa-mcp.exe
# Should print the config-error message and exit 2.
Remove-Item -Recurse -Force .venv-testpypi
```

### 5. Upload to real PyPI

```powershell
uv publish --token pypi-YOUR-REAL-TOKEN dist/*
```

You can omit `--token` if `~/.pypirc` is configured.

If `uv publish` is unavailable for any reason, the equivalent `twine` command is:

```powershell
uv run python -m twine upload --username __token__ --password pypi-YOUR-TOKEN dist/*
```

(`twine` will need to be installed: `uv pip install twine`.)

### 6. Verify the release

- Browse to https://pypi.org/project/opentext-pa-mcp/ and confirm the release page renders correctly.
- In a fresh venv, install via `uvx`:
  ```powershell
  uvx opentext-pa-mcp
  ```
  It should print the config-error message and exit (no env vars set yet).

### 7. Tag the release in git

```powershell
git tag -a v0.1.1 -m "Release 0.1.1"
git push origin v0.1.1   # if you have a remote configured
```

## After publishing

Update the `mcpServers` snippet in `README.md` only if you've changed env var names or added new ones; otherwise the snippet remains valid because users always invoke through `uvx opentext-pa-mcp`.

Send the install instructions to test users. Common gotchas to mention:
- They need `uv` installed (or Python 3.11+ with `pipx`).
- The MCP client (Claude Desktop, Claude Code, etc.) needs to be **fully restarted** after editing its config — the MCP server is spawned at client startup.
- The first invocation downloads the package; subsequent runs use the cached copy.

## Yanking a bad release

If you publish something broken:

1. Bump the version, fix, and re-publish.
2. Then yank the bad version: https://pypi.org/manage/project/opentext-pa-mcp/release/X.Y.Z/ → "Yank".
   - Yanked versions remain installable by exact version pin but are skipped by version resolvers.
   - **Do not delete** — PyPI does not allow re-uploading the same version number even after deletion.
