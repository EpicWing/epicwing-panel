// Content of the in-panel guide. It is plain data, so the same text can be
// reused for the README and the Discord docs.

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
  icon: string;
  title: string;
  sections: GuideSection[];
}

export const guide: GuideGroup[] = [
  {
    id: "start",
    icon: "🚀",
    title: "Getting started",
    sections: [
      {
        id: "concepts",
        icon: "🧩",
        title: "How it fits together",
        summary:
          "EpicWing has a few simple parts. The panel is the website you are on right now. A node is a machine that runs your game servers, and each server lives in its own Docker container. An egg is the recipe for a game: it says which image to use, how to install it and how to start it. An allocation is an IP address and a port that a server can use. Locations are just groups for your nodes.",
        tips: ["The panel and a node can run on the same machine. This is the easiest way to start."],
        next: "install-panel",
      },
      {
        id: "install-panel",
        icon: "📦",
        title: "Install the panel",
        summary:
          "You need a fresh machine with Debian 13 and a domain. The installer sets up the database, the web server, the backend, the frontend, HTTPS and your first admin account. It takes a few minutes.",
        steps: [
          "Point your domain at the machine with an A record. Port 80 must be open, so that Let's Encrypt can give you a certificate.",
          "Run the command below as root on the fresh machine.",
          "Answer the questions: your domain, the admin e-mail and, if you like, a separate e-mail for Let's Encrypt.",
          "Open your domain in the browser and sign in with the admin account that the installer made.",
        ],
        code: "bash <(curl -fsSL https://raw.githubusercontent.com/EpicWing/epicwing-panel/main/scripts/install.sh) panel",
        tips: [
          "Certificate problems? Check that the A record points to the machine and that port 80 is open.",
          "If the install fails, read /var/log/epicwing-install.log. The part 'Installation failed, what now?' in docs/INSTALL.md shows how to clean up and try again.",
        ],
        warnings: ["Do not run the installer on a machine that already runs EpicWing."],
        next: "first-server",
      },
      {
        id: "first-server",
        icon: "🎮",
        title: "Your first server",
        summary: "This takes you from an empty panel to a running game server.",
        steps: [
          "Add a node under Admin > Nodes and install the agent on that machine (see 'Install the agent on a node').",
          "Add at least one allocation on the page of the node. That is an IP address and a port (see 'Allocations').",
          "Have a look at the eggs under Admin > Nests & Eggs. Six come with the panel, and you can import more.",
          "Create the server under Admin > All Servers. Pick the node, the egg and the port, then set memory, CPU and disk. Tick 'Install the server right after creating it'.",
          "Open the server. The Home tab shows the install output live. When the server says it is ready, the status changes to Running.",
        ],
        tips: ["Stuck on the first start? The console on the Home tab shows what the server is doing."],
        next: "nodes",
      },
    ],
  },
  {
    id: "admin",
    icon: "🛠️",
    title: "Administration",
    sections: [
      {
        id: "overview",
        icon: "📊",
        title: "Overview",
        summary:
          "Your first look at the panel. It shows how many nodes, servers and users you have, how much RAM and disk is given out, and a short checklist while the panel is still empty.",
      },
      {
        id: "nodes",
        icon: "🖥️",
        title: "Nodes",
        summary:
          "A node is a machine that hosts servers, for example a rented VPS or a dedicated server. You add the machine here and then connect the agent on it.",
        steps: [
          "Open Admin > Nodes and add a node.",
          "Enter a name and the address (domain or IP) of the machine. A location and a suggested port range are optional.",
          "Create the node. The panel shows an enrollment token once, so copy it right away.",
          "Install the agent on the machine (next section). Until it connects, the node says 'Waiting for agent'.",
        ],
        tips: [
          "Click a node to see its details, change its settings, get a new token, revoke its credentials or delete it.",
          "The node page also has a ready-made setup command that you can copy.",
        ],
        next: "node-install",
      },
      {
        id: "node-install",
        icon: "⬇️",
        title: "Install the agent on a node",
        summary: "The agent runs on the node. It starts and stops the containers and talks to the panel.",
        steps: [
          "Make sure Docker is installed on the node. The installer does not do this for you.",
          "Create the node in the panel and copy the enrollment token (see 'Nodes').",
          "On the node, run the command below as root. Use the address of your own panel instead of panel.example.com.",
          "Paste the enrollment token when the installer asks for it.",
          "Back in the panel, the node changes from 'Waiting for agent' to online.",
        ],
        code: "bash <(curl -fsSL https://raw.githubusercontent.com/EpicWing/epicwing-panel/main/scripts/install.sh) node --panel https://panel.example.com",
        tips: [
          "The node must be able to reach your panel over HTTPS.",
          "The token is shown only once and runs out after a while. If it is lost or too old, press 'New token'.",
        ],
        next: "allocations",
      },
      {
        id: "allocations",
        icon: "🔢",
        title: "Allocations (ports)",
        summary:
          "An allocation is an IP address and a port on a node that a server can use. Every server needs at least one free allocation. You can use any port from 1024 to 65535, as long as nothing else on the node uses it.",
        steps: [
          "Open Admin > Nodes and click the node.",
          "Go to the Allocations section.",
          "Enter the IP address. This is the address the port is published on, for example the public IP of the node.",
          "Enter the port. To add many at once, fill in 'Last port' too.",
          "Press Add. The summary shows how many allocations exist and how many are free.",
        ],
        tips: ["A port that a server uses cannot be deleted. Take it away from the server first."],
        warnings: ["Open the same ports in the firewall of the node, or players cannot connect."],
      },
      {
        id: "locations",
        icon: "📍",
        title: "Locations",
        summary:
          "Locations group your nodes, for example by data center or country. The table shows how many nodes are online and how many servers run in each location.",
        tips: ["Nodes without a location are listed as unassigned."],
      },
      {
        id: "admin-servers",
        icon: "🗂️",
        title: "All servers",
        summary: "Every server on the panel, with its owner, node and status. You create new servers here and control them.",
        steps: [
          "Press the button to create a server.",
          "Enter a name and pick the node, the egg and the port. The node needs a free allocation.",
          "Add extra ports if the server needs more than one.",
          "Set memory, CPU and disk.",
          "Fill in the variables of the egg. Under the advanced options you can change the container image and the start command.",
          "Tick 'Install the server right after creating it' and create the server.",
        ],
        tips: ["Reinstall, kill and delete ask you to confirm first. A reinstall keeps the files."],
      },
      {
        id: "eggs",
        icon: "🥚",
        title: "Nests and eggs",
        summary:
          "Eggs say what a server runs: the image, the start command, the variables and the install script. A nest is a group of eggs. EpicWing comes with six eggs: Minecraft (Vanilla, Paper, Purpur and Fabric), Unturned and a static website.",
        steps: [
          "To add an egg, press Import egg and choose an egg file in Pterodactyl JSON format.",
          "To keep a copy or share an egg, press Export.",
        ],
        warnings: ["Install scripts and container images run on your nodes. Read an egg before you import it."],
      },
      {
        id: "database-hosts",
        icon: "🗄️",
        title: "Database hosts",
        summary: "A database host is a MariaDB or MySQL server. EpicWing uses it to create databases for your servers.",
        steps: [
          "Open Admin > Database Hosts and create a host with its address, its port and a user that may create databases.",
          "Use the connection test to check the details.",
          "Your servers can now create their own databases in the Databases tab.",
        ],
        warnings: ["Do not open the database host to the public internet."],
      },
      {
        id: "users",
        icon: "👥",
        title: "Users",
        summary: "Create accounts here and decide who is an admin.",
        steps: [
          "Create the account under Admin > Users.",
          "Tick 'Administrator' to give full access to every server and to this admin area.",
          "To block an account without deleting it, disable it.",
        ],
        tips: ["To share one server, make a normal account and add it in the Access tab of that server."],
      },
      {
        id: "notifications",
        icon: "🔔",
        title: "Notifications",
        summary:
          "Tells you when something fails. Add an e-mail address and a Discord webhook, so you notice problems early.",
        steps: ["Fill in the e-mail settings.", "Paste a Discord webhook URL to get alerts in a channel."],
      },
    ],
  },
  {
    id: "server",
    icon: "🕹️",
    title: "Server page",
    sections: [
      {
        id: "home",
        icon: "🏠",
        title: "Home",
        summary:
          "The live console with the power buttons (Start, Stop, Restart and Kill), graphs for CPU, RAM, disk and network, and a field to send commands. While a server installs, the console shows the real installer output.",
        tips: ["The status changes to Running when the server says it is ready."],
      },
      {
        id: "timeline",
        icon: "🕒",
        title: "Timeline",
        summary: "A log of what happened on the server and who did it, for example power actions, file changes and backups.",
        tips: ["Console output is not part of this log."],
      },
      {
        id: "files",
        icon: "📁",
        title: "Files",
        summary: "A file manager and editor for the data of the server.",
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
        icon: "▶️",
        title: "Launch",
        summary: "Shows and changes the start command and the variables of the egg, for example the token of a game server.",
        tips: ["Changes work the next time the server starts."],
      },
      {
        id: "ports",
        icon: "🔌",
        title: "Ports",
        summary: "The allocations of this server. Add more ports, choose the main one or remove ports you do not need.",
        tips: ["Ports below 1024 cannot be used."],
      },
      {
        id: "ddos",
        icon: "🛡️",
        title: "DDoS (Traffic Guard)",
        summary:
          "Shows the traffic going in and out, what is normal for this server, and warns you about odd spikes and console floods.",
        tips: ["It watches and tells you. It does not block traffic."],
      },
      {
        id: "automations",
        icon: "⏰",
        title: "Automations",
        summary: "Run actions on a schedule, for example restart the server every night.",
      },
      {
        id: "server-databases",
        icon: "🗄️",
        title: "Databases",
        summary:
          "Create databases for the server. Enter a name and, if you want, the addresses that may connect. Leave that empty to allow connections from anywhere. You can show the password, change it or delete the database.",
      },
      {
        id: "backups",
        icon: "💾",
        title: "Backups",
        summary: "Make backups of the server, download them, restore them or copy them to another server on the same node.",
        tips: ["You can set a limit for the number of backups per server."],
      },
      {
        id: "access",
        icon: "🤝",
        title: "Access",
        summary: "Give other users access to this server and choose what they may do.",
        tips: ["The owner and the admins always have full access."],
      },
      {
        id: "server-settings",
        icon: "⚙️",
        title: "Settings",
        summary:
          "Change the name and the description of the server, or reinstall it. Admins can also set auto restart: off, after a crash, or always.",
        tips: ["If something fails, add the technical details of the error to your bug report. It helps a lot."],
      },
    ],
  },
  {
    id: "account",
    icon: "👤",
    title: "Your account",
    sections: [
      {
        id: "api-keys",
        icon: "🔑",
        title: "API Keys",
        summary: "Make keys to use the panel API from scripts and other tools.",
        warnings: ["Keep your keys secret and delete the ones you no longer use."],
      },
      {
        id: "ssh-keys",
        icon: "🗝️",
        title: "SSH Keys",
        summary: "Save your public SSH keys here, for example for SFTP access.",
      },
      {
        id: "account-settings",
        icon: "⚙️",
        title: "Settings",
        summary: "Set your avatar and manage your account.",
      },
    ],
  },
];
