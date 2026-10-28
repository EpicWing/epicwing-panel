// Removes ANSI escape sequences (colors, cursor movement) from console output.
const ANSI_PATTERN = /\u001b\[[0-9;?]*[ -/]*[@-~]/g;

export function stripAnsi(value: string): string {
  return value.replace(ANSI_PATTERN, "");
}
