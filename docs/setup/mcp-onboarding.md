# MCP Onboarding Guide

## Purpose

This guide documents how optional MCP-based tooling should be added to this project in a reusable and team-friendly way.

It is intentionally separate from the core `Alpaca Paper` implementation because MCP-based chart or research tools are optional enhancements, not execution dependencies.

## Design Goal

If we later add an MCP server for:

- TradingView research
- session brief generation
- chart screenshots
- replay and review workflows

then the setup should be:

- reproducible
- project-scoped when possible
- easy to verify
- safe for collaboration

## Recommended Approach

Prefer this order of operations:

1. install or verify the MCP server locally
2. register it with `claude mcp add` or a project `.mcp.json`
3. keep machine-specific values in environment variables
4. verify the server starts correctly
5. document any Windows-specific command wrappers

## Why Project Scope Matters

Project-scoped MCP configuration is better for shared work because:

- it documents intended tools in the repository
- it reduces hidden setup living only in a personal profile
- it makes onboarding easier for future collaborators

Use user-level configuration only for:

- personal experiments
- private credentials
- tools that should never be committed to the project context

## Suggested Workflow

### Option A: Project-Scoped Configuration

Use a repo-level `.mcp.json` when:

- the server is optional but shared
- the command is stable enough to document
- teammates may want the same workflow

The example file in this repository is:

- `.mcp.example.json`

Copy it to `.mcp.json` only if and when the project is ready to enable that integration locally.

### Option B: User-Scoped Configuration

Use a personal Claude configuration when:

- the setup is temporary
- the tool contains sensitive local paths
- the tool is not intended to be shared with the project

## Windows Notes

Anthropic's Claude Code documentation notes that native Windows setups often need `cmd /c` for `npx`-based MCP server commands.

That means a project-scoped command may look different on Windows than on macOS or Linux, even when the logical server setup is the same.

## Verification Checklist

Before relying on an MCP integration, verify:

- the server command launches successfully
- required environment variables are present
- the tool is visible to the client
- at least one basic command works
- failure behavior is understandable when the tool is unavailable

## What We Should Reuse From The Claude One-Shot Pattern

These parts are worth copying into our own future setup flow:

- a single onboarding sequence
- a template config file
- a post-setup verification step
- explicit instructions for user customization

These parts should be improved:

- prefer project-scoped config over hidden global edits
- avoid storing secrets in config files
- keep optional integrations clearly marked as optional

## Recommended Policy For This Repository

- the Alpaca execution system must not depend on MCP
- MCP can be added later for research and operator assistance
- any future MCP integration should ship with:
  - a setup guide
  - an example config
  - a verification step
  - a note describing whether it is optional or required

## References

- Anthropic: Connect Claude Code to tools via MCP - https://docs.anthropic.com/en/docs/claude-code/mcp
- Anthropic: Claude Code settings - https://docs.anthropic.com/en/docs/claude-code/settings
- Anthropic: MCP in the SDK - https://docs.anthropic.com/en/docs/claude-code/sdk/sdk-mcp
- GitHub: tradingview-mcp-jackson - https://github.com/LewisWJackson/tradingview-mcp-jackson
