// ANSI handling for the server console.
//
// AnsiBuffer turns the raw console stream into lines of styled text segments. It keeps
// its parser state between write() calls, so an escape sequence that is cut in half by a
// chunk boundary is completed by the next chunk. The result is plain data (text plus
// color numbers) that the console component renders without v-html.

export interface AnsiSegment {
  text: string;
  /** 0-15 for the 16 terminal colors, -1 for the default color. */
  fg: number;
  bg: number;
  bold: boolean;
}

export interface ConsoleLine {
  id: number;
  /** Counts changes of the line, so the console can skip lines that did not change. */
  rev: number;
  /** Number of characters in the line. */
  length: number;
  segments: AnsiSegment[];
}

type Mode = "text" | "esc" | "escInter" | "csi" | "osc" | "oscEsc";

const MAX_CSI_LENGTH = 64;
const MAX_OSC_LENGTH = 1024;
const TAB_WIDTH = 8;

function isHighSurrogate(code: number): boolean {
  return code >= 0xd800 && code <= 0xdbff;
}

export class AnsiBuffer {
  lines: ConsoleLine[] = [];
  private readonly maxLines: number;
  private readonly maxLineLength: number;
  private mode: Mode = "text";
  private params = "";
  private oscLength = 0;
  private carriageReturn = false;
  private fg = -1;
  private bg = -1;
  private bold = false;
  private nextId = 0;

  constructor(maxLines = 3000, maxLineLength = 4000) {
    this.maxLines = Math.max(1, maxLines);
    this.maxLineLength = Math.max(1, maxLineLength);
    this.lines.push(this.createLine());
  }

  clear(): void {
    this.lines.length = 0;
    this.lines.push(this.createLine());
    this.mode = "text";
    this.params = "";
    this.carriageReturn = false;
    this.resetStyle();
  }

  write(chunk: string): void {
    let run = "";
    const flush = (): void => {
      if (run) {
        this.addText(run);
        run = "";
      }
    };
    for (let i = 0; i < chunk.length; i += 1) {
      const ch = chunk[i];
      const code = chunk.charCodeAt(i);
      switch (this.mode) {
        case "text":
          if (code === 0x1b) {
            flush();
            this.mode = "esc";
          } else if (ch === "\n") {
            flush();
            this.newLine();
          } else if (ch === "\r") {
            flush();
            this.carriageReturn = true;
          } else if (ch === "\t") {
            run += " ".repeat(TAB_WIDTH - ((this.current().length + run.length) % TAB_WIDTH));
          } else if (code < 0x20 || code === 0x7f || (code >= 0x80 && code <= 0x9f)) {
            // Bell, backspace and other control characters are dropped.
          } else {
            run += ch;
          }
          break;
        case "esc":
          if (ch === "[") {
            this.mode = "csi";
            this.params = "";
          } else if (ch === "]" || ch === "P" || ch === "X" || ch === "^" || ch === "_") {
            this.mode = "osc";
            this.oscLength = 0;
          } else if (code >= 0x20 && code <= 0x2f) {
            this.mode = "escInter";
          } else if (code === 0x1b) {
            // ESC ESC: still waiting for the real sequence.
          } else if (code < 0x20) {
            this.mode = "text";
            i -= 1;
          } else {
            this.mode = "text";
          }
          break;
        case "escInter":
          if (code >= 0x20 && code <= 0x2f) break;
          this.mode = "text";
          if (code < 0x30 || code > 0x7e) i -= 1;
          break;
        case "csi":
          if ((code >= 0x30 && code <= 0x3f) || (code >= 0x20 && code <= 0x2f)) {
            this.params += ch;
            if (this.params.length > MAX_CSI_LENGTH) this.mode = "text";
          } else if (code >= 0x40 && code <= 0x7e) {
            this.finishCsi(ch);
            this.mode = "text";
          } else {
            // A broken sequence: drop it and handle this character normally.
            this.mode = "text";
            i -= 1;
          }
          break;
        case "osc":
          this.oscLength += 1;
          if (ch === "\x07") {
            this.mode = "text";
          } else if (code === 0x1b) {
            this.mode = "oscEsc";
          } else if (this.oscLength > MAX_OSC_LENGTH) {
            this.mode = "text";
          }
          break;
        case "oscEsc":
          if (ch === "\\") {
            this.mode = "text";
          } else {
            this.mode = "esc";
            i -= 1;
          }
          break;
      }
    }
    flush();
  }

