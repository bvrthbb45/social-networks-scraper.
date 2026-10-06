// End-to-end: invite -> password -> 2FA -> roles -> import -> findings -> evidence -> decision -> audit.
import { execFileSync } from "node:child_process";
import { chromium } from "playwright-core";
import { join } from "node:path";

const BASE = "http://localhost:4173";
const OUT = process.env.E2E_OUT;
const SHOTS = process.env.E2E_SHOTS || OUT; // set E2E_SHOTS to keep the screenshots
const PASSWORD = "correct horse battery 7";
const py = (...args) => execFileSync("python3", ["e2e/helpers.py", ...args], { encoding: "utf8", env: process.env }).trim();
const he = {
  setPassword: "קביעת סיסמה", enable: "הפעלה", cont: "המשך", users: "משתמשים", create: "משתמש חדש", findings: "התראות",
};

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH, args: ["--no-sandbox"] });
let step = 0;
const ok = (msg) => console.log(`ok ${++step} - ${msg}`);
const fail = (msg) => { throw new Error(msg); };
const expect = (cond, msg) => (cond ? ok(msg) : fail(`FAILED: ${msg}`));

async function enrol(page, token, label) {
  await page.goto(`${BASE}/?invite=${token}`);
  expect(!(await page.url()).includes("invite="), `${label}: invitation token removed from the address bar`);
  await page.getByLabel("סיסמה").fill(PASSWORD);
  await page.getByRole("button", { name: he.setPassword }).click();
  const secret = (await page.getByTestId("totp-secret").textContent()).trim();
  await page.getByLabel("קוד אימות").fill(py("totp", secret));
  await page.getByRole("button", { name: he.enable }).click();
  await page.locator(".codes li").first().waitFor();
  const codes = await page.locator(".codes li").allTextContents();
  expect(codes.length === 10, `${label}: 10 recovery codes shown`);
  await page.getByLabel("שמרתי את הקודים").check();
  await page.getByRole("button", { name: he.cont }).click();
  return secret;
}

// --- admin ----------------------------------------------------------------------------------
const admin = await (await browser.newContext({ locale: "he-IL" })).newPage();
await enrol(admin, process.env.ADMIN_INVITE, "admin");
await admin.getByRole("heading", { name: "לוח בקרה" }).waitFor();
expect((await admin.getByRole("navigation").first().locator("a").count()) === 9, "admin sees all 9 sections");
expect((await admin.locator("html").getAttribute("dir")) === "rtl", "document is right-to-left");

async function createUser(email, roleLabel) {
  await admin.getByRole("link", { name: he.users }).first().click();
  await admin.getByRole("button", { name: he.create }).click();
  const dlg = admin.getByRole("dialog");
  await dlg.getByLabel("אימייל").fill(email);
  await dlg.getByLabel("תפקיד").selectOption({ label: roleLabel });
  await dlg.getByRole("button", { name: he.create }).click();
  const link = (await admin.getByTestId("invite-link").textContent()).trim();
  await admin.getByRole("button", { name: "סגירה" }).first().click();
  return new URL(link).searchParams.get("invite");
}
const uploaderToken = await createUser("uploader@example.org", "מעלה קבצים");
const reviewerToken = await createUser("reviewer@example.org", "בודק");
ok("admin created uploader and reviewer, one-time links shown");

// watch-list through the UI
py("terms", join(OUT, "terms.xlsx"));
await admin.getByRole("link", { name: "רשימת מעקב" }).first().click();
await admin.getByLabel("ייבוא רשימת מונחים").setInputFiles(join(OUT, "terms.xlsx"));
await admin.getByText("נוספו 2, עודכנו 0.").waitFor();
ok("watch-list imported (2 terms)");

// --- uploader -------------------------------------------------------------------------------
const uploader = await (await browser.newContext({ locale: "he-IL" })).newPage();
await enrol(uploader, uploaderToken, "uploader");
await uploader.getByRole("heading", { name: "ייבוא קבצים" }).waitFor();
expect((await uploader.getByRole("navigation").first().locator("a").count()) === 2, "uploader sees only imports + account");
await uploader.goto(`${BASE}/users`);
await uploader.getByRole("heading", { name: "ייבוא קבצים" }).waitFor();
ok("uploader is redirected away from /users");

py("roster", join(OUT, "roster.xlsx"));
await uploader.getByLabel("בחירת קובץ Excel").setInputFiles(join(OUT, "roster.xlsx"));
await uploader.getByRole("button", { name: "תצוגה מקדימה" }).click();
await uploader.getByText("תוצאת תצוגה מקדימה").waitFor();
expect(await uploader.getByText("רשת לא נתמכת", { exact: false }).isVisible(), "preview rejects the WhatsApp row with a Hebrew reason");
expect(await uploader.getByText("זוהו 1 עמודות טלפון", { exact: false }).isVisible(), "phone column is reported as ignored");
await uploader.screenshot({ path: join(SHOTS, "import-preview.png") });
await uploader.getByRole("button", { name: "אישור וייבוא" }).click();
await uploader.getByText("הייבוא הושלם.").waitFor();
ok("roster committed after preview");
py("seed");
ok("a post with text + image was ingested and analysed");

