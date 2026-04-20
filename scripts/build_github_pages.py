from __future__ import annotations

import argparse
import html
import os
import shutil
from pathlib import Path


DOC_ORDER = [
    Path("docs/research/alpaca-paper-build-plan.md"),
    Path("docs/research/published-resources.md"),
    Path("docs/research/strategy-categories.md"),
    Path("docs/architecture/system-overview.md"),
    Path("docs/architecture/system-design.md"),
    Path("docs/architecture/operator-dashboard-and-automation.md"),
    Path("docs/operations/runbook.md"),
    Path("docs/operations/security-controls.md"),
    Path("docs/setup/mcp-onboarding.md"),
    Path("docs/setup/github-automation-and-pages.md"),
    Path("CONTRIBUTING.md"),
    Path("SECURITY.md"),
    Path("CHANGELOG.md"),
]

SCREENSHOT_ORDER = [
    (
        Path("docs/assets/readme/operator-dashboard-overview.png"),
        "Operator Dashboard",
        "Main operator window with account state, market watch, order tape, and session controls.",
    ),
    (
        Path("docs/assets/readme/market-overview-cards.png"),
        "Market Overview Cards",
        "Per-asset trading cards with signal, risk, momentum, moving averages, and buy/sell zones.",
    ),
    (
        Path("docs/assets/readme/night-watch-monitor.png"),
        "Night Watch Monitor",
        "Long-run monitoring surface for session status, trade counts, warnings, and fresh report signals.",
    ),
]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


def extract_intro(markdown: str) -> str:
    lines = [line.strip() for line in markdown.splitlines()]
    chunks: list[str] = []
    for line in lines:
        if not line or line.startswith("#"):
            continue
        if line.startswith("- ") or line.startswith("* "):
            break
        chunks.append(line)
        if len(" ".join(chunks)) > 280:
            break
    return " ".join(chunks[:3]).strip()


def markdown_title(markdown: str, fallback: str) -> str:
    for line in markdown.splitlines():
        if line.startswith("#"):
            return line.lstrip("#").strip()
    return fallback


def repo_doc_url(repo_slug: str, relative_path: Path) -> str:
    return f"https://github.com/{repo_slug}/blob/main/{relative_path.as_posix()}"


def extract_changelog_sections(markdown: str, limit: int = 2) -> list[tuple[str, list[tuple[str, list[str]]]]]:
    sections: list[tuple[str, list[tuple[str, list[str]]]]] = []
    current_title: str | None = None
    current_groups: list[tuple[str, list[str]]] = []
    current_group_title: str | None = None
    current_group_items: list[str] = []

    def flush_group() -> None:
        nonlocal current_group_title, current_group_items, current_groups
        if current_group_title and current_group_items:
            current_groups.append((current_group_title, current_group_items.copy()))
        current_group_title = None
        current_group_items = []

    def flush_section() -> None:
        nonlocal current_title, current_groups
        flush_group()
        if current_title and current_groups:
            sections.append((current_title, current_groups.copy()))
        current_title = None
        current_groups = []

    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            flush_section()
            current_title = line[3:].strip()
        elif line.startswith("### "):
            flush_group()
            current_group_title = line[4:].strip()
        elif line.startswith("- "):
            current_group_items.append(line[2:].strip())

    flush_section()
    return sections[:limit]