  private createLine(): ConsoleLine {
    const id = this.nextId;
    this.nextId += 1;
    return { id, rev: 0, length: 0, segments: [] };
  }

  private current(): ConsoleLine {
    return this.lines[this.lines.length - 1];
  }

  private newLine(): void {
    this.carriageReturn = false;
    this.lines.push(this.createLine());
    const slack = Math.max(1, Math.floor(this.maxLines / 10));
    if (this.lines.length > this.maxLines + slack) {
      this.lines.splice(0, this.lines.length - this.maxLines);
    }
  }

  // A lone carriage return moves back to the start of the line, so progress output
  // that rewrites itself ends up as one line instead of hundreds.
  private clearCurrent(): void {
    const line = this.current();
    line.segments = [];
    line.length = 0;
    line.rev += 1;
  }

  private addText(text: string): void {
    if (this.carriageReturn) {
      this.carriageReturn = false;
      this.clearCurrent();
    }
    let rest = text;
    while (rest) {
      let line = this.current();
      let room = this.maxLineLength - line.length;
      if (room <= 0) {
        this.newLine();
        line = this.current();
        room = this.maxLineLength;
      }
      let end = Math.min(room, rest.length);
      if (end < rest.length && isHighSurrogate(rest.charCodeAt(end - 1))) end -= 1;
      if (end <= 0) end = Math.min(2, rest.length);
      this.append(line, rest.slice(0, end));
      rest = rest.slice(end);
    }
  }

  private append(line: ConsoleLine, text: string): void {
    const last = line.segments[line.segments.length - 1];
    if (last && last.fg === this.fg && last.bg === this.bg && last.bold === this.bold) {
      last.text += text;
    } else {
      line.segments.push({ text, fg: this.fg, bg: this.bg, bold: this.bold });
    }
    line.length += text.length;
    line.rev += 1;
  }

  private resetStyle(): void {
    this.fg = -1;
    this.bg = -1;
    this.bold = false;
  }

  private finishCsi(final: string): void {
    if (final === "m" && /^[0-9;]*$/.test(this.params)) {
      this.applySgr(this.params);
    }
  }

  private applySgr(params: string): void {
    const codes = params === "" ? [0] : params.split(";").map((part) => (part === "" ? 0 : Number(part)));
    for (let i = 0; i < codes.length; i += 1) {
      const code = codes[i];
      if (code === 0) {
        this.resetStyle();
      } else if (code === 1) {
        this.bold = true;
      } else if (code === 22) {
        this.bold = false;
      } else if (code >= 30 && code <= 37) {
        this.fg = code - 30;
      } else if (code === 39) {
        this.fg = -1;
      } else if (code >= 40 && code <= 47) {
        this.bg = code - 40;
      } else if (code === 49) {
        this.bg = -1;
      } else if (code >= 90 && code <= 97) {
        this.fg = code - 90 + 8;
      } else if (code >= 100 && code <= 107) {
        this.bg = code - 100 + 8;
      } else if (code === 38 || code === 48) {
        const kind = codes[i + 1];
        if (kind === 5) {
          const index = codes[i + 2];
          if (typeof index === "number" && index >= 0 && index < 16) {
            if (code === 38) this.fg = index;
            else this.bg = index;
          }
          i += 2;
        } else if (kind === 2) {
          i += 4;
        } else {
          break;
        }
      }
    }
  }
}

export function segmentClass(segment: AnsiSegment): string {
  const classes: string[] = [];
  if (segment.fg >= 0) classes.push(`ansi-fg-${segment.fg}`);
  if (segment.bg >= 0) classes.push(`ansi-bg-${segment.bg}`);
  if (segment.bold) classes.push("ansi-bold");
  return classes.join(" ");
}

// Removes ANSI escape sequences (colors, cursor movement) from a complete string.
const ANSI_PATTERN = /\u001b\[[0-9;?]*[ -/]*[@-~]/g;

export function stripAnsi(value: string): string {
  return value.replace(ANSI_PATTERN, "");
}
