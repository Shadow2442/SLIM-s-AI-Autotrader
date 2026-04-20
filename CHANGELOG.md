# Changelog

All notable changes to this project will be documented in this file.

The format is inspired by [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) and adapted for this repository's documentation, dashboard, automation, and paper-trading workflow.

## [Unreleased]

### Added

- Canonical changelog tracking for repo, README, and GitHub Pages.
- Changelog sections on the GitHub front page and public Pages site.

### Changed

- Future feature work in this repository should update this file before the next push so GitHub, Pages, and local docs stay aligned.

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
