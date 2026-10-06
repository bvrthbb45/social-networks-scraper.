// Language guard: every string in the Hebrew catalogue must actually contain Hebrew, and may
// contain Latin words only when they are on the allow-list of product names.
import { he } from "../src/i18n/he.ts";

const PRODUCT_NAMES = ["Google", "Excel", "Authenticator", "QR"];
const HEBREW = /[֐-׿]/;
const LATIN_WORD = /[A-Za-z]{2,}/;

const offenders = [];

function inspect(path, text) {
  const withoutNames = PRODUCT_NAMES.reduce((t, name) => t.replaceAll(name, ""), text);
  if (LATIN_WORD.test(withoutNames) || !HEBREW.test(text)) offenders.push(`he.${path} -> ${JSON.stringify(text)}`);
}

function visit(node, path) {
  if (typeof node === "string") return inspect(path, node);
  if (typeof node === "function") {
    // message builders: call with placeholder arguments to see the rendered text
    const args = Array.from({ length: node.length }, (_, i) => (i === 0 ? "#" : "1"));
    return inspect(path, node(...args));
  }
  for (const [key, value] of Object.entries(node)) visit(value, path ? `${path}.${key}` : key);
}

visit(he, "");
if (offenders.length) {
  console.error(offenders.join("\n"));
  console.error(`\nHebrew lint: ${offenders.length} string(s) without Hebrew`);
  process.exit(1);
}
console.log("Hebrew lint: OK");
