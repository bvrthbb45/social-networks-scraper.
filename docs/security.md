# Security model (Loop 2)

## Accounts
* No self-registration. An **admin** creates a user (email + role); the API returns a one-time invitation token (72 h, stored only as a SHA-256 hash). The user sets their own password with it — the admin never learns it.
* The **first admin** is created on the server: `python -m app.cli create-admin EMAIL`.
* Password policy: ≥ 12 chars, not common, not containing the e-mail name; Argon2id; constant-time failure path.
* **2FA (TOTP) is mandatory.** A password alone never yields an API session. Recovery codes are single-use (atomic claim). TOTP replay is rejected.
* Lockout after 5 failures for 15 minutes; unknown users and wrong passwords return the same answer.
* Lost phone/password: admin `POST /users/{id}/reset-credentials` → account locked out, 2FA wiped, all devices revoked, one-time reset link issued.

## Roles
| role | can |
|---|---|
| uploader | (Loop 3) import roster / account files |
| reviewer | (Loop 5) review findings and decide |
| admin | manage users, watch-lists, settings |
| auditor | read the audit trail |

`require_roles(...)` guards every endpoint; the test-suite checks each role against each protected route. Last-admin and self-demotion are refused.

## Sessions and devices
Every sign-in creates a **device** (web or Android). The access token (10 min) carries the device id and is checked against the database on **every request**, so revoking a device or deactivating a user takes effect immediately. Refresh tokens rotate; presenting an already-used one revokes the whole device session (theft assumed). Session lifetime is absolute (web 12 h, Android 7 d) and is not extended by refreshing. Browsers receive the refresh token as an httpOnly SameSite=Strict cookie; the Android app receives it in the response body and keeps it in the Android Keystore.

## Data protection
AES-256-GCM field encryption with a key id byte, rotation support and per-field AAD (ciphertext cannot be moved between rows/columns). HMAC blind indexes with Hebrew normalisation allow lookup without storing plaintext. OpenAPI/docs are disabled; CORS is an allow-list; security headers are set on every response.

## Audit
Append-only (database trigger). Records who/what/when/IP; never passwords, tokens or evidence. Readable by auditor and admin only.

## Not yet done
Passkeys, IP allow-listing and a second-person approval workflow are deferred; see the roadmap.
