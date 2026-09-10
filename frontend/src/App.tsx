import { useCallback, useEffect, useState } from "react";
import { Link, useLocation, useMatch, useNavigate } from "react-router-dom";
import { Button, Dialog, IconButton } from "@radix-ui/themes";
import {
  HamburgerMenuIcon,
  PlusIcon,
  ChatBubbleIcon,
  TrashIcon,
  Cross2Icon,
} from "@radix-ui/react-icons";
import {
  request,
  json,
  type Project,
  type Session,
  type Agent,
  type AgentSettings,
} from "./api";
import { Chat } from "./Chat";
import { Personalization, SettingsFields } from "./Settings";

export function App() {
  const [projects, setProjects] = useState<Project[]>([]),
    [sessions, setSessions] = useState<Record<string, Session[]>>({}),
    [agents, setAgents] = useState<Record<string, Agent>>({});
  const [loaded, setLoaded] = useState(false),
    [error, setError] = useState(""),
    [menu, setMenu] = useState(false),
    [query, setQuery] = useState("");
  const [defaults, setDefaults] = useState<Project | null>(null),
    [add, setAdd] = useState(false),
    [formError, setFormError] = useState("");
  const [health, setHealth] = useState("Checking agents"),
    [update, setUpdate] = useState("");
  const [lanMode, setLanMode] = useState(false);
  const match = useMatch("/projects/:projectId/chats/:sessionId"),
    projectMatch = useMatch("/projects/:projectId");
  const projectId = match?.params.projectId || projectMatch?.params.projectId,
    sessionId = match?.params.sessionId;
  const navigate = useNavigate(),
    location = useLocation();
  const refresh = useCallback(async () => {
    const ps = await request<Project[]>("/projects");
    const entries = await Promise.all(
      ps.map(
        async (p) =>
          [
            p.id,
            await request<Session[]>(`/projects/${p.id}/sessions`),
          ] as const,
      ),
    );
    setProjects(ps);
    setSessions(Object.fromEntries(entries));
    setLoaded(true);
  }, []);
  useEffect(() => {
    void refresh().catch((e) => {
      setError(e.message);
    });
    let live = true;
    const status = async () => {
      try {
        const [a, h, u] = await Promise.all([
          request<Record<string, Agent>>("/agents"),
          request<{ status: string; lan_mode?: boolean }>("/health"),
          request<{ state: string; available_commit?: string }>("/update"),
        ]);
        if (live) {
          setAgents(a);
          setLanMode(!!h.lan_mode);
          setHealth(
            h.status === "ready" ? "Agents ready" : "No agent is ready",
          );
          setUpdate(u.state === "available" ? "Update available" : "");
        }
      } catch (e) {
        if (live) setHealth((e as Error).message);
      }
    };
    void status();
    const timer = setInterval(() => {
      void refresh().catch((e) => setError(e.message));
      void status();
    }, 30000);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [refresh]);
  useEffect(() => setMenu(false), [location.pathname]);
  const project = projects.find((p) => p.id === projectId),
    session = sessions[projectId || ""]?.find((s) => s.id === sessionId);
  useEffect(() => {
    if (!loaded) return;
    if (
      (projectId && !project) ||
      (sessionId && sessionId !== "new" && !session)
    ) {
      setError(
        "This project or chat is no longer available. Choose another conversation.",
      );
      navigate("/", { replace: true });
    } else if (location.pathname !== "/" && !projectId) {
      setError("This page is not available. Choose a project.");
      navigate("/", { replace: true });
    }
  }, [
    loaded,
    projectId,
    sessionId,
    project,
    session,
    navigate,
    location.pathname,
  ]);
  const usage = agents[session?.agent || project?.agent || "codex"]?.usage;
  async function remove(s: Session, p: Project) {
    if (
      !confirm(
        `Delete “${s.title || "Untitled chat"}”? Native agent history will be preserved.`,
      )
    )
      return;
    try {
      await request(`/sessions/${s.id}`, { method: "DELETE" });
      if (s.id === sessionId) navigate(`/projects/${p.id}`);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }
  const nav = (
    <>
      <div className="nav-brand">
        <span className="brand-mark">A</span>
        <div>
          <strong>Agent Web</strong>
          <small>Local AI workspace</small>
        </div>
      </div>
      <div className="nav-search">
        <label className="sr-only" htmlFor="search">
          Find a project or chat
        </label>
        <input
          id="search"
          placeholder="Find a project or chat"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      <nav
        aria-label="Projects and chats"
        onClick={(e) => {
          if ((e.target as HTMLElement).closest("a")) setMenu(false);
        }}
      >
        {projects.map((p) => {
          const chats = (sessions[p.id] || []).filter((s) =>
            `${p.name} ${s.title || ""}`
              .toLowerCase()
              .includes(query.toLowerCase()),
          );
          if (
            query &&
            !chats.length &&
            !p.name.toLowerCase().includes(query.toLowerCase())
          )
            return null;
          return (
            <section className="nav-project" key={p.id}>
              <div className="nav-project-heading">
                <Link to={`/projects/${p.id}`}>{p.name}</Link>
                <IconButton
                  variant="ghost"
                  aria-label={`New chat in ${p.name}`}
                  onClick={() => navigate(`/projects/${p.id}/chats/new`)}
                >
                  <PlusIcon />
                </IconButton>
              </div>
              {chats.map((s) => (
                <div
                  className={`nav-chat ${s.id === sessionId ? "selected" : ""}`}
                  key={s.id}
                >
                  <Link
                    to={`/projects/${p.id}/chats/${s.id}`}
                    aria-current={s.id === sessionId ? "page" : undefined}
                  >
                    <ChatBubbleIcon />
                    <span>{s.title || "Untitled chat"}</span>
                  </Link>
                  <IconButton
                    className="delete-chat"
                    variant="ghost"
                    color="gray"
                    aria-label={`Delete ${s.title || "Untitled chat"}`}
                    onClick={() => void remove(s, p)}
                  >
                    <TrashIcon />
                  </IconButton>
                </div>
              ))}
              {!chats.length && (
                <small className="nav-empty">No conversations yet</small>
              )}
              <button
                className="text-button project-defaults"
                onClick={() => {
                  setFormError("");
                  setDefaults(p);
                }}
              >
                Project settings
              </button>
            </section>
          );
        })}
        {loaded && !projects.length && <p>No projects configured.</p>}
      </nav>
      <footer className="nav-footer">
        {lanMode && (
          <small>
            LAN mode: devices on this network can control configured projects.
          </small>
        )}
        <Button
          variant="soft"
          onClick={() => {
            setFormError("");
            setAdd(true);
          }}
        >
          <PlusIcon />
          Add project
        </Button>
        {agents.codex && <Personalization agents={agents} />}
        <small>{health}</small>
        <small id="limits">
          {usage?.local ? (
            "Local model · no cloud limit"
          ) : usage?.available ? (
            <>
              {usage.plan_type?.replace("chatgpt_", "")}
              {[usage.primary, usage.secondary].filter(Boolean).map((w, i) => (
                <span key={i}>
                  {w!.window_duration_mins === 300 ? "5h" : "Week"}:{" "}
                  {w!.remaining_percent}% left
                  {w!.resets_at
                    ? ` · resets ${new Date(w!.resets_at * 1000).toLocaleString()}`
                    : ""}
                </span>
              ))}
              {usage.credits?.unlimited
                ? "Credits: unlimited"
                : usage.credits?.balance
                  ? `Credits: ${usage.credits.balance}`
                  : ""}
            </>
          ) : (
            usage?.message
          )}
        </small>
        {update && <small>{update}</small>}
      </footer>
    </>
  );
  return (
    <div className="app-shell">
      <header className="workspace-header">
        <Dialog.Root open={menu} onOpenChange={setMenu}>
          <Dialog.Trigger>
            <IconButton variant="ghost" size="3" aria-label="Open navigation">
              <HamburgerMenuIcon />
            </IconButton>
          </Dialog.Trigger>
          <Dialog.Content
            className="navigation-drawer"
            aria-describedby={undefined}
          >
            <Dialog.Title className="sr-only">Projects and chats</Dialog.Title>
            <Dialog.Close>
              <IconButton
                className="close-navigation"
                variant="ghost"
                aria-label="Close navigation"
              >
                <Cross2Icon />
              </IconButton>
            </Dialog.Close>
            {nav}
          </Dialog.Content>
        </Dialog.Root>
        <div className="header-titles">
          <span>{project?.name || "Agent Web"}</span>
          <h1 id="session-title">
            {session?.title ||
              (sessionId === "new"
                ? "New conversation"
                : project
                  ? "Conversations"
                  : "Your workspace")}
          </h1>
        </div>
        {project && (
          <Button
            variant="soft"
            aria-label="New chat"
            onClick={() => navigate(`/projects/${project.id}/chats/new`)}
          >
            <PlusIcon />
            <span>New chat</span>
          </Button>
        )}
      </header>
      {error && (
        <div className="error-banner" role="alert">
          {error}
          <button className="text-button" onClick={() => setError("")}>
            Dismiss
          </button>
        </div>
      )}
      {project && sessionId && (session || sessionId === "new") ? (
        <Chat
          key={`${project.id}-${sessionId}`}
          project={project}
          session={session}
          agents={agents}
          onChanged={refresh}
        />
      ) : (
        <main className="workspace-home">
          {!loaded ? (
            <p role="status">Loading workspace…</p>
          ) : project ? (
            <>
              <p className="eyebrow">{project.path}</p>
              <h2>Pick up where you left off.</h2>
              <div className="conversation-list">
                {(sessions[project.id] || []).map((s) => (
                  <Link key={s.id} to={`/projects/${project.id}/chats/${s.id}`}>
                    <ChatBubbleIcon />
                    <div>
                      <strong>{s.title || "Untitled chat"}</strong>
                      <small>
                        {s.source} ·{" "}
                        {new Date(
                          s.last_activity_at || s.created_at,
                        ).toLocaleString()}
                      </small>
                    </div>
                  </Link>
                ))}
              </div>
              {!sessions[project.id]?.length && (
                <p>No chats yet. Start a new conversation.</p>
              )}
            </>
          ) : (
            <>
              <span className="welcome-mark">A</span>
              <h2>A little space for your next idea.</h2>
              <p>
                Continue a conversation or start something new.
                <br />
                Your projects and agents stay on this machine.
              </p>
              <div className="project-list">
                {projects.map((p) => (
                  <Link key={p.id} to={`/projects/${p.id}`}>
                    <div>
                      <strong>{p.name}</strong>
                      <small>{p.path}</small>
                    </div>
                    <span>{sessions[p.id]?.length || 0} chats →</span>
                  </Link>
                ))}
              </div>
              <Button
                variant="soft"
                onClick={() => {
                  setFormError("");
                  setAdd(true);
                }}
              >
                <PlusIcon />
                Add project
              </Button>
            </>
          )}
        </main>
      )}
      <Dialog.Root open={add} onOpenChange={setAdd}>
        <Dialog.Content maxWidth="500px">
          <Dialog.Title>Add a project</Dialog.Title>
          <Dialog.Description>
            Choose an existing folder inside a configured allowed root.
          </Dialog.Description>
          <form
            id="project-form"
            onSubmit={async (e) => {
              e.preventDefault();
              const data = Object.fromEntries(new FormData(e.currentTarget));
              try {
                await request("/projects", json("POST", data));
                await refresh();
                setAdd(false);
              } catch (e) {
                setFormError((e as Error).message);
              }
            }}
          >
            <label>
              Name
              <input name="name" required placeholder="My project" />
            </label>
            <label>
              Folder path
              <input name="path" required placeholder="Absolute folder path" />
            </label>
            {formError && <p role="alert">{formError}</p>}
            <div className="dialog-actions">
              <Dialog.Close>
                <Button type="button" variant="soft">
                  Cancel
                </Button>
              </Dialog.Close>
              <Button>Add project</Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Root>
      <Dialog.Root
        open={!!defaults}
        onOpenChange={(open) => {
          if (!open) setDefaults(null);
        }}
      >
        <Dialog.Content maxWidth="540px">
          <Dialog.Title>Project settings</Dialog.Title>
          <Dialog.Description>
            {defaults?.name}: defaults for new conversations.
          </Dialog.Description>
          {defaults && (
            <form
              onSubmit={async (e) => {
                e.preventDefault();
                try {
                  await request(
                    `/projects/${defaults.id}/agent-settings`,
                    json("PUT", { ...defaults, approval_policy: "auto" }),
                  );
                  await refresh();
                  setDefaults(null);
                } catch (e) {
                  setFormError((e as Error).message);
                }
              }}
            >
              <SettingsFields
                value={defaults}
                onChange={(s: AgentSettings) =>
                  setDefaults({ ...defaults, ...s })
                }
                agents={agents}
              />
              {formError && <p role="alert">{formError}</p>}
              <div className="dialog-actions">
                <Dialog.Close>
                  <Button type="button" variant="soft">
                    Cancel
                  </Button>
                </Dialog.Close>
                <Button>Save defaults</Button>
              </div>
            </form>
          )}
        </Dialog.Content>
      </Dialog.Root>
    </div>
  );
}
