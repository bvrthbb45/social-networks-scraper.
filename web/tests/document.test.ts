import { readFileSync } from "node:fs";

describe("the page shell", () => {
  const html = readFileSync("index.html", "utf8");

  it("is Hebrew and right-to-left from the first byte", () => {
    expect(html).toMatch(/<html[^>]*\blang="he"/);
    expect(html).toMatch(/<html[^>]*\bdir="rtl"/);
  });

  it("has a Hebrew title", () => {
    expect(html).toMatch(/<title>[^<]*[֐-׿][^<]*<\/title>/);
  });

  it("asks search engines and referrers to keep out", () => {
    expect(html).toMatch(/name="robots"[^>]*noindex/);
    expect(html).toMatch(/name="referrer"[^>]*no-referrer/);
  });
});
