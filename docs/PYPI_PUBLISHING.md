# PyPI publishing (perfsage-signalpilot)

The release workflow publishes to PyPI via [trusted publishing](https://docs.pypi.org/trusted-publishers/) when a `v*.*.*` tag is pushed.

## One-time setup

1. Register the project on PyPI (first publish only):
   - Create account at https://pypi.org
   - After first successful publish, project URL: https://pypi.org/project/perfsage-signalpilot/

2. Add trusted publisher on PyPI:
   - Project → **Publishing** → **Add a new pending publisher**
   - **PyPI Project Name:** `perfsage-signalpilot`
   - **Owner:** `perfsage`
   - **Repository name:** `signalpilot`
   - **Workflow name:** `release.yml`
   - **Environment name:** leave blank

3. Re-run the failed Release workflow or push a patch tag:
   ```bash
   git tag -a v1.0.1 -m "v1.0.1 — PyPI publish retry"
   git push origin v1.0.1
   ```

## Install (after PyPI is live)

```bash
pip install perfsage-signalpilot
signalpilot --help
```

Until PyPI is configured, install from GitHub:

```bash
pip install "git+https://github.com/perfsage/signalpilot@v1.0.0"
```

Or clone and `pip install -e .` per README.
