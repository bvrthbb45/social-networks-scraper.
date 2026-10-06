import { readFileSync } from "node:fs";

describe("document is Hebrew and right-to-left", () => {
  const html = readFileSync("index.html", "utf8");
  it("declares lang=he and dir=rtl on <html>", () => {
    expect(html).toMatch(/<html[^>]*\blang="he"/);
    expect(html).toMatch(/<html[^>]*\bdir="rtl"/);
  });
  it("has a Hebrew title", () => {
    expect(html).toMatch(/<title>[^<]*[֐-׿][^<]*<\/title>/);
  });
});
