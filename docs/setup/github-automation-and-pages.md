# GitHub Automation And Pages

This project now includes a lightweight GitHub automation path so the repository can:

- run tests automatically on pushes and pull requests
- build a static documentation site
- publish that site through GitHub Pages

The setup is intentionally simple. The goal is a reliable public project surface, not an overengineered CI carnival.

## What Is Included

The repository now contains:

- `.github/workflows/ci.yml`
  Runs `pytest` on pushes to `main` or `master`, and on pull requests.
- `.github/workflows/pages.yml`
  Builds the documentation landing page and deploys it with GitHub Pages.
- `scripts/build_github_pages.py`
  Generates the static site into `site/` from the main project documents.

## Expected Repository Target

The current Pages builder assumes the public repository target will be:

- `Shadow2442/Autotrade`

If the repository name changes later, the build still works because the GitHub Actions workflow passes `${{ github.repository }}` into the generator.

## GitHub Pages Setup

After pushing this repository to GitHub:

1. Open the repository settings.
2. Go to `Pages`.
3. Set the source to `GitHub Actions`.
4. Push to `main` or trigger the `pages` workflow manually.

The deployed site should then appear at the normal GitHub Pages project URL pattern:

- `https://shadow2442.github.io/Autotrade/`

If the repository name changes, the trailing path changes with it.

## CI Workflow

The CI workflow is intentionally small:

1. Check out the repository
2. Set up Python `3.12`
3. Install the project with `pip install -e .`
4. Install `pytest`
5. Run `pytest`

This gives the project a basic quality gate without making every push feel like it needs a priest and a change advisory board.

## Pages Workflow

The Pages workflow does this:

1. Check out the repository
2. Set up Python `3.12`
3. Install the local project
4. Run `python scripts/build_github_pages.py --output site --repo "${{ github.repository }}"`
5. Upload the generated `site/` directory
6. Deploy it with `actions/deploy-pages`

It runs on:

- pushes to `main`
- manual `workflow_dispatch`

## Local Preview

You can generate the site locally before pushing:

```powershell
.\.venv\Scripts\python.exe scripts\build_github_pages.py --output site --repo Shadow2442/Autotrade
```

That writes:

- `site/index.html`
- `site/404.html`
- `site/assets/site.css`

The generated site is a simple landing page that links back to the canonical repository documents on GitHub.

## Document Flow

The site builder currently highlights these repository areas:

- research
- architecture
- setup
- operations

That keeps the public project story clean:

1. what the system is
2. how it is designed
3. how it is operated
4. how it is published

## Recommended GitHub Follow-Up

After the initial push, the next sensible GitHub upgrades would be:

- repository description and topics
- branch protection on `main`
- issue templates
- pull request template
- release notes once the project stabilizes

Those are optional. The current setup is enough to establish a proper public repo with automated docs publishing.
