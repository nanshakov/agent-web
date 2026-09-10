import { Button, Dialog } from "@radix-ui/themes";
import { useState } from "react";
import { json, request, type Agent, type AgentSettings } from "./api";
export function SettingsFields({
  value,
  onChange,
  agents,
  disabled = false,
  globalDefaults = false,
}: {
  value: AgentSettings;
  onChange: (v: AgentSettings) => void;
  agents: Record<string, Agent>;
  disabled?: boolean;
  globalDefaults?: boolean;
}) {
  const models = agents[value.agent]?.models || [];
  return (
    <fieldset disabled={disabled} className="settings-fields">
      {!globalDefaults && (
        <label>
          Agent
          <select
            name="agent"
            value={value.agent}
            onChange={(e) =>
              onChange({
                ...value,
                agent: e.target.value,
                model: null,
                reasoning: null,
              })
            }
          >
            {Object.entries(agents).map(([id, a]) => (
              <option key={id} value={id} disabled={!a.ready}>
                {id === "opencode" ? "OpenCode · LM Studio" : id}
              </option>
            ))}
            {value.agent === "cline" && <option value="cline">Cline</option>}
          </select>
        </label>
      )}
      <label>
        Model
        <select
          name="model"
          value={value.model || ""}
          onChange={(e) =>
            onChange({
              ...value,
              model: e.target.value || null,
              reasoning: null,
            })
          }
        >
          <option value="">Agent default</option>
          {models.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        Reasoning
        <select
          name="reasoning"
          value={value.reasoning || ""}
          onChange={(e) =>
            onChange({ ...value, reasoning: e.target.value || null })
          }
        >
          <option value="">Model default</option>
          {(
            models.find((m) => m.id === value.model)?.reasoning_efforts || []
          ).map((r) => (
            <option key={r}>{r}</option>
          ))}
        </select>
      </label>
      {!globalDefaults && (
        <label>
          Project access
          <select
            name="sandbox"
            value={value.sandbox}
            onChange={(e) => onChange({ ...value, sandbox: e.target.value })}
          >
            <option value="workspace_write">Write in project</option>
            <option value="read_only">Read only</option>
          </select>
        </label>
      )}
    </fieldset>
  );
}
export function Personalization({ agents }: { agents: Record<string, Agent> }) {
  const [open, setOpen] = useState(false),
    [value, setValue] = useState<AgentSettings>({
      agent: "codex",
      model: null,
      reasoning: null,
      sandbox: "workspace_write",
    }),
    [instructions, setInstructions] = useState(""),
    [error, setError] = useState("");
  async function load() {
    try {
      const s = await request<{
        model: string | null;
        reasoning: string | null;
        custom_instructions: string;
      }>("/settings");
      setValue((v) => ({ ...v, ...s }));
      setInstructions(s.custom_instructions);
      setError("");
      setOpen(true);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  return (
    <>
      <Button variant="ghost" onClick={load}>
        Personalization
      </Button>
      {!open && error && <p role="alert">{error}</p>}
      <Dialog.Root open={open} onOpenChange={setOpen}>
        <Dialog.Content maxWidth="540px">
          <Dialog.Title>Personalization</Dialog.Title>
          <Dialog.Description>
            Defaults for new chats. Project settings take precedence.
          </Dialog.Description>
          <form
            id="settings-form"
            onSubmit={async (e) => {
              e.preventDefault();
              try {
                await request(
                  "/settings",
                  json("PUT", {
                    model: value.model,
                    reasoning: value.reasoning,
                    custom_instructions: instructions,
                  }),
                );
                setOpen(false);
              } catch (e) {
                setError((e as Error).message);
              }
            }}
          >
            <SettingsFields
              value={value}
              onChange={setValue}
              agents={{ codex: agents.codex }}
              globalDefaults
            />
            <label>
              Custom instructions
              <textarea
                value={instructions}
                onChange={(e) => setInstructions(e.target.value)}
                maxLength={20000}
              />
            </label>
            {error && <p role="alert">{error}</p>}
            <div className="dialog-actions">
              <Dialog.Close>
                <Button type="button" variant="soft">
                  Cancel
                </Button>
              </Dialog.Close>
              <Button>Save settings</Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Root>
    </>
  );
}
