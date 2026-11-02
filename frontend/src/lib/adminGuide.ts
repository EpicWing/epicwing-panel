// Content of the in-panel guide. It is plain data, so the same text can be
// reused for the README and the Discord docs.
// "icon" is the name of an icon in components/GuideIcon.vue.

export interface GuideSection {
  id: string;
  icon: string;
  title: string;
  summary: string;
  steps?: string[];
  code?: string;
  tips?: string[];
  warnings?: string[];
  next?: string;
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
        icon: "layers",
        title: "How it fits together",
        summary:
          "A node is a machine that runs game servers. Each server runs in its own Docker container on a node. An egg describes a game: the image, the install script, the start command and the variables. An allocation is an IP address and a port that a server can use. Locations only group your nodes.",
        tips: ["The panel and a node can run on the same machine."],
        next: "install-panel",
      },
      {
        id: "install-panel",
        icon: "package",
        title: "Install the panel",
        summary:
          "Run the installer on a fresh Debian 13 machine. It sets up PostgreSQL, nginx, the backend, the frontend, a TLS certificate and the first admin account.",
        steps: [
          "Create an A record for your domain that points to the machine. Port 80 must be open, because Let's Encrypt needs it.",
          "Run the command below as root.",
          "Answer the questions: your domain, the admin e-mail and, if you want, an e-mail for Let's Encrypt.",
          "Open the domain in your browser and sign in with the admin account.",
        ],
        code: "bash <(curl -fsSL https://raw.githubusercontent.com/EpicWing/epicwing-panel/main/scripts/install.sh) panel",
        tips: [
          "If the install fails, look at /var/log/epicwing-install.log. The part 'Installation failed, what now?' in docs/INSTALL.md explains how to clean up and start again.",
        ],
        warnings: ["Do not run the installer on a machine that already runs EpicWing."],
        next: "first-server",
      },
      {
        id: "first-server",
        icon: "flag",
        title: "Your first server",
        summary: "From an empty panel to a running server.",
        steps: [
          "Add a node under Admin > Nodes and install the agent on the machine (see 'Install the agent on a node').",
          "Add an allocation on the page of the node (see 'Allocations').",
          "Check the eggs under Admin > Nests & Eggs. Six are included, and you can import more.",
          "Create the server under Admin > All Servers. Choose the node, the egg and the port, then set memory, CPU and disk. Tick 'Install the server right after creating it'.",
          "Open the server. The Home tab shows the install output. When the server is ready, the status changes to Running.",
        ],
        next: "nodes",
      },
    ],
  },
  {
    id: "admin",
    title: "Administration",
    sections: [
      {
        id: "overview",
        icon: "grid",
        title: "Overview",
        summary:
          "Shows how many nodes, servers and users you have and how much RAM and disk is given out. While the panel is still empty, it also shows a short checklist.",
      },
      {
        id: "nodes",
        icon: "server",
        title: "Nodes",
        summary:
          "A node is a machine that hosts servers, for example a VPS or a dedicated server. Add the machine here, then connect the agent on it.",
        steps: [
          "Open Admin > Nodes and add a node.",
          "Enter a name and the address (domain or IP) of the machine. A location and a suggested port range are optional.",
          "Create the node. The panel shows an enrollment token once. Copy it right away.",
          "Install the agent on the machine (next section). Until it connects, the node says 'Waiting for agent'.",
        ],
        tips: [
          "Click a node to see its details. There you can also change its settings, get a new token, revoke its credentials, delete it and copy a ready setup command.",
        ],
        next: "node-install",
      },
      {
        id: "node-install",
        icon: "download",
        title: "Install the agent on a node",
        summary: "The agent runs on the node. It starts and stops the containers and talks to the panel.",
        steps: [
          "Make sure Docker is installed on the node. The installer does not install it.",
          "Create the node in the panel and copy the enrollment token (see 'Nodes').",
          "Run the command below on the node as root. Use the address of your own panel instead of panel.example.com.",
          "Paste the enrollment token when the installer asks for it.",
          "In the panel, the node changes from 'Waiting for agent' to online.",
        ],
        code: "bash <(curl -fsSL https://raw.githubusercontent.com/EpicWing/epicwing-panel/main/scripts/install.sh) node --panel https://panel.example.com",
        tips: [
          "The node must reach the panel over HTTPS. The token is shown once and runs out after a while. If it is lost or too old, press 'New token'.",
        ],
        next: "allocations",
      },
      {
        id: "allocations",
        icon: "hash",
        title: "Allocations (ports)",
        summary:
          "An allocation is an IP address and a port on a node. Every server needs at least one free allocation. You can use any port from 1024 to 65535 that nothing else on the node uses.",
        steps: [
          "Open Admin > Nodes and click the node.",
          "Go to the Allocations section.",
          "Enter the IP address. This is the address the port is published on, for example the public IP of the node.",
          "Enter the port. To add many at once, fill in 'Last port' too.",
          "Press Add. The summary shows how many allocations exist and how many are free.",
        ],
        tips: ["A port that a server uses cannot be deleted. Remove it from the server first."],
        warnings: ["Open the same ports in the firewall of the node. Otherwise players cannot connect."],
      },
      {
        id: "locations",
        icon: "map-pin",
        title: "Locations",
        summary:
          "Locations group your nodes, for example by data center or country. The table shows how many nodes are online and how many servers run in each location. Nodes without a location are listed as unassigned.",
      },
      {
        id: "admin-servers",
        icon: "list",
        title: "All servers",
        summary: "All servers on the panel with owner, node and status. You create and control servers here.",
        steps: [
          "Press the button to create a server.",
          "Enter a name and choose the node, the egg and the port. The node needs a free allocation.",
          "Add extra ports if the server needs more than one.",
          "Set memory, CPU and disk.",
          "Fill in the variables of the egg. Under the advanced options you can change the container image and the start command.",
          "Tick 'Install the server right after creating it' and create the server.",
        ],
        tips: ["Reinstall, kill and delete ask for a confirmation. A reinstall keeps the files."],
      },
      {
        id: "eggs",
        icon: "egg",
        title: "Nests and eggs",
        summary:
          "An egg says what a server runs: the image, the start command, the variables and the install script. A nest is a group of eggs. Six eggs are included: Minecraft (Vanilla, Paper, Purpur, Fabric), Unturned and a static website.",
        steps: [
          "To add an egg, press Import egg and choose an egg file in Pterodactyl JSON format.",
          "To keep a copy or share an egg, press Export.",
        ],
        warnings: ["Install scripts and container images run on your nodes. Read an egg before you import it."],
      },
      {
        id: "database-hosts",
        icon: "database",
        title: "Database hosts",
        summary: "A database host is a MariaDB or MySQL server. EpicWing uses it to create databases for your servers.",
        steps: [
          "Open Admin > Database Hosts and create a host with its address, its port and a user that may create databases.",
          "Use the connection test to check the details.",
          "Servers can now create their own databases in the Databases tab.",
        ],
        warnings: ["Do not expose the database host to the public internet."],
      },
      {
        id: "users",
        icon: "users",
        title: "Users",
        summary: "Create accounts and choose who is an admin.",
        steps: [
          "Create the account under Admin > Users.",
          "Tick 'Administrator' for full access to every server and to this admin area.",
          "To block an account without deleting it, disable it.",
        ],
        tips: ["To share one server, create a normal account and add it in the Access tab of that server."],
      },
      {
        id: "notifications",
        icon: "bell",
        title: "Notifications",
        summary: "Get a message when something fails.",
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
        icon: "terminal",
        title: "Home",
        summary:
          "The live console. It has the power buttons (Start, Stop, Restart, Kill), graphs for CPU, RAM, disk and network, and a field for commands. During an install it shows the real installer output. The status changes to Running when the server reports that it is ready.",
      },
      {
        id: "timeline",
        icon: "activity",
        title: "Timeline",
        summary:
          "A log of what happened on the server and who did it: power actions, file changes, backups. Console output is not included.",
      },
      {
        id: "files",
        icon: "folder",
        title: "Files",
        summary: "File manager and editor for the data of the server.",
        steps: [
          "Click a file to edit it. Folders come first, then everything is sorted by name.",
          "Tick files with the checkboxes to download them as a ZIP or delete them.",
          "Add files with the Upload button.",
          "Right-click a file for more actions like rename, move, download and unarchive.",
        ],
        tips: ["Archives (zip and tar.gz) are unpacked into the current folder."],
      },
      {
        id: "launch",
        icon: "play",
        title: "Launch",
        summary:
          "The start command and the variables of the egg, for example the token of a game server. Changes apply at the next start.",
      },
      {
        id: "ports",
        icon: "link",
        title: "Ports",
        summary:
          "The allocations of this server. Add ports, choose the main one or remove ports you do not need. Ports below 1024 cannot be used.",
      },
      {
        id: "ddos",
        icon: "shield",
        title: "DDoS (Traffic Guard)",
        summary:
          "Shows incoming and outgoing traffic and what is normal for this server. It warns about unusual spikes and console floods. It only watches, it does not block traffic.",
      },
      {
        id: "automations",
        icon: "clock",
        title: "Automations",
        summary: "Run actions on a schedule, for example restart the server every night.",
      },
      {
        id: "server-databases",
        icon: "database",
        title: "Databases",
        summary:
          "Create databases for the server. Enter a name and, if you want, the addresses that may connect. Leave it empty to allow every address. You can show the password, rotate it or delete the database.",
      },
      {
        id: "backups",
        icon: "archive",
        title: "Backups",
        summary:
          "Create backups, download them, restore them, or copy them to another server on the same node. A limit for the number of backups can be set per server.",
      },
      {
        id: "access",
        icon: "user-plus",
        title: "Access",
        summary:
          "Give other users access to this server and choose what they may do. The owner and admins always have full access.",
        tips: [
          "Start with a preset (Viewer, Operator or Manager) and change single permissions after that. Tabs that a user may not use are hidden for that user.",
        ],
      },
      {
        id: "server-settings",
        icon: "sliders",
        title: "Settings",
        summary:
          "Change the name and description, or reinstall the server. Admins can also set auto restart: off, after a crash, or always.",
        tips: ["If something fails, add the technical error details to your bug report."],
      },
    ],
  },
  {
    id: "account",
    title: "Your account",
    sections: [
      {
        id: "api-keys",
        icon: "key",
        title: "API Keys",
        summary: "Create keys for the panel API, to use from scripts and other tools.",
        warnings: ["Keep your keys secret. Delete keys you do not use anymore."],
      },
      {
        id: "ssh-keys",
        icon: "lock",
        title: "SSH Keys",
        summary: "Save your public SSH keys, for example for SFTP.",
      },
      {
        id: "account-settings",
        icon: "sliders",
        title: "Settings",
        summary: "Set your avatar and manage your account.",
      },
    ],
  },
];
