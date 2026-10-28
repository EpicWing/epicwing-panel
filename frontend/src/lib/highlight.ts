export type Lang = "plain" | "yaml" | "json" | "ini" | "shell";

export const LANGUAGES: { id: Lang; label: string }[] = [
  { id: "plain", label: "Plain text" },
  { id: "yaml", label: "YAML / Config" },
  { id: "json", label: "JSON" },
  { id: "ini", label: "INI / Properties" },
  { id: "shell", label: "Shell" },
];

const COMMENT = "text-ink-500";
const PUNCT = "text-ink-500";
const KEY = "text-ink-100";
const VALUE = "text-ink-300";
const STRING = "text-ink-200";
const NUMBER = "text-accent-300";
const SECTION = "text-accent-500";

function esc(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function span(cls: string, text: string): string {
  return text === "" ? "" : `<span class="${cls}">${esc(text)}</span>`;
}

function tokenize(
  line: string,
  pattern: RegExp,
  paint: (match: RegExpExecArray) => string,
): string {
  let out = "";
  let last = 0;
  pattern.lastIndex = 0;
  for (let match = pattern.exec(line); match !== null; match = pattern.exec(line)) {
    const whole = match[0] ?? "";
    out += esc(line.slice(last, match.index)) + paint(match);
    last = match.index + whole.length;
    if (whole.length === 0) pattern.lastIndex += 1;
  }
  return out + esc(line.slice(last));
}

function scalar(text: string): string {
  const word = text.trim();
  const flag = /^(true|false|null|~|yes|no|on|off)$/i.test(word);
  const number = /^[-+]?(\d[\d_]*\.?\d*|\.\d+)([eE][-+]?\d+)?$/.test(word);
  return span(flag || number ? NUMBER : VALUE, text);
}

function yamlTail(text: string): string {
  const hash = text.search(/\s#/);
  if (hash === -1) return esc(text);
  return esc(text.slice(0, hash)) + span(COMMENT, text.slice(hash));
}

function yamlValue(text: string): string {
  const quoted = /^(\s*)("(?:[^"\\]|\\.)*"|'[^']*')(.*)$/.exec(text);
  if (quoted) {
    return esc(quoted[1] ?? "") + span(STRING, quoted[2] ?? "") + yamlTail(quoted[3] ?? "");
  }
  const hash = text.search(/\s#/);
  if (hash === -1) return scalar(text);
  return scalar(text.slice(0, hash)) + span(COMMENT, text.slice(hash));
}

function yamlLine(line: string): string {
  let match = /^(\s*)(#.*)$/.exec(line);
  if (match) return esc(match[1] ?? "") + span(COMMENT, match[2] ?? "");
  match = /^(\s*(?:-\s+)?)([^\s#][^#]*?)(:)(?=\s|$)(.*)$/.exec(line);
  if (match) {
    return esc(match[1] ?? "") + span(KEY, match[2] ?? "") + span(PUNCT, ":") + yamlValue(match[4] ?? "");
  }
  match = /^(\s*)(-)(\s.*|)$/.exec(line);
  if (match) return esc(match[1] ?? "") + span(PUNCT, "-") + yamlValue(match[3] ?? "");
  return span(VALUE, line);
}

const JSON_TOKEN =
  /("(?:[^"\\]|\\.)*")(\s*:)?|(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)|\b(true|false|null)\b|([{}[\],:])/g;

function jsonLine(line: string): string {
  return tokenize(line, JSON_TOKEN, (match) => {
    if (match[1] !== undefined) {
      return match[2] !== undefined
        ? span(KEY, match[1]) + span(PUNCT, match[2])
        : span(STRING, match[1]);
    }
    if (match[3] !== undefined) return span(NUMBER, match[3]);
    if (match[4] !== undefined) return span(NUMBER, match[4]);
    return span(PUNCT, match[0] ?? "");
  });
}

function iniLine(line: string): string {
  let match = /^(\s*)([#;].*)$/.exec(line);
  if (match) return esc(match[1] ?? "") + span(COMMENT, match[2] ?? "");
  match = /^(\s*)(\[[^\]]*\])(.*)$/.exec(line);
  if (match) return esc(match[1] ?? "") + span(SECTION, match[2] ?? "") + esc(match[3] ?? "");
  match = /^(\s*)([^=:\s][^=:]*?)(\s*[=:]\s*)(.*)$/.exec(line);
  if (match) {
    return esc(match[1] ?? "") + span(KEY, match[2] ?? "") + span(PUNCT, match[3] ?? "") + scalar(match[4] ?? "");
  }
  return esc(line);
}

const SHELL_TOKEN = /(#.*$)|("(?:[^"\\]|\\.)*"|'[^']*')|(\$\{?[A-Za-z_][A-Za-z0-9_]*\}?)/g;

function shellLine(line: string): string {
  return tokenize(line, SHELL_TOKEN, (match) => {
    if (match[1] !== undefined) return span(COMMENT, match[1]);
    if (match[2] !== undefined) return span(STRING, match[2]);
    return span(NUMBER, match[3] ?? "");
  });
}

function renderLine(line: string, lang: Lang): string {
  switch (lang) {
    case "yaml":
      return yamlLine(line);
    case "json":
      return jsonLine(line);
    case "ini":
      return iniLine(line);
    case "shell":
      return shellLine(line);
    default:
      return esc(line);
  }
}

// Gibt HTML zurück; der letzte Zeilenumbruch hält die Höhe identisch zum Textfeld.
export function highlight(text: string, lang: Lang): string {
  return (
    text
      .replace(/\r\n?/g, "\n")
      .split("\n")
      .map((line) => renderLine(line, lang))
      .join("\n") + "\n"
  );
}

export function detectLanguage(name: string, text: string): Lang {
  const ext = name.includes(".") ? (name.split(".").pop() ?? "").toLowerCase() : "";
  if (ext === "yml" || ext === "yaml") return "yaml";
  if (ext === "json") return "json";
  if (["properties", "ini", "cfg", "conf", "toml"].includes(ext)) return "ini";
  if (ext === "sh" || ext === "bash") return "shell";
  const keyLines = text
    .split("\n", 400)
    .filter((line) => /^\s*[A-Za-z0-9_.-]+:(\s|$)/.test(line)).length;
  return keyLines >= 3 ? "yaml" : "plain";
}
