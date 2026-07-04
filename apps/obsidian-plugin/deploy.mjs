// Copy the built plugin into the repo vault so Obsidian picks it up.
import { cpSync, mkdirSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const here = dirname(fileURLToPath(import.meta.url));
const target = join(here, "..", "..", "vault", ".obsidian", "plugins", "blackbox");

mkdirSync(target, { recursive: true });
for (const file of ["main.js", "manifest.json"]) {
  cpSync(join(here, file), join(target, file));
}
console.log(`Deployed to ${target} — enable "BLACKBOX" in Obsidian community plugins.`);
