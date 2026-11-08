// Installationsbefehl für einen neuen Node, gemeinsam für Node-Liste und Node-Seite.
// Die Panel-Adresse kommt aus dem Browser. Das Token geht als Umgebungsvariable
// an den Installer, damit es nicht als Argument des Installers auftaucht.
const INSTALL_URL = "https://raw.githubusercontent.com/EpicWing/epicwing-panel/main/scripts/install.sh";

export function installCommand(token: string): string {
  const panel = window.location.origin;
  // Einfache Anführungszeichen absichern, auch wenn ein Token sie nicht enthalten sollte
  const safe = token.replace(/'/g, "'\\''");
  return `curl -fsSL ${INSTALL_URL} | sudo EPICWING_ENROLL_TOKEN='${safe}' bash -s -- node --panel ${panel}`;
}