// --- reviewer -------------------------------------------------------------------------------
const reviewer = await (await browser.newContext({ locale: "he-IL" })).newPage();
await enrol(reviewer, reviewerToken, "reviewer");
await reviewer.getByRole("heading", { name: "לוח בקרה" }).waitFor();
await reviewer.getByRole("link", { name: he.findings }).first().click();
await reviewer.getByRole("heading", { name: he.findings, exact: true }).waitFor();
await reviewer.locator("tbody tr").first().waitFor();
const rows = await reviewer.locator("tbody tr").count();
expect(rows >= 3, `reviewer sees ${rows} findings`);
await reviewer.screenshot({ path: join(SHOTS, "queue.png") });

// open the most suspicious one
await reviewer.locator("tbody tr").first().getByRole("link", { name: "פתיחה" }).click();
await reviewer.getByRole("heading", { name: "פרטי התראה" }).waitFor();
expect(await reviewer.getByText("ההחלטה היא שלכם").isVisible(), "page states a human decides");
expect(await reviewer.getByText("בבסיס צפוני", { exact: false }).first().isVisible(), "post text shown");
expect((await reviewer.locator("img").count()) === 0, "image hidden by default");
await reviewer.getByRole("button", { name: "הצגת התמונה" }).click();
await reviewer.locator("img").first().waitFor();
const natural = await reviewer.locator("img").first().evaluate((i) => i.naturalWidth);
expect(natural > 0, "evidence image actually decodes in the browser");
await reviewer.screenshot({ path: join(SHOTS, "detail.png"), fullPage: true });

await reviewer.getByRole("button", { name: "דחייה – התראת שווא" }).click();
await reviewer.getByLabel("סיבת הדחייה").selectOption({ label: "מילה רגילה, לא שם קוד" });
await reviewer.getByLabel("הערה (לא חובה)").fill("הערה סודית של בודק");
await reviewer.getByRole("button", { name: "שמירה" }).click();
await reviewer.getByText("ההחלטה נשמרה.", { exact: false }).waitFor();
await reviewer.getByText("מילה רגילה, לא שם קוד").last().waitFor();
ok("decision saved and shown in history");
await reviewer.getByRole("link", { name: "חזרה לרשימה" }).click();
await reviewer.getByRole("heading", { name: he.findings, exact: true }).waitFor();
await reviewer.waitForTimeout(300);
const after = await reviewer.locator("tbody tr").count();
expect(after === rows - 1, `dismissed finding left the queue (${rows} -> ${after})`);
await reviewer.getByRole("tab", { name: "נדחה" }).click();
await reviewer.locator("tbody tr").first().waitFor();
ok("it appears under the dismissed tab");
await reviewer.goto(`${BASE}/audit`);
await reviewer.getByRole("heading", { name: "לוח בקרה" }).waitFor();
ok("reviewer cannot open the audit page");

// --- admin: audit trail ---------------------------------------------------------------------
await admin.getByRole("link", { name: "יומן ביקורת" }).first().click();
await admin.getByText("finding.decided").first().waitFor();
const text = await admin.locator("main").textContent();
for (const a of ["evidence.viewed", "finding.viewed", "finding.decided", "user.created", "import.committed"])
  expect(text.includes(a), `audit trail contains ${a}`);
for (const secret of ["הערה סודית", "חייל בדוי", "7000001", "e2e_user", "נשר שחור"])
  expect(!text.includes(secret), `audit trail does not contain "${secret}"`);

// --- tokens never in web storage --------------------------------------------------------------
const stored = await reviewer.evaluate(() => JSON.stringify({ l: { ...localStorage }, s: { ...sessionStorage } }));
expect(stored === '{"l":{},"s":{}}', "no tokens in localStorage / sessionStorage");
const cookies = await reviewer.context().cookies();
const refresh = cookies.find((c) => c.name === "refresh_token");
expect(refresh?.httpOnly === true && refresh?.sameSite === "Strict", "refresh cookie is httpOnly + SameSite=Strict");

// reload keeps the session through the cookie, in memory token restored
await reviewer.goto(`${BASE}/findings`);
await reviewer.getByRole("heading", { name: he.findings, exact: true }).waitFor();
ok("page reload restores the session from the refresh cookie");

// --- sign out really revokes ----------------------------------------------------------------
await reviewer.getByRole("button", { name: "יציאה" }).first().click();
await reviewer.getByRole("heading", { name: "כניסה למערכת" }).waitFor();
await reviewer.goto(`${BASE}/findings`);
await reviewer.getByRole("heading", { name: "כניסה למערכת" }).waitFor();
ok("after sign-out the refresh cookie no longer works");

await browser.close();
console.log(`\nAll ${step} end-to-end checks passed. Screenshots in ${SHOTS}`);
