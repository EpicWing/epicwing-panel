// Wraps a refresh function for setInterval: it only runs while the tab is visible.
// Hidden tabs then stop asking the panel every few seconds.
export function whenVisible(refresh: () => unknown): () => void {
  return () => {
    if (!document.hidden) void refresh();
  };
}
