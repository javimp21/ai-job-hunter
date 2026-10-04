# Claude Code

Project instructions live in AGENTS.md (shared with other coding agents):

@AGENTS.md

Notes for Claude Code sessions:

- Private data is never in Git: `.env`, `*.local.json`, `private/` and `data/local/` exist only on the user's machine. Cloud sessions work without them (offline tests use fixtures).
- Work on a feature branch and push it; never push to `main` unless the user asks.
- Avoid writing regexes through Python/heredoc strings (`\b` becomes a backspace byte); use the editor and scan changed files for control bytes.
