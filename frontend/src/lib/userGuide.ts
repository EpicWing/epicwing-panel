// Help for everyone who uses the panel, not only admins. Same format as adminGuide.ts.

import type { GuideGroup } from "./adminGuide";

export const userGuide: GuideGroup[] = [
  {
    id: "servers",
    title: "Your servers",
    sections: [
      {
        id: "server-basics",
        icon: "server",
        title: "Start, stop and the console",
        summary:
          "Open a server from the list. On Home you start, stop and restart it and see the console. Commands you type into the console go straight to the server, like on its own command line.",
        steps: [
          "Click the server in the list.",
          "Press Start. The console shows what the server prints while it starts.",
          "Type a command into the field below the console and press Enter.",
        ],
        tips: ["Stop asks the server to shut down cleanly, so it can save first."],
        next: "files-panel",
      },
      {
        id: "access",
        icon: "user-plus",
        title: "Let others help you",
        summary:
          "Under Access you can add other people to your server and pick exactly what they may do, for example only use the console or only read files. They need an account on this panel.",
        steps: [
          "Open the server and go to Access.",
          "Click Add user and enter their email address.",
          "Tick what they may do and save. You can change it later at any time.",
        ],
        warnings: ["Only give people the permissions they really need."],
      },
      {
        id: "backups",
        icon: "archive",
        title: "Backups",
        summary:
          "Under Backups you make a copy of all files of the server and can go back to it later. How many backups a server can have is set by the admin.",
        steps: [
          "Open the server and go to Backups.",
          "Click New Backup, then Create. Large servers can take a few minutes.",
          "To go back, stop the server and click Restore next to the backup.",
        ],
        warnings: ["Restoring replaces the current files with the ones from the backup."],
      },
    ],
  },
  {
    id: "files",
    title: "Files and SFTP",
    sections: [
      {
        id: "files-panel",
        icon: "folder",
        title: "Files in the browser",
        summary:
          "Under Files you can open, edit, upload and download the files of your server right in the panel. For a few files this is the easiest way. For many or large files, SFTP is faster.",
        next: "ssh-key",
      },
      {
        id: "ssh-key",
        icon: "key",
        title: "Create an SSH key",
        summary:
          "SFTP here works with an SSH key instead of a password. A key has two parts: the private key stays on your computer, the public key goes into the panel. You only do this once.",
        steps: [
          "Open a terminal. On Windows that is PowerShell, on a Mac the Terminal app.",
          "Run the command below and press Enter three times. That keeps the default file and sets no passphrase. You can also type a passphrase if you want.",
          "The key is now in the folder .ssh in your user folder. id_ed25519 is the private key, id_ed25519.pub is the public key.",
          "Open id_ed25519.pub with a text editor and copy the whole line. It starts with ssh-ed25519.",
          "In the panel go to SSH Keys, click Add SSH Key, paste the line and save.",
        ],
        code: 'ssh-keygen -t ed25519 -C "epicwing"',
        warnings: [
          "Never share the private key (the file without .pub). Anyone who has it can open your server files.",
        ],
        next: "sftp",
      },
      {
        id: "sftp",
        icon: "download",
        title: "Connect with FileZilla or WinSCP",
        summary:
          "Open the server and go to Settings. The SFTP card shows a line like sftp -P 2222 1a2b3c4d@node.example.com. The number after -P is the port, the part before the @ is your user name and the part after it is the host.",
        steps: [
          "FileZilla: open Edit → Settings → Connection → SFTP, click Add key file and pick id_ed25519 from your .ssh folder. FileZilla may offer to convert it, say yes.",
          "FileZilla: open File → Site Manager, click New site and choose SFTP as protocol. Enter host, port and user name from the SFTP card and set Logon type to Interactive or Normal without a password. Click Connect.",
          "WinSCP: choose SFTP, enter host, port and user name. Under Advanced → SSH → Authentication pick id_ed25519 as private key file. WinSCP converts it to a .ppk file for you.",
          "On Linux or a Mac you can also just run the line from the SFTP card in a terminal.",
        ],
        code: "sftp -P 2222 1a2b3c4d@node.example.com",
        tips: [
          "Every server has its own user name. If you have more servers, each one gets its own entry in FileZilla.",
          "If the SFTP card says your access is read only, you can download files but not change them.",
        ],
        next: "sftp-problems",
      },
      {
        id: "sftp-problems",
        icon: "alert",
        title: "If SFTP does not connect",
        summary: "Most problems come from one of these points.",
        steps: [
          "Permission denied (publickey): the public key is missing under SSH Keys, or your program uses a different private key. Check that you added the .pub file of the same key.",
          "Connection refused or timeout: check the port. It is the number after -P on the SFTP card, not 22.",
          "You see no files or cannot change them: ask the owner of the server for the file permissions under Access.",
        ],
      },
    ],
  },
  {
    id: "automation",
    title: "Scripts and bots",
    sections: [
      {
        id: "api-key",
        icon: "lock",
        title: "Create an API key",
        summary:
          "An API key lets a script or a Discord bot control your servers without your password. It can do what you can do on your servers, or only look if you make it read only.",
        steps: [
          "Go to API Keys and click Create API Key.",
          "Give it a name you will recognise later, for example Discord bot.",
          "Tick Read only if the script only needs to look. Set an expiry if you only need it for a while.",
          "Copy the key right away. It starts with ewk_ and is shown only once.",
        ],
        warnings: [
          "Treat the key like a password. If it leaks, delete it under API Keys and create a new one.",
        ],
        next: "api-example",
      },
      {
        id: "api-example",
        icon: "terminal",
        title: "Use the key",
        summary:
          "Send the key in the Authorization header. The first command lists your servers with their IDs, the second one starts a server. Replace the panel address, the key and the server ID with your own.",
        code: [
          'curl -H "Authorization: Bearer ewk_..." https://panel.example.com/api/servers',
          "",
          'curl -X POST -H "Authorization: Bearer ewk_..." -H "Content-Type: application/json" \\',
          '  -d \'{"action": "start"}\' https://panel.example.com/api/servers/SERVER-ID/power',
        ].join("\n"),
        tips: ['Other actions are "stop", "restart" and "kill".'],
      },
    ],
  },
];
