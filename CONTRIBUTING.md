# Contributing

Thank you for wanting to improve **SLIM's AI Autotrader**.

This project is an AI-assisted paper-trading lab, not a casual throw-code-at-the-wall repo. The best contributions make the system easier to understand, safer to run, and cleaner to review.

## Principles

- Keep paper-trading safety first.
- Prefer explainability over cleverness.
- Make operator-facing behavior obvious and auditable.
- Do not commit secrets, tokens, or broker credentials.
- Update documentation when behavior changes.

## Development Flow

1. Create a branch for your change.
2. Make the smallest coherent change that solves one problem well.
3. Run tests locally before opening a pull request.
4. Update documentation, screenshots, and changelog entries when relevant.
5. Open a pull request with a clear summary and risk notes.

## Local Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
pip install pytest
```

## Before You Open A Pull Request

Please check these items:

- `pytest` passes
- no secrets were added to tracked files
- changed operator behavior is reflected in docs
- `README.md` is still accurate
- `CHANGELOG.md` is updated for meaningful user-facing or system-facing changes

## Documentation Rules

If your change affects:

- dashboard layout
- operator controls
- GitHub automation
- runtime behavior
- risk logic
- reporting

then update the relevant docs and add a short changelog note.

## Versioning And Releases

This project uses simple milestone tagging for public checkpoints.

- use tags like `v0.1.0`, `v0.2.0`, and so on
- update `CHANGELOG.md` before a release
- prefer small, understandable release steps over dramatic “big bang” drops

## Pull Request Style

Good pull requests explain:

- what changed
- why it changed
- operator impact
- risk or regression concerns
- test coverage or manual verification

## Security Basics

- Keep `.env` local only
- never commit broker keys or API tokens
- do not commit generated secret notes or key dumps
- rotate credentials if they were ever exposed

## If You Are Unsure

Open an issue or a draft PR and describe the goal first. That is much better than teaching the robot new tricks in total darkness.
