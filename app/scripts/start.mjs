// Launch the app. Clears ELECTRON_RUN_AS_NODE, which editors such as VS Code
// set for their child processes and which makes Electron run as plain Node.
import { spawn } from "node:child_process";
import electron from "electron";

const env = { ...process.env };
delete env.ELECTRON_RUN_AS_NODE;
const child = spawn(electron, ["."], { stdio: "inherit", env });
child.on("exit", (code) => process.exit(code ?? 0));
