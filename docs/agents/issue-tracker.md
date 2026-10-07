# Issue tracker: Linear

Issues and PRDs for this repo live as Linear issues under the **Scene Sentry** team. Use the Linear MCP server (`plugin-linear-linear`) for all operations.

## Conventions

- **Create an issue**: Use `save_issue` with `team: "Scene Sentry"`, `title`, and `description` (Markdown).
- **Read an issue**: Use `get_issue` with the issue identifier (e.g. `SCE-123`).
- **List issues**: Use `list_issues` with filters like `team`, `state`, `label`, `assignee`.
- **Comment on an issue**: Use `save_comment` with `issueId` and `body` (Markdown).
- **Apply labels**: Use `save_issue` with `id` and `labels: ["label-name"]`.
- **Close an issue**: Use `save_issue` with `id` and `state: "Done"` or `state: "Cancelled"`.

## When a skill says "publish to the issue tracker"

Create a Linear issue via `save_issue` on the Scene Sentry team.

## When a skill says "fetch the relevant ticket"

Use `get_issue` with the issue identifier.