def build_index(root: Path, output_dir: Path, repo_slug: str) -> None:
    readme = read_text(root / "README.md")
    changelog = read_text(root / "CHANGELOG.md")
    project_title = markdown_title(readme, "Autotrade")
    project_intro = extract_intro(readme)

    doc_cards: list[str] = []
    for relative_path in DOC_ORDER:
        absolute_path = root / relative_path
        if not absolute_path.exists():
            continue
        content = read_text(absolute_path)
        title = markdown_title(content, relative_path.stem.replace("-", " ").title())
        intro = extract_intro(content) or "Project documentation."
        parent_label = relative_path.parent.name.title() if relative_path.parent.name else "Repo"
        doc_cards.append(
            f"""
            <article class="doc-card">
              <span class="doc-tag">{html.escape(parent_label)}</span>
              <h3>{html.escape(title)}</h3>
              <p>{html.escape(intro)}</p>
              <a href="{html.escape(repo_doc_url(repo_slug, relative_path))}" target="_blank" rel="noreferrer">Open on GitHub</a>
            </article>
            """
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = output_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    screenshots_dir = assets_dir / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    css = """
    :root {
      --bg: #08111a;
      --panel: #0f1c28;
      --panel-2: #132434;
      --line: #234056;
      --text: #ecf3f9;
      --muted: #9db1c0;
      --accent: #66b8ff;
      --good: #2bd67b;
      --warn: #f4b04f;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", Tahoma, sans-serif;
      background: radial-gradient(circle at top, #173149 0%, #0c1723 30%, #08111a 100%);
      color: var(--text);
    }
    .wrap {
      max-width: 1240px;
      margin: 0 auto;
      padding: 32px 24px 64px;
    }
    .hero {
      display: grid;
      grid-template-columns: minmax(0, 1.25fr) minmax(280px, 0.75fr);
      gap: 20px;
      align-items: stretch;
    }
    .panel {
      background: linear-gradient(180deg, rgba(15, 28, 40, 0.96) 0%, rgba(19, 36, 52, 0.98) 100%);
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 24px;
      box-shadow: 0 18px 44px rgba(0, 0, 0, 0.28);
    }
    .eyebrow {
      display: inline-flex;
      padding: 8px 12px;
      border-radius: 999px;
      background: rgba(102, 184, 255, 0.1);
      border: 1px solid rgba(102, 184, 255, 0.22);
      color: #a6d7ff;
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }
    h1, h2, h3, p { margin: 0; }
    h1 {
      font-size: clamp(2.4rem, 5vw, 4.3rem);
      line-height: 0.98;
      letter-spacing: -0.04em;
      margin-top: 18px;
    }
    .hero p {
      margin-top: 16px;
      color: var(--muted);
      line-height: 1.55;
      max-width: 62ch;
      font-size: 1.02rem;
    }
    .link-row, .workflow-list {
      display: grid;
      gap: 12px;
      margin-top: 18px;
    }
    .action-link, .workflow-item {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      border: 1px solid rgba(157, 177, 192, 0.16);
      background: rgba(255, 255, 255, 0.03);
      border-radius: 16px;
      padding: 14px 16px;
    }
    .action-link a, .doc-card a {
      color: var(--accent);
      text-decoration: none;
      font-weight: 600;
    }
    .stats {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-top: 28px;
    }
    .stat {
      border: 1px solid rgba(157, 177, 192, 0.16);
      border-radius: 16px;
      padding: 16px;
      background: rgba(255, 255, 255, 0.03);
    }
    .stat span {
      display: block;
      color: var(--muted);
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .stat strong {
      display: block;
      margin-top: 8px;
      font-size: 1.45rem;
      letter-spacing: -0.03em;
    }
    section + section {
      margin-top: 24px;
    }
    .section-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 14px;
    }
    .section-head p {
      color: var(--muted);
      max-width: 70ch;
      font-size: 0.95rem;
      line-height: 1.5;
      margin-top: 0;
    }
    .doc-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 14px;
    }
    .architecture-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
      gap: 14px;
    }
    .architecture-card {
      border: 1px solid rgba(157, 177, 192, 0.16);
      border-radius: 18px;
      padding: 18px;
      background: rgba(255, 255, 255, 0.03);
      display: grid;
      gap: 10px;
    }
    .architecture-card h3 {
      font-size: 1.05rem;
      line-height: 1.2;
    }
    .architecture-card p {
      color: var(--muted);
      line-height: 1.45;
      font-size: 0.92rem;
    }
    .changelog-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
      gap: 14px;
    }
    .changelog-card {
      border: 1px solid rgba(157, 177, 192, 0.16);
      border-radius: 18px;
      padding: 18px;
      background: rgba(255, 255, 255, 0.03);
      display: grid;
      gap: 12px;
    }
    .changelog-card h3 {
      font-size: 1.15rem;
      line-height: 1.2;
    }
    .changelog-group {
      display: grid;
      gap: 8px;
    }
    .changelog-group h4 {
      font-size: 0.9rem;
      letter-spacing: 0.02em;
      color: #b5dfff;
      text-transform: uppercase;
    }
    .changelog-group ul {
      margin: 0;
      padding-left: 18px;
      color: var(--muted);
      line-height: 1.5;
      font-size: 0.92rem;
    }
    .changelog-link {
      margin-top: 12px;
      display: inline-flex;
      color: var(--accent);
      text-decoration: none;
      font-weight: 600;
    }
    .screenshot-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 16px;
    }
    .screenshot-card {
      border: 1px solid rgba(157, 177, 192, 0.16);
      border-radius: 18px;
      padding: 16px;
      background: rgba(255, 255, 255, 0.03);
      display: grid;
      gap: 12px;
    }
    .screenshot-card img {
      width: 100%;
      height: auto;
      display: block;
      border-radius: 14px;
      border: 1px solid rgba(157, 177, 192, 0.14);
      background: #09131d;
    }
    .screenshot-card h3 {
      font-size: 1.1rem;
      line-height: 1.2;
    }
    .screenshot-card p {
      color: var(--muted);
      line-height: 1.45;
      font-size: 0.92rem;
    }
    .doc-card {
      border: 1px solid rgba(157, 177, 192, 0.16);
      border-radius: 18px;
      padding: 18px;
      background: rgba(255, 255, 255, 0.03);
      display: grid;
      gap: 10px;
    }
    .doc-tag {
      color: #9cefbf;
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      font-weight: 700;
    }
    .doc-card h3 {
      font-size: 1.15rem;
      line-height: 1.2;
    }
    .doc-card p {
      color: var(--muted);
      line-height: 1.45;
      font-size: 0.92rem;
    }
    .workflow-item strong {
      display: block;
      font-size: 1rem;
    }
    .workflow-item small {
      display: block;
      color: var(--muted);
      margin-top: 6px;
      line-height: 1.4;
      font-size: 0.85rem;
    }
    .pill {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 88px;
      height: 28px;
      border-radius: 999px;
      padding: 0 12px;
      font-size: 0.72rem;
      font-weight: 800;
      letter-spacing: 0.05em;
      text-transform: uppercase;
      border: 1px solid rgba(157, 177, 192, 0.16);
      background: rgba(43, 214, 123, 0.12);
      color: #9cefbf;
    }
    .footer {
      margin-top: 28px;
      color: var(--muted);
      font-size: 0.88rem;
      line-height: 1.5;
    }
    @media (max-width: 900px) {
      .hero {
        grid-template-columns: 1fr;
      }
      .stats {
        grid-template-columns: 1fr;
      }
    }
    """

    workflows_html = """
      <div class="workflow-item">
        <div>
          <strong>CI workflow</strong>
          <small>Runs tests on every push and pull request so the repo rejects broken automation before it lands.</small>
        </div>
        <span class="pill">Active</span>
      </div>
      <div class="workflow-item">
        <div>
          <strong>Pages deploy workflow</strong>
          <small>Builds the static docs site and deploys it through GitHub Pages on pushes to <code>main</code> or manual dispatch.</small>
        </div>
        <span class="pill">Active</span>
      </div>
    """

    repo_url = f"https://github.com/{repo_slug}"
    pages_url = f"https://{repo_slug.split('/')[0].lower()}.github.io/{repo_slug.split('/')[1]}/"

    screenshot_cards: list[str] = []
    for relative_path, title, description in SCREENSHOT_ORDER:
        absolute_path = root / relative_path
        if not absolute_path.exists():
            continue
        destination_name = absolute_path.name
        shutil.copy2(absolute_path, screenshots_dir / destination_name)
        screenshot_cards.append(
            f"""
            <article class="screenshot-card">
              <img src="assets/screenshots/{html.escape(destination_name)}" alt="{html.escape(title)}" />
              <h3>{html.escape(title)}</h3>
              <p>{html.escape(description)}</p>
            </article>
            """
        )

    changelog_sections = extract_changelog_sections(changelog, limit=2)
    changelog_cards: list[str] = []
    for title, groups in changelog_sections:
        group_markup = []
        for group_title, items in groups:
            item_list = "".join(f"<li>{html.escape(item)}</li>" for item in items)
            group_markup.append(
                f"""
                <div class="changelog-group">
                  <h4>{html.escape(group_title)}</h4>
                  <ul>{item_list}</ul>
                </div>
                """
            )
        changelog_cards.append(
            f"""
            <article class="changelog-card">
              <h3>{html.escape(title)}</h3>
              {''.join(group_markup)}
            </article>
            """
        )

    html_body = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{html.escape(project_title)} | GitHub Pages</title>
    <meta name="description" content="GitHub-ready documentation and automation hub for {html.escape(project_title)}." />
    <link rel="stylesheet" href="assets/site.css" />
  </head>
  <body>
    <main class="wrap">
      <section class="hero">
        <div class="panel">
          <span class="eyebrow">GitHub Automation</span>
          <h1>{html.escape(project_title)}</h1>
          <p>{html.escape(project_intro)}</p>
          <div class="stats">
            <div class="stat"><span>Deployment</span><strong>Pages</strong></div>
            <div class="stat"><span>Automation</span><strong>CI + Publish</strong></div>
            <div class="stat"><span>Owner</span><strong>{html.escape(repo_slug.split('/')[0])}</strong></div>
          </div>
        </div>
        <div class="panel">
          <div class="section-head">
            <div>
              <h2>Repository Links</h2>
              <p>Fast paths into the GitHub repo, the Pages deployment target, and the setup guide for the automation path.</p>
            </div>
          </div>
          <div class="link-row">
            <div class="action-link"><span>GitHub repository</span><a href="{html.escape(repo_url)}">Open repo</a></div>
            <div class="action-link"><span>GitHub Pages target</span><a href="{html.escape(pages_url)}">Open site</a></div>
            <div class="action-link"><span>Automation setup guide</span><a href="{html.escape(repo_doc_url(repo_slug, Path('docs/setup/github-automation-and-pages.md')))}">Read guide</a></div>
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="section-head">
          <div>
            <h2>What The Automation Covers</h2>
            <p>The repository now includes the GitHub-side baseline for automated quality checks plus static documentation deployment.</p>
          </div>
        </div>
        <div class="workflow-list">
          {workflows_html}
        </div>
      </section>

      <section class="panel">
        <div class="section-head">
          <div>
            <h2>Architecture Snapshot</h2>
            <p>The platform is split into a live operator layer, a trading/runtime layer, a broker/reporting layer, and a GitHub automation layer so the project stays understandable while it grows.</p>
          </div>
        </div>
        <div class="architecture-grid">
          <article class="architecture-card">
            <h3>Operator Layer</h3>
            <p>Local web GUI, manual overrides, session controls, warnings, order tape, and market watch.</p>
          </article>
          <article class="architecture-card">
            <h3>Runtime + Trading</h3>
            <p>Cycle timing, crypto wakeups, strategy logic, risk approval, duplicate-order suppression, and execution orchestration.</p>
          </article>
          <article class="architecture-card">
            <h3>Broker + Reports</h3>
            <p>Alpaca Paper integration, runtime state, dashboard snapshots, operator HTML, and session reports.</p>
          </article>
          <article class="architecture-card">
            <h3>GitHub Automation</h3>
            <p>CI, Pages publishing, changelog-backed public docs, and repository governance documents.</p>
          </article>
        </div>
        <a class="changelog-link" href="{html.escape(repo_doc_url(repo_slug, Path('docs/architecture/system-overview.md')))}" target="_blank" rel="noreferrer">Open architecture overview on GitHub</a>
      </section>

      <section class="panel">
        <div class="section-head">
          <div>
            <h2>Project Documentation</h2>
            <p>These documents stay in the repository, while this site gives the project a clean public landing page and a stable entry point.</p>
          </div>
        </div>
        <div class="doc-grid">
          {''.join(doc_cards)}
        </div>
      </section>

      <section class="panel">
        <div class="section-head">
          <div>
            <h2>Operator Screenshots</h2>
            <p>A quick visual tour of the operator experience, including the live dashboard, market overview cards, and the long-run monitor.</p>
          </div>
        </div>
        <div class="screenshot-grid">
          {''.join(screenshot_cards)}
        </div>
      </section>

      <section class="panel">
        <div class="section-head">
          <div>
            <h2>Project Changelog</h2>
            <p>The public site mirrors the repository changelog so recent automation, dashboard, and documentation work stays visible without digging through commits.</p>
          </div>
        </div>
        <div class="changelog-grid">
          {''.join(changelog_cards)}
        </div>
        <a class="changelog-link" href="{html.escape(repo_doc_url(repo_slug, Path('CHANGELOG.md')))}" target="_blank" rel="noreferrer">Open full changelog on GitHub</a>
      </section>

      <p class="footer">
        Generated by <code>scripts/build_github_pages.py</code>. If you rename the repository later, update the workflow input or the repository slug and redeploy.
      </p>
    </main>
  </body>
</html>
"""

    (assets_dir / "site.css").write_text(css.strip() + "\n", encoding="utf-8")
    (output_dir / "index.html").write_text(html_body, encoding="utf-8")
    (output_dir / "404.html").write_text(html_body, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the static GitHub Pages site for Autotrade.")
    parser.add_argument("--output", default="site", help="Output directory for the static site.")
    parser.add_argument("--repo", default=os.getenv("GITHUB_REPOSITORY", "Shadow2442/Autotrade"), help="GitHub repo slug, e.g. owner/repo.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    output_dir = root / args.output
    build_index(root=root, output_dir=output_dir, repo_slug=args.repo)
    print(f"Built GitHub Pages site in {output_dir}")


if __name__ == "__main__":
    main()
