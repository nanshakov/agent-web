import { useEffect, useRef, useState } from "react";
import { Button, IconButton } from "@radix-ui/themes";
import {
  ArrowUpIcon,
  PaperPlaneIcon,
  SpeakerLoudIcon,
} from "@radix-ui/react-icons";
import { useNavigate } from "react-router-dom";
import {
  json,
  request,
  type Project,
  type Session,
  type Agent,
  type AgentSettings,
} from "./api";
import { SettingsFields } from "./Settings";
import { useChat } from "./useChat";
import { TurnActivity } from "./Activity";

export function Chat({
  project,
  session,
  agents,
  onChanged,
}: {
  project: Project;
  session?: Session;
  agents: Record<string, Agent>;
  onChanged: () => Promise<void>;
}) {
  const navigate = useNavigate(),
    chat = useChat(session?.id);
  const initial: AgentSettings = {
    agent: session?.agent || project.agent,
    model: session?.model ?? project.model,
    reasoning: session?.reasoning ?? project.reasoning,
    sandbox: session?.sandbox || project.sandbox,
  };
  const [settings, setSettings] = useState(initial),
    applied = useRef(initial);
  const [prompt, setPrompt] = useState(""),
    [files, setFiles] = useState<File[]>([]),
    [sending, setSending] = useState(false),
    [error, setError] = useState("");
  const [voiceStatus, setVoiceStatus] = useState(""),
    [listening, setListening] = useState(false);
  const recognition = useRef<any>(null),
    messagesRef = useRef<HTMLDivElement>(null),
    follow = useRef(true),
    fileRef = useRef<HTMLInputElement>(null);
  const createdId = useRef<string | undefined>(undefined);
  const pendingRequest = useRef<{ signature: string; id: string } | null>(null);
  const [optimistic, setOptimistic] = useState<string | null>(null);
  const busy = sending || chat.running;
  useEffect(() => {
    if (follow.current && messagesRef.current)
      messagesRef.current.scrollTop = messagesRef.current.scrollHeight;
  }, [chat.messages, optimistic]);
  useEffect(() => {
    const Recognition =
      (window as any).SpeechRecognition ||
      (window as any).webkitSpeechRecognition;
    if (!Recognition) return;
    const r = new Recognition();
    recognition.current = r;
    r.continuous = true;
    r.interimResults = true;
    r.lang = navigator.language;
    r.onstart = () => setListening(true);
    r.onend = () => setListening(false);
    r.onerror = (e: any) => setVoiceStatus(`Voice input: ${e.error}`);
    r.onresult = (e: any) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        if (e.results[i].isFinal)
          setPrompt(
            (p) => (p ? p + " " : "") + e.results[i][0].transcript.trim(),
          );
        else interim += e.results[i][0].transcript;
      }
      setVoiceStatus(interim || "Review the text before sending.");
    };
    return () => {
      r.onend = null;
      r.onresult = null;
      r.onerror = null;
      r.abort();
    };
  }, []);
  async function send(e: React.FormEvent) {
    e.preventDefault();
    if (busy || (!prompt.trim() && !files.length)) return;
    setSending(true);
    setError("");
    follow.current = true;
    let id = session?.id || createdId.current;
    try {
      if (!id) {
        const created = await request<{ id: string }>(
          `/projects/${project.id}/sessions`,
          json("POST", { ...settings, approval_policy: "auto" }),
        );
        id = created.id;
        createdId.current = id;
      } else if (JSON.stringify(settings) !== JSON.stringify(applied.current)) {
        const transfer_context =
          settings.agent !== applied.current.agent
            ? window.confirm(
                `Transfer this chat's context from ${applied.current.agent} to ${settings.agent}? Cancel switches without transferring context.`,
              )
            : null;
        await request(
          `/sessions/${id}/switch`,
          json("POST", {
            ...settings,
            approval_policy: "auto",
            transfer_context,
          }),
        );
        applied.current = settings;
      }
      const signature = JSON.stringify([
        id,
        prompt,
        files.map((f) => [f.name, f.size, f.lastModified]),
      ]);
      if (pendingRequest.current?.signature !== signature)
        pendingRequest.current = {
          signature,
          id:
            crypto.randomUUID?.() ||
            `${Date.now()}-${Math.random().toString(36).slice(2)}`,
        };
      const data = new FormData();
      data.append("prompt", prompt);
      data.append("client_request_id", pendingRequest.current.id);
      files.forEach((f) => data.append("files", f));
      setOptimistic(prompt || files.map((f) => f.name).join(", "));
      await request(`/sessions/${id}/turns`, { method: "POST", body: data });
      pendingRequest.current = null;
      setPrompt("");
      setFiles([]);
      if (fileRef.current) fileRef.current.value = "";
      if (!session) {
        await onChanged();
        navigate(`/projects/${project.id}/chats/${id}`, { replace: true });
      } else {
        await chat.refresh();
        await onChanged();
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSending(false);
      setOptimistic(null);
    }
  }
  return (
    <section id="chat" className="chat-workspace">
      <div className="chat-subhead">
        <span
          className={chat.connection === "Live" ? "live-state" : ""}
          role="status"
        >
          {chat.running ? "Agent is working" : chat.connection}
        </span>
        {session && (
          <a
            id="export-chat"
            className="export"
            href={`/api/v1/sessions/${session.id}/export`}
          >
            Export chat
          </a>
        )}
      </div>
      <div
        id="messages"
        ref={messagesRef}
        onScroll={() => {
          const m = messagesRef.current!;
          follow.current = m.scrollHeight - m.scrollTop - m.clientHeight < 90;
        }}
      >
        {!chat.messages.length && !session && (
          <div className="empty-chat">
            <PaperPlaneIcon width="28" height="28" />
            <h2>What are we working on?</h2>
            <p>
              Your agent has access to <strong>{project.name}</strong>.<br />
              Choose your settings and send the first instruction.
            </p>
          </div>
        )}
        {!chat.messages.length && session && (
          <p className="empty-note">
            {chat.loading
              ? "Loading chat history…"
              : chat.error
                ? "History is unavailable."
                : "No messages yet."}
          </p>
        )}
        {chat.messages.map((m, i) => (
          <article
            key={`${m.turn_id || i}-${m.role}-${i}`}
            className={`message ${m.role === "user" ? "you" : "markdown"} ${m.status === "failed" ? "failed" : ""}`}
            data-turn-id={m.turn_id}
          >
            <div className="message-author">
              {m.role === "user" ? "You" : m.agent || settings.agent}
              {m.model && m.role !== "user" && <span>{m.model}</span>}
            </div>
            {m.role === "assistant" && m.rendered_content ? (
              <div dangerouslySetInnerHTML={{ __html: m.rendered_content }} />
            ) : (
              <div className="plain-text">{m.content}</div>
            )}
            {m.attachments?.length ? (
              <div className="attachments">
                {m.attachments.map((f, j) => (
                  <span key={j}>
                    {f.kind === "image" ? "Image" : "File"} · {f.name}
                  </span>
                ))}
              </div>
            ) : null}
            {m.role === "assistant" && (
              <TurnActivity
                items={m.activities}
                running={m.status === "running"}
              />
            )}
            {m.created_at && (
              <time dateTime={m.created_at}>
                {new Date(m.created_at).toLocaleString()}
              </time>
            )}
          </article>
        ))}
        {optimistic &&
          !chat.messages.some(
            (m) => m.role === "user" && m.content === optimistic,
          ) && (
            <article className="message you">
              <div className="message-author">You · Sending</div>
              {optimistic}
            </article>
          )}
      </div>
      {(error || chat.error) && (
        <p role="alert" className="error-banner">
          {error || chat.error}
        </p>
      )}
      {settings.agent === "cline" ? (
        <p className="empty-note">Cline history is read-only.</p>
      ) : (
        <form id="turn-form" className="composer" onSubmit={send}>
          <div className="composer-box">
            <label className="sr-only" htmlFor="prompt">
              Message
            </label>
            <textarea
              id="prompt"
              name="prompt"
              placeholder="Message your agent…"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                  e.preventDefault();
                  e.currentTarget.form?.requestSubmit();
                }
              }}
            />
            <div className="composer-actions">
              <label className="attach">
                <input
                  ref={fileRef}
                  name="files"
                  type="file"
                  multiple
                  onChange={(e) => setFiles(Array.from(e.target.files || []))}
                />
                Attach files
              </label>
              <IconButton
                type="button"
                variant="ghost"
                aria-label={
                  listening ? "Stop voice input" : "Start voice input"
                }
                aria-pressed={listening}
                disabled={
                  !(
                    (window as any).SpeechRecognition ||
                    (window as any).webkitSpeechRecognition
                  )
                }
                onClick={() => {
                  try {
                    listening
                      ? recognition.current.stop()
                      : recognition.current.start();
                  } catch {
                    setVoiceStatus("Voice input could not start.");
                  }
                }}
              >
                <SpeakerLoudIcon />
              </IconButton>
              <span className="composer-hint">
                {busy ? "Agent is working…" : "Ctrl / ⌘ + Enter"}
              </span>
              <Button
                type="submit"
                disabled={busy || (!prompt.trim() && !files.length)}
              >
                <ArrowUpIcon />
                Send
              </Button>
            </div>
            {files.length > 0 && (
              <div className="attachments">
                {files.map((f, i) => (
                  <button
                    type="button"
                    key={i}
                    onClick={() =>
                      setFiles((old) => old.filter((_, j) => i !== j))
                    }
                  >
                    {f.name} ×
                  </button>
                ))}
              </div>
            )}
            {voiceStatus && <p role="status">{voiceStatus}</p>}
          </div>
          <details id="chat-settings">
            <summary>
              {settings.agent} · {settings.model || "Default model"} · Chat
              settings
            </summary>
            <SettingsFields
              value={settings}
              onChange={setSettings}
              agents={agents}
              disabled={busy}
            />
          </details>
        </form>
      )}
    </section>
  );
}
