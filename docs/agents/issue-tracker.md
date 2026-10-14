# Issue tracker: GitHub Issues

Issues and PRDs for this repo live as GitHub Issues in the `Sharim1/scene-sentry` repository. Use the `gh` CLI for all operations.

## Conventions

- **Create an issue**: `gh issue create --title "..." --body "..."` (Markdown body).
- **Read an issue**: `gh issue view <number>`.
- **List issues**: `gh issue list` with filters like `--state`, `--label`, `--assignee`.
- **Comment on an issue**: `gh issue comment <number> --body "..."`.
- **Apply labels**: `gh issue edit <number> --add-label "label-name"`.
- **Close an issue**: `gh issue close <number>` (add `--reason "not planned"` to cancel).

## When a skill says "publish to the issue tracker"

Create a GitHub issue with `gh issue create`.

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number>`.
