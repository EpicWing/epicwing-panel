// Install command for a new node, shared by the node list and the node page.
// The panel address comes from the browser. The token is passed as an environment
// variable so it does not show up as an argument of the installer.
const INSTALL_URL = "https://raw.githubusercontent.com/EpicWing/epicwing-panel/main/scripts/install.sh";

export function installCommand(token: string): string {
  const panel = window.location.origin;
  // Escape single quotes, even though a token should never contain them
  const safe = token.replace(/'/g, "'\\''");
  // Run as root. bash <(...) keeps stdin on the terminal, same form as in the README
  return `EPICWING_ENROLL_TOKEN='${safe}' bash <(curl -fsSL ${INSTALL_URL}) node --panel ${panel}`;
}
