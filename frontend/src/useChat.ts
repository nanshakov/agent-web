import { useCallback, useEffect, useRef, useState } from "react";
import { request, type Message, type TurnEvent } from "./api";

// History is authoritative. Stream payloads are cumulative, keyed by turn, never appended deltas.
export function useChat(sessionId: string | undefined) {
  const [history, setHistory] = useState<Message[]>([]);
  const [streams, setStreams] = useState<Record<string, TurnEvent>>({});
  const [connection, setConnection] = useState("Connecting");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(!!sessionId);
  const refreshRef = useRef<() => Promise<void>>(async () => {});
  useEffect(() => {
    setHistory([]);
    setStreams({});
    setError("");
    setLoading(!!sessionId);
    if (!sessionId) {
      setConnection("Ready");
      return;
    }
    let disposed = false,
      socket: WebSocket | undefined,
      retry: ReturnType<typeof setTimeout>,
      attempt = 0,
      refreshing = false,
      again = false;
    const controller = new AbortController();
    async function refresh() {
      if (refreshing) {
        again = true;
        return;
      }
      refreshing = true;
      try {
        do {
          again = false;
          const messages = await request<Message[]>(
            `/sessions/${sessionId}/messages`,
            { signal: controller.signal },
          );
          if (!disposed) {
            setHistory(messages);
            setError("");
            setLoading(false);
          }
        } while (again && !disposed);
      } catch (e) {
        if (!disposed) {
          setError((e as Error).message);
          setLoading(false);
        }
      } finally {
        refreshing = false;
      }
    }
    refreshRef.current = refresh;
    function connect() {
      if (disposed) return;
      setConnection(attempt ? "Reconnecting" : "Connecting");
      socket = new WebSocket(
        `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/v1/ws/sessions/${sessionId}`,
      );
      socket.onopen = () => {
        if (disposed) return;
        attempt = 0;
        setConnection("Live");
        void refresh();
      };
      socket.onmessage = (e) => {
        if (disposed) return;
        try {
          const event: TurnEvent = JSON.parse(e.data);
          if (!event.turn_id) return;
          setStreams((old) => ({ ...old, [event.turn_id]: event }));
          if (event.status !== "running") void refresh();
        } catch {
          setError(
            "Could not read an agent update. Reconnecting will restore history.",
          );
        }
      };
      socket.onclose = () => {
        if (disposed) return;
        setConnection("Reconnecting");
        retry = setTimeout(connect, Math.min(1000 * 2 ** attempt++, 10000));
      };
      socket.onerror = () => socket?.close();
    }
    const resume = () => {
      if (document.visibilityState === "hidden") return;
      void refresh();
      if (!socket || socket.readyState === WebSocket.CLOSED) {
        clearTimeout(retry);
        connect();
      }
    };
    connect();
    void refresh();
    // Also recover persisted state if a server restart loses its in-memory event replay.
    const poll = setInterval(() => {
      if (document.visibilityState !== "hidden") void refresh();
    }, 5000);
    window.addEventListener("online", resume);
    window.addEventListener("pageshow", resume);
    document.addEventListener("visibilitychange", resume);
    return () => {
      disposed = true;
      controller.abort();
      clearTimeout(retry);
      clearInterval(poll);
      socket?.close();
      window.removeEventListener("online", resume);
      window.removeEventListener("pageshow", resume);
      document.removeEventListener("visibilitychange", resume);
    };
  }, [sessionId]);
  const messages = [...history];
  for (const stream of Object.values(streams)) {
    const index = messages.findIndex(
      (m) => m.role === "assistant" && m.turn_id === stream.turn_id,
    );
    const persisted = messages.find(
      (m) =>
        m.role === "assistant" &&
        m.turn_id === stream.turn_id &&
        m.status !== "running",
    );
    if (persisted && index >= 0) continue;
    const message: Message = {
      role: "assistant",
      turn_id: stream.turn_id,
      status: stream.status,
      content: stream.content || "Agent is working…",
      rendered_content: stream.rendered_content,
    };
    if (index >= 0) messages[index] = message;
    else if (!persisted) messages.push(message);
  }
  const running =
    history.some(
      (m) =>
        m.status === "running" &&
        !streams[m.turn_id!]?.status?.match(/completed|failed/),
    ) ||
    Object.values(streams).some(
      (s) =>
        s.status === "running" &&
        !history.some((m) => m.turn_id === s.turn_id && m.status !== "running"),
    );
  return {
    messages,
    running,
    connection,
    error,
    loading,
    refresh: useCallback(() => refreshRef.current(), []),
  };
}
