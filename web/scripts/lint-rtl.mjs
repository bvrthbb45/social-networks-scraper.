// Right-to-left guard: the UI is Hebrew, so layout must use logical (start/end) properties.
// Physical left/right values break mirroring. Add "rtl-ok" to a line to allow a deliberate exception.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const FORBIDDEN = [
  { re: /\b(?:margin|padding)-(?:left|right)\b/, fix: "margin/padding-inline-start|end" },
  { re: /\bborder-(?:left|right)(?:-[a-z]+)?\b/, fix: "border-inline-start|end" },
  { re: /\bborder-(?:top|bottom)-(?:left|right)-radius\b/, fix: "border-start-start-radius and friends" },
  { re: /(?:^|[;{\s])(?:left|right)\s*:/, fix: "inset-inline-start|end" },
  { re: /text-align\s*:\s*(?:left|right)\b/, fix: "text-align: start|end" },
  { re: /float\s*:\s*(?:left|right)\b/, fix: "float: inline-start|end" },
  { re: /\b(?:margin|padding|border)(?:Left|Right)\b/, fix: "the *Inline* variants in style props" },
  { re: /\btextAlign\s*:\s*["'](?:left|right)["']/, fix: 'textAlign: "start" | "end"' },
  { re: /\b(?:ml|mr|pl|pr)-\d/, fix: "ms-/me-/ps-/pe- utilities" },
];

function sourceFiles(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return /\.(?:css|tsx?)$/.test(name) ? [path] : [];
  });
}

const stripComments = (line) => line.replace(/\/\/.*$/, "").replace(/\/\*.*?\*\//g, "");

const problems = [];
for (const file of sourceFiles("src")) {
  readFileSync(file, "utf8")
    .split("\n")
    .forEach((line, index) => {
      if (line.includes("rtl-ok")) return;
      const code = stripComments(line);
      for (const { re, fix } of FORBIDDEN) {
        if (re.test(code)) problems.push(`${file}:${index + 1}  use ${fix}\n    ${line.trim()}`);
      }
    });
}

if (problems.length) {
  console.error(problems.join("\n"));
  console.error(`\nRTL lint: ${problems.length} physical-direction use(s)`);
  process.exit(1);
}
console.log("RTL lint: OK");
