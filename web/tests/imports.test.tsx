import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setAccessToken } from "../src/api/client";
import { he } from "../src/i18n/he";
import { renderAt, signedIn } from "./helpers";
import { mockApi, status } from "./mockApi";

afterEach(() => setAccessToken(null));

const summary = (o = {}) => ({
  dry_run: true, import_id: null, duplicate_file: false, rows_total: 3, soldiers_created: 2, accounts_created: 2, accounts_updated: 0,
  unchanged: 0, rejected: { no_consent: [4], platform_not_allowed: [5, 9] }, unused_columns: 2, phone_columns_ignored: 2, ...o,
});
const xlsx = () => new File(["PK"], "roster.xlsx", { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });

async function pick(file = xlsx()) {
  await userEvent.upload(await screen.findByLabelText(he.imports.chooseFile), file);
}

describe("roster import", () => {
  it("previews first; only after a preview can the import be committed, with the same file", async () => {
    const forms: FormData[] = [];
    mockApi({
      ...signedIn("uploader"), "GET /imports": () => [],
      "POST /imports/roster": (_u, init) => { const f = init.body as FormData; forms.push(f); return f.get("dry_run") === "true" ? summary() : summary({ dry_run: false, import_id: "i1" }); },
    });
    renderAt("/imports");
    await pick();
    expect(screen.queryByRole("button", { name: he.imports.commit })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: he.imports.preview }));
    expect(await screen.findByText(he.imports.previewResult)).toBeInTheDocument();
    expect(screen.getByText(he.imports.reasons.no_consent)).toBeInTheDocument();
    expect(screen.getByText(he.imports.reasons.platform_not_allowed)).toBeInTheDocument();
    expect(screen.getByText("5, 9")).toBeInTheDocument(); // row numbers, never row contents
    expect(screen.getByText(he.imports.phones("2"))).toBeInTheDocument();
    expect(forms).toHaveLength(1);
    await userEvent.click(screen.getByRole("button", { name: he.imports.commit }));
    expect(await screen.findByText(he.imports.done)).toBeInTheDocument();
    expect(forms.map((f) => f.get("dry_run"))).toEqual(["true", "false"]);
    expect((forms[1].get("file") as File).name).toBe("roster.xlsx");
  });

  it("choosing another file discards the old preview", async () => {
    mockApi({ ...signedIn("uploader"), "GET /imports": () => [], "POST /imports/roster": () => summary() });
    renderAt("/imports");
    await pick();
    await userEvent.click(screen.getByRole("button", { name: he.imports.preview }));
    await screen.findByText(he.imports.previewResult);
    await pick(new File(["PK"], "other.xlsx"));
    expect(screen.queryByText(he.imports.previewResult)).toBeNull();
    expect(screen.queryByRole("button", { name: he.imports.commit })).toBeNull();
  });

  it.each([
    [422, "not_xlsx", he.imports.errors.not_xlsx],
    [422, "macros_not_allowed", he.imports.errors.macros_not_allowed],
    [422, "missing_columns:consent_ref", he.imports.errors.missing_columns],
    [413, "file_too_large", he.imports.errors.file_too_large],
    [403, "Insufficient role", he.common.forbidden],
  ])("maps %s %s to a Hebrew message", async (code, detail, text) => {
    mockApi({ ...signedIn("uploader"), "GET /imports": () => [], "POST /imports/roster": () => status(code, { detail }) });
    renderAt("/imports");
    await pick();
    await userEvent.click(screen.getByRole("button", { name: he.imports.preview }));
    expect(await screen.findByRole("alert")).toHaveTextContent(text);
  });

  it("an auditor sees the history but no upload form", async () => {
    mockApi({ ...signedIn("auditor"), "GET /imports": () => [{ id: "i1", filename: "a.xlsx", status: "done", rows_total: 3, rows_accepted: 2, rows_rejected: 1, uploaded_at: "2026-10-06T10:00:00Z" }] });
    renderAt("/imports");
    expect(await screen.findByText("a.xlsx")).toBeInTheDocument();
    expect(screen.queryByLabelText(he.imports.chooseFile)).toBeNull();
  });

  it("flags a file that was already imported", async () => {
    mockApi({ ...signedIn("uploader"), "GET /imports": () => [], "POST /imports/roster": () => summary({ duplicate_file: true }) });
    renderAt("/imports");
    await pick();
    await userEvent.click(screen.getByRole("button", { name: he.imports.preview }));
    await waitFor(() => expect(screen.getByText(he.imports.duplicateFile)).toBeInTheDocument());
  });
});
