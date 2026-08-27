# Cline ACP with a local OpenAI-compatible model

Checked 27 August 2026 against Cline CLI 3.0.60, Cline's public issue tracker,
and a local LM Studio server.

## Result

LM Studio does not require a cloud account. Its OpenAI-compatible endpoint at
`http://127.0.0.1:1234/v1` exposed `qwen/qwen3.8-27b`, and Cline CLI accepted
an `openai-compatible` provider configuration for that model.

However, Cline ACP currently has a separate account gate. `cline --acp`
successfully responds to `initialize`, but rejects `session/new` with
`Authentication required: Call authenticate before starting a session` even
after the local provider is configured.

## Primary-source evidence

- [Cline issue #11662](https://github.com/cline/cline/issues/11662) reproduces
  the same ACP authentication gate with an already configured OpenRouter
  provider.
- [Cline issue #12120](https://github.com/cline/cline/issues/12120) reports
  the same behaviour with a user's own OpenAI-compatible server; the normal
  CLI and VS Code extension work, while ACP demands a Cline-site login.
- Both issues are linked to Cline's internal tracked issues, without a public
  released workaround or fix in the discussion.

## Decision

Do not parse Cline's JSON output as a replacement for ACP. Keep ACP as the
planned integration boundary and wait for an ACP build that permits a
configured local provider without account sign-in. A Cline account may work
around the gate, but it is not technically required by LM Studio and should
not be presented as such.
