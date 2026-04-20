# Changelog

All notable changes to this project will be documented in this file.

The format is inspired by [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) and adapted for this repository's documentation, dashboard, automation, and paper-trading workflow.

## [Unreleased]

### Added

- Canonical changelog tracking for repo, README, and GitHub Pages.
- Changelog sections on the GitHub front page and public Pages site.
- `CONTRIBUTING.md` with development rules, release expectations, and documentation/update guidance.
- `SECURITY.md` with secret-handling, workflow, and paper-trading security expectations.
- Dedicated architecture overview document and diagram for faster onboarding.

### Changed

- Future feature work in this repository should update this file before the next push so GitHub, Pages, and local docs stay aligned.
- README now includes architecture, contribution, and security entry points.
- GitHub Pages now surfaces the changelog and broader repo governance/docs story.
- GitHub Pages layout now uses cleaner section navigation, calmer spacing, and a more guided document flow.
- README and GitHub Pages screenshots are now clickable for full-resolution viewing.

## [2026-04-20]

### Added

- GitHub Actions CI workflow for automated test runs on pushes and pull requests.
- GitHub Pages deployment workflow and static site builder for public project documentation.
- Issue templates and a pull request template for cleaner collaboration.
- Public repo screenshots for the operator dashboard, market cards, and long-run monitoring view.
- Dedicated GitHub setup guide and repo automation documentation.

### Changed

- README rewritten into a full project front door with overview, feature map, quick start, operator screenshots, live paper-trading status, and GitHub automation notes.
- Screenshot assets reorganized into `docs/assets/readme/` with project-appropriate names.
- GitHub Pages landing page extended with screenshot cards and project documentation links.
- Repo metadata refined with description, topics, and homepage URL for better discoverability.

### Fixed

- GitHub Actions test portability issue for Linux runners in the operator server config test.
- Runtime session restart behavior so stale cycle logs do not bleed into fresh sessions.

### Security

- Removed the local `keys.txt` secret bait file while keeping `.env` local and ignored.
