// Fails when CSS/TSX uses physical (left/right) properties instead of logical ones.
// Add "rtl-ok" in a comment on the same line to allow a deliberate exception.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const RULES = [
  [/\b(margin|padding)-(left|right)\b/, "use margin/padding-inline-start/end"],
  [/\bborder-(left|right)\b/, "use border-inline-start/end"],
  [/\bborder-(top|bottom)-(left|right)-radius\b/, "use border-start-start-radius etc."],
  [/(^|[;{\s])(left|right)\s*:/, "use inset-inline-start/end"],
  [/text-align\s*:\s*(left|right)\b/, "use text-align: start/end"],
  [/float\s*:\s*(left|right)\b/, "use float: inline-start/end"],
  [/\b(margin|padding)(Left|Right)\b/, "use marginInline*/paddingInline* in style props"],
  [/\bborder(Left|Right)\b/, "use borderInline* in style props"],
  [/\btextAlign\s*:\s*["'](left|right)["']/, 'use textAlign: "start" | "end"'],
  [/\b(ml|mr|pl|pr)-\d/, "use ms-/me-/ps-/pe- logical utilities"],
];

function* files(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) yield* files(p);
    else if (/\.(css|tsx|ts)$/.test(name)) yield p;
  }
}

let bad = 0;
for (const file of files("src")) {
  readFileSync(file, "utf8").split("\n").forEach((line, i) => {
    if (/rtl-ok/.test(line)) return;
    const code = line.replace(/\/\/.*$/, "").replace(/\/\*.*?\*\//g, "");
    for (const [re, hint] of RULES) {
      if (re.test(code)) {
        console.error(`${file}:${i + 1}: physical direction (${hint})\n    ${line.trim()}`);
        bad++;
      }
    }
  });
}
if (bad) { console.error(`\nRTL lint: ${bad} problem(s)`); process.exit(1); }
console.log("RTL lint: OK");
