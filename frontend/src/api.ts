export interface AgentSettings {
  agent: string;
  model: string | null;
  reasoning: string | null;
  sandbox: string;
}
export interface Project extends AgentSettings {
  id: string;
  name: string;
  path: string;
}
export interface Session extends AgentSettings {
  id: string;
  title: string | null;
  source: string;
  created_at: string;
  last_activity_at: string;
}
export interface Message {
  activities?: Activity[];
  role: string;
  content: string;
  rendered_content?: string;
  created_at?: string;
  agent?: string;
  model?: string;
  turn_id?: string;
  status?: string;
  attachments?: { name: string; kind: string }[];
}
export interface TurnEvent {
  activities?: Activity[];
  type: string;
  turn_id: string;
  status: string;
  content: string;
  rendered_content?: string;
}
export interface Activity {
  id: string;
  kind: string;
  label: string;
  status: "running" | "completed" | "failed" | "interrupted";
}
export interface Agent {
  ready: boolean;
  detail: string;
  models: { id: string; name: string; reasoning_efforts: string[] }[];
  usage?: {
    available: boolean;
    local?: boolean;
    message?: string;
    plan_type?: string;
    primary?: UsageWindow;
    secondary?: UsageWindow;
    credits?: { balance?: string; unlimited?: boolean };
  };
}
interface UsageWindow {
  remaining_percent: number;
  window_duration_mins: number;
  resets_at?: number;
}
export async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch("/api/v1" + path, {
    ...options,
    headers:
      options.body instanceof FormData
        ? options.headers
        : { "Content-Type": "application/json", ...options.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(
      body?.detail?.message || `Request failed (${response.status})`,
    );
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
export const json = (method: string, body: unknown) => ({
  method,
  body: JSON.stringify(body),
});
