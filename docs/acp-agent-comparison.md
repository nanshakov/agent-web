# ACP agents for Agent Web

## What Agent Web needs

The integration needs an ACP subprocess with session create/load/resume, prompt
updates, cancellation, permission requests, project-scoped filesystem access,
and a selectable local OpenAI-compatible provider.

## Cline

Cline adds a product layer beyond the common ACP boundary: explicit Plan/Act
modes, checkpoints and diff review, browser tooling, project rules/skills,
teams, scheduling, and channel integrations. Its README also explicitly lists
LM Studio and any OpenAI-compatible API as providers.

Source: <https://github.com/cline/cline>

Current drawback: the Cline CLI ACP server has an account gate even when a
local OpenAI-compatible provider is configured. See
[#11662](https://github.com/cline/cline/issues/11662) and
[#12120](https://github.com/cline/cline/issues/12120).

## OpenCode

OpenCode documents `opencode acp` as an ACP stdio subprocess. Its ACP page
states that the same terminal features are supported through ACP: built-in
file and terminal tools, custom tools and commands, MCP, `AGENTS.md`, custom
formatters/linters, agents, and the permissions system. It notes only that
`/undo` and `/redo` are not currently available via ACP.

Source: <https://opencode.ai/docs/acp>

This covers the critical Agent Web requirements without Cline's ACP account
gate. Cline-specific Plan/Act and checkpoint UX are not protocol requirements;
Agent Web can expose its own project access and approval controls.

## Goose

Goose is an Apache-2.0 open-source Rust agent with a CLI, desktop application,
and embedding API. Its public source contains ACP handlers for new/load/list
and fork sessions, prompts, provider selection, tool calls, permissions, and
local inference. That makes it a credible ACP backend, though it needs a real
Windows + LM Studio compatibility spike before selection.

Sources:

- <https://github.com/aaif-goose/goose>
- <https://github.com/aaif-goose/goose/tree/main/crates/goose/src/acp/server>

## Recommendation

For a no-account local-LM MVP, test OpenCode first. Its documented ACP support
matches the required transport features and has no known equivalent account
gate. Keep Cline as a selectable backend once its ACP account gate is fixed or
if a Cline account is acceptable. Evaluate Goose next if a more general
workflow agent is desired.
