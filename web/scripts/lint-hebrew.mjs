// Every UI string in the catalogue must be Hebrew (brand/product names excepted).
import { he } from "../src/i18n/he.ts";

const ALLOWED = ["Google", "Excel", "Authenticator", "QR"];
let bad = 0;

function check(path, text) {
  let rest = text;
  for (const w of ALLOWED) rest = rest.replaceAll(w, "");
  if (/[A-Za-z]{2,}/.test(rest) || !/[֐-׿]/.test(text)) {
    console.error(`he.${path}: not Hebrew -> ${JSON.stringify(text)}`);
    bad++;
  }
}

function walk(node, path) {
  if (typeof node === "string") return check(path, node);
  if (typeof node === "function") return check(path, node(...Array.from({ length: node.length }, (_, i) => (i === 0 ? "#" : "1"))));
  for (const [k, v] of Object.entries(node)) walk(v, path ? `${path}.${k}` : k);
}
walk(he, "");
if (bad) { console.error(`\nHebrew lint: ${bad} problem(s)`); process.exit(1); }
console.log("Hebrew lint: OK");
