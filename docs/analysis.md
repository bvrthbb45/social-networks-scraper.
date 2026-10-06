# Analysis engines (Loop 4)

Everything runs **locally**. No post, image or text is ever sent to an external AI or API service.
Every result is a **finding = a lead for a human reviewer**. The system never decides anything about a person.

## What is analysed, and when
Only content of an **open** account under an **active, in-date consent**, that has not passed its retention date.
This is checked at intake (`POST /posts/import`) *and again* by the pipeline before analysis, so a consent revoked
or an account that turned private between the two stops analysis.

## Engines
| engine | finding kind | how reliable |
|---|---|---|
| Watch-list (code names, sites, units) on post text and on OCR text | `codename`, `location` | Good. Handles Hebrew prefixes (ב/ה/ל/מ/ש/ו/כ), niqqud, final letters, typos on terms ≥ 5 letters, obfuscation ("נ.ש.ר"). Short single-word terms (≤ 3 letters, e.g. "נשר") are damped because they are ordinary Hebrew words. |
| Classification markers (סודי, סודי ביותר, שמור, בלמ"ס, …) | `text_pattern`; `classified_document` when found inside a picture | Good as a lead; the word alone is not proof. |
| Coordinates, map links (lat/long, ITM, MGRS, Google/Waze links) | `location` | Good. |
| EXIF GPS embedded in a picture | `location` (high) | Precise. Metadata is stripped before the image is stored. |
| OCR (Tesseract, Hebrew + English) | feeds the text engines | Depends on image quality; skipped automatically if Tesseract is not installed. |
| Uniform colour (olive-green / beige region of person-like size) | `uniform` (always low severity, score ≤ 0.6) | **Weak.** A colour heuristic: expect false positives (clothes, walls, wood) and misses. Loop 6 calibrates it from reviewer decisions. |
| Trained image model (equipment, aircraft, classified-looking items, screens) | `equipment`, `screen_photo`, … | **Not shipped.** The plug-in point (`Classifier`) exists and loads weights from `MODEL_DIR` when the unit supplies them; until then these kinds are simply not reported. |

## Data handling
* Post text, finding reasons and evidence snippets are encrypted per row (AES-256-GCM, row-bound context).
* Images are re-encoded without metadata and stored as encrypted files addressed by content hash (`MEDIA_DIR`, mode 0600, outside the repo).
* `delete_after` is set at intake (`RETENTION_DAYS`); the purge job comes in Loop 7.
* Audit entries carry counts and reason codes only, never content.

## Operations
* `python -m app.cli analyze-pending` (re-)analyses posts that have not been analysed by the current `ENGINE_VERSION`. Findings are idempotent: re-running adds nothing.
* Collection itself is **not** part of this service. Content arrives through the API from an approved connector or by hand.

## Known limits (honest list)
* Precision of the colour heuristic is low until trained on the unit's own reviewed examples.
* Fuzzy matching is limited to one edit; transliteration variants (English ↔ Hebrew spelling of a code name) must be added as aliases.
* OCR on stylised or low-resolution images is unreliable.
