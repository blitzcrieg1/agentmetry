import { readdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

const outputDir = path.resolve("out");
const cacheKey = new Date().toISOString().replace(/\D/g, "");
const assetReference = /(_next\/static\/[^"'`\s<>]+?\.(?:js|css))(?!\?v=)/g;

async function walk(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const filePath = path.join(directory, entry.name);
    if (entry.isDirectory()) files.push(...(await walk(filePath)));
    else if (entry.isFile() && entry.name.endsWith(".html")) files.push(filePath);
  }
  return files;
}

const htmlFiles = await walk(outputDir);
let referencesUpdated = 0;

for (const filePath of htmlFiles) {
  const html = await readFile(filePath, "utf8");
  const updated = html.replace(assetReference, (asset) => {
    referencesUpdated += 1;
    return `${asset}?v=${cacheKey}`;
  });
  await writeFile(filePath, updated, "utf8");
}

console.log(`Cache-busted ${referencesUpdated} dashboard assets in ${htmlFiles.length} exported pages (${cacheKey}).`);
