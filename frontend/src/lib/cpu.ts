// CPU values above 0 but below 0.1 % are shown as 0.1 %, so a running server never shows 0.
export function formatCpu(percent: number, digits = 1): string {
  if (percent > 0 && percent < 0.1) return "0.1%";
  return `${percent.toFixed(digits)}%`;
}
