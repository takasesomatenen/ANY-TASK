// Bundles src/{engine,ai,ui}.mjs into a single self-contained index.html so the
// game can be opened straight from disk with no server and no build tooling.
//
//   node build.mjs

import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = (f) => readFileSync(join(here, "src", f), "utf8");

/** Turn an ES module into a plain script body. */
const flatten = (code) =>
  code
    .replace(/^import\s[\s\S]*?from\s+"[^"]*";\s*$/gm, "")
    .replace(/^export\s+(?=const|function|class|let|var)/gm, "")
    .trim();

const html = src("template.html")
  .replace("/*__ENGINE__*/", flatten(src("engine.mjs")))
  .replace("/*__AI__*/", flatten(src("ai.mjs")))
  .replace("/*__UI__*/", flatten(src("ui.mjs")));

writeFileSync(join(here, "index.html"), html);
console.log(`index.html written (${(html.length / 1024).toFixed(1)} kB)`);
