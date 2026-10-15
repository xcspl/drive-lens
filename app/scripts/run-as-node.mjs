// Run a script with Electron's Node, so native modules built for Electron
// (better-sqlite3 after `npm run rebuild`) load. Usage: node scripts/run-as-node.mjs <script> [args]
import { spawn } from "node:child_process";
import electron from "electron";

const child = spawn(electron, process.argv.slice(2), { stdio: "inherit", env: { ...process.env, ELECTRON_RUN_AS_NODE: "1" } });
child.on("exit", (code) => process.exit(code ?? 0));
