// Content of the in-panel guide. Plain data, so the same text can be reused
// for the README and the Discord documentation.

export interface GuideSection {
  id: string;
  title: string;
  summary: string;
  steps?: string[];
  code?: string;
  tips?: string[];
}

export interface GuideGroup {
  id: string;
  title: string;
  sections: GuideSection[];
}

export const guide: GuideGroup[] = [
  {
    id: "start",
    title: "Getting started",
    sections: [
      {
        id: "concepts",
        title: "How it fits together",
        summary:
          "A node is a machine that runs the EpicWing agent. Servers run as Docker containers on a node. An egg describes what a server runs: the container image, the start command, the install script and its variables. An allocation is an IP address and port that a server can use. Locations group your nodes.",
        tips: ["The panel and a node can run on the same machine."],
      },
      {
        id: "install-panel",
        title: "Install the panel",
        summary:
          "The installer sets up PostgreSQL, nginx, the backend, the frontend, a TLS certificate and the first administrator. It is tested on Debian 13.",
        steps: [
          "Point your domain (an A record) at the machine. Port 80 must be reachable so that Let's Encrypt can issue the certificate.",
          "Run the command below as root on the fresh machine.",
          "Answer the questions: the domain, the administrator e-mail and an optional e-mail for Let's Encrypt.",
          "Open your domain in the browser and sign in with the administrator account that the installer created.",
        ],
        code: "bash <(curl -fsSL https://raw.githubusercontent.com/EpicWing/epicwing-panel/main/scripts/install.sh) panel",
        tips: [
          "Do not run the installer on a machine that already runs EpicWing.",
          "If the installation fails, read /var/log/epicwing-install.log. The section 'Installation failed, what now?' in docs/INSTALL.md explains how to clean up and try again.",
        ],
      },
      {
        id: "first-server",
        title: "Your first server",
        summary: "From an empty panel to a running server.",
        steps: [
          "Add a node under Admin > Nodes and install the agent on that machine (see 'Install the agent on a node').",
          "Add at least one allocation, an IP address and port, on the page of the node (see 'Allocations').",
          "Look at the eggs under Admin > Nests & Eggs. Six are bundled, more can be imported.",
          "Create the server under Admin > All Servers. Choose the node, the egg and the port, then set memory, CPU and disk. Tick 'Install the server right after creating it'.",
          "Open the server. The Home tab shows the install output in the console. When the server reports that it is ready, the status changes to Running.",
        ],
      },
    ],
  },
  {
    id: "admin",
    title: "Administration",
    sections: [
      {
        id: "overview",
        title: "Overview",
        summary:
          "A first look at the panel: how many nodes, servers and users you have, how much RAM and disk is allocated, and a short checklist while the panel is still empty.",
      },
      {
        id: "nodes",
        title: "Nodes",
        summary:
          "A node is a machine that hosts servers, for example a rented VPS or a dedicated server. Add the machine here, then connect the agent on it.",
        steps: [
          "Open Admin > Nodes and add a node.",
          "Enter a name and the address (domain or IP) of the machine. A location and a suggested port range are optional.",
          "Create the node. The panel shows an enrollment token once. Copy it right away.",
          "Install the agent on the machine (next section). Until it connects, the node shows 'Waiting for agent'.",
        ],
        tips: [
          "Click a node to see its details, change its settings, get a new token, revoke its credentials or delete it.",
          "The node page also shows a ready-made setup command that you can copy.",
        ],
      },
      {
        id: "node-install",
        title: "Install the agent on a node",
        summary: "The agent runs on the node, starts and stops the containers and talks to the panel.",
        steps: [
          "Make sure Docker is installed on the node. The installer does not install it for you.",
          "Create the node in the panel and copy the enrollment token (see 'Nodes').",
          "On the node, run the command below as root. Replace the address with the address of your panel.",
          "Paste the enrollment token when the installer asks for it.",
          "Back in the panel, the node changes from 'Waiting for agent' to online.",
        ],
        code: "bash <(curl -fsSL https://raw.githubusercontent.com/EpicWing/epicwing-panel/main/scripts/install.sh) node --panel https://panel.example.com",
        tips: [
          "The node must be able to reach your panel over HTTPS.",
          "The token is shown only once and expires. If it is lost or expired, create a new one with 'New token'.",
        ],
      },
      {
        id: "allocations",
        title: "Allocations (ports)",
        summary:
          "An allocation is an IP address and port on a node that a server can use. Every server needs at least one free allocation. Any port from 1024 to 65535 works, as long as nothing else on the node uses it.",
        steps: [
          "Open Admin > Nodes and click the node.",
          "Go to the Allocations section.",
          "Enter the IP address. This is the address the port is published on, for example the public IP of the node.",
          "Enter the port. To add a whole range at once, fill in 'Last port' as well.",
          "Press Add. The summary shows how many allocations exist and how many are free.",
        ],
        tips: [
          "Open the same ports in the firewall of the node, or players cannot connect.",
          "A port that a server uses cannot be deleted. Remove it from the server first.",
        ],
      },
      {
        id: "locations",
        title: "Locations",
        summary:
          "Locations group your nodes, for example by data center or country. The table shows how many nodes are online and how many servers run in each location.",
        tips: ["Nodes without a location are listed as unassigned."],
      },
      {
        id: "admin-servers",
        title: "All servers",
        summary: "Every server on the panel with owner, node and status. Create new servers here and control them.",
        steps: [
          "Press the button to create a server.",
          "Enter a name and choose the node, the egg and the port. The node needs a free allocation.",
          "Add extra ports if the server needs more than one.",
          "Set memory, CPU and disk.",
          "Fill in the variables of the egg. Under the advanced options you can change the container image and the start command.",
          "Tick 'Install the server right after creating it' and create the server.",
        ],
        tips: ["Reinstall, kill and delete ask for confirmation first. A reinstall keeps the files."],
      },
      {
        id: "eggs",
        title: "Nests and eggs",
        summary:
          "Eggs define what a server runs: image, start command, variables and install script. A nest groups eggs. EpicWing ships six eggs: Minecraft (Vanilla, Paper, Purpur, Fabric), Unturned and a static website.",
        steps: [
          "To add an egg, press Import egg and choose an egg file in Pterodactyl JSON format.",
          "To keep a copy or share an egg, press Export.",
        ],
        tips: ["Install scripts and container images run on your nodes. Read an egg before you import it."],
      },
      {
        id: "database-hosts",
        title: "Database hosts",
        summary: "A database host is a MariaDB or MySQL server that EpicWing uses to create databases for your servers.",
        steps: [
          "Open Admin > Database Hosts and create a host with its address, port and a user that may create databases.",
          "Use the connection test to check the details.",
          "Servers can then create their own databases in the Databases tab of the server.",
        ],
        tips: ["Do not expose the database host to the public internet."],
      },
      {
        id: "users",
        title: "Users",
        summary: "Create accounts and decide who is an administrator.",
        steps: [
          "Create the account under Admin > Users.",
          "Tick 'Administrator' for full access to every server and to this admin area.",
          "Disable an account to block it without deleting it.",
        ],
        tips: ["To share one server, create a normal account and add it in the Access tab of that server."],
      },
      {
        id: "notifications",
        title: "Notifications",
        summary: "Tells you when something fails. Connect an e-mail address and a Discord webhook so that you notice problems early.",
        steps: ["Fill in the e-mail settings.", "Paste a Discord webhook URL to get alerts in a channel."],
      },
    ],
  },
  {
    id: "server",
    title: "Server page",
    sections: [
      {
        id: "home",
        title: "Home",
        summary:
          "The live console with the power buttons (Start, Stop, Restart, Kill), usage graphs for CPU, RAM, disk and network, and a field to send commands. During an install the console shows the real installer output.",
        tips: ["The status changes to Running when the server reports that it is ready."],
      },
      {
        id: "timeline",
        title: "Timeline",
        summary: "A log of what happened on the server and who did it, such as power actions, file changes and backups.",
        tips: ["Console output is not part of the log."],
      },
      {
        id: "files",
        title: "Files",
        summary: "A file manager and editor for the data of the server.",
        steps: [
          "Click a file to edit it. Folders come first, names are sorted alphabetically.",
          "Select files with the checkboxes to download them as a ZIP or delete them.",
          "Upload files with the Upload button.",
          "Right-click a file for more actions such as rename, move, download and unarchive.",
        ],
        tips: ["Archives (zip, tar.gz) are unpacked into the current folder."],
      },
      {
        id: "launch",
        title: "Launch",
        summary: "Shows and edits the start command and the variables of the egg, for example a game server token.",
        tips: ["Changes apply the next time the server starts."],
      },
      {
        id: "ports",
        title: "Ports",
        summary: "The allocations of the server. Add more ports, choose the primary one or remove ports you do not need.",
        tips: ["Ports below 1024 cannot be used."],
      },
      {
        id: "ddos",
        title: "DDoS (Traffic Guard)",
        summary:
          "Shows incoming and outgoing network traffic, what is usual for this server, and warns about unusual spikes and console floods.",
        tips: ["It watches and reports. It does not block traffic."],
      },
      {
        id: "automations",
        title: "Automations",
        summary: "Run actions on a schedule, for example restart the server every night.",
      },
      {
        id: "server-databases",
        title: "Databases",
        summary:
          "Create databases for the server. Enter a name and, if you want, the addresses that may connect. Leave that empty to allow connections from anywhere. You can show the password, rotate it or delete the database.",
      },
      {
        id: "backups",
        title: "Backups",
        summary: "Create backups of the server, download them, restore them or copy them to another server on the same node.",
        tips: ["A limit for the number of backups can be set per server."],
      },
      {
        id: "access",
        title: "Access",
        summary: "Give other users access to this server and choose what they may do.",
        tips: ["The owner and administrators always have full access."],
      },
      {
        id: "server-settings",
        title: "Settings",
        summary:
          "Change the server name and description and reinstall the server. Administrators can also set auto restart: off, after a crash, or always.",
        tips: ["If something fails, the technical details of the error help a lot in a bug report."],
      },
    ],
  },
  {
    id: "account",
    title: "Your account",
    sections: [
      {
        id: "api-keys",
        title: "API Keys",
        summary: "Create keys to use the panel API from scripts and other tools. Keep them secret and delete keys you no longer use.",
      },
      {
        id: "ssh-keys",
        title: "SSH Keys",
        summary: "Store your public SSH keys here, for example for SFTP access.",
      },
      {
        id: "account-settings",
        title: "Settings",
        summary: "Set your avatar and manage your account.",
      },
    ],
  },
];
