import { onBeforeUnmount, ref, shallowRef } from "vue";
import { useI18n } from "vue-i18n";

import { ApiError, api } from "../api/client";
import { AnsiBuffer, type ConsoleLine } from "../utils/ansi";

export interface ConsoleFrame {
  type?: string;
  data?: string;
  status?: string;
  message?: string;
}

interface Options {
  /** Called for every frame from the node, e.g. for stats. */
  onFrame?: (frame: ConsoleFrame) => void;
  maxLines?: number;
}

// Connection to the console websocket of one server. Output is parsed into lines
// and published at most once per animation frame.
export function useServerConsole(options: Options = {}) {
  const { t } = useI18n();
  const buffer = new AnsiBuffer(options.maxLines);
  const lines = shallowRef<ConsoleLine[]>(buffer.lines.slice());
  const status = ref("connecting");
  const error = ref("");
  let socket: WebSocket | null = null;
  let frameRequest = 0;

  function publish(): void {
    frameRequest = 0;
    lines.value = buffer.lines.slice();
  }

  function write(data: string): void {
    buffer.write(data);
    if (!frameRequest) frameRequest = window.requestAnimationFrame(publish);
  }

  function handleMessage(raw: string): void {
    let frame: ConsoleFrame;
    try {
      const parsed: unknown = JSON.parse(raw);
      if (parsed === null || typeof parsed !== "object") {
        write(raw);
        return;
      }
      frame = parsed as ConsoleFrame;
    } catch {
      write(raw);
      return;
    }
    if (frame.type === "output" && frame.data) {
      write(frame.data);
    } else if (frame.type === "status" && frame.status) {
      status.value = frame.status;
    } else if (frame.type === "clear") {
      clear();
    } else if (frame.type === "error") {
      error.value = frame.message ?? t("console.connectionError");
    }
    options.onFrame?.(frame);
  }

  async function connect(serverId: string): Promise<void> {
    socket?.close();
    // The backend replays the install output on every new socket, so start from scratch.
    clear();
    status.value = "connecting";
    try {
      const { ticket } = await api<{ ticket: string }>(`/servers/${serverId}/console/ticket`, {
        method: "POST",
        body: {},
      });
      const scheme = window.location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(
        `${scheme}://${window.location.host}/api/servers/${serverId}/console?ticket=${encodeURIComponent(ticket)}`,
      );
      socket = ws;
      ws.onopen = () => {
        status.value = "connected";
        error.value = "";
      };
      ws.onmessage = (event) => {
        if (typeof event.data === "string") handleMessage(event.data);
      };
      ws.onerror = () => {
        status.value = "error";
        error.value = t("console.connectionError");
      };
      ws.onclose = () => {
        if (status.value !== "error") status.value = "closed";
      };
    } catch (cause) {
      status.value = "error";
      error.value = cause instanceof ApiError ? cause.message : t("console.connectionError");
    }
  }

  function send(value: string): boolean {
    const text = value.trim();
    if (!text || socket?.readyState !== WebSocket.OPEN) return false;
    socket.send(JSON.stringify({ type: "input", data: text }));
    return true;
  }

  function clear(): void {
    buffer.clear();
    publish();
  }

  function close(): void {
    socket?.close();
  }

  onBeforeUnmount(() => {
    if (frameRequest) window.cancelAnimationFrame(frameRequest);
    close();
  });

  return { lines, status, error, connect, send, clear, close };
}
