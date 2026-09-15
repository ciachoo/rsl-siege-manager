# Manager Human Authentication + RBAC Audit

Audit basis: repository HEAD `72ed626aec8ea6a0479ccdffb5a7260643e7a407` (2026-09-15). **CURRENT** describes inspected code; **PROPOSED** is Task #5B design. This document defines no implemented permission, API contract or migration. The task instruction's `2ed626` checkpoint is not a Git object here; the clean HEAD has the stated `feat: add authenticated scanner ingestion API` subject.

Task #5B implementation status is recorded in `MANAGER_HUMAN_AUTH_RBAC_IMPLEMENTATION.md`. The CURRENT/PROPOSED statements below remain the pre-implementation audit baseline; Task #5B implemented the foundation and representative Siege/Building mutation checks, while comprehensive route classification remains Task #5C.

## Executive summary

**CURRENT:** Discord OAuth proves identity, requires guild membership and a configured Discord role, then admits only a matching `Member`. A signed, client-contained JWT cookie identifies the Member for 24 hours. Ordinary protected API routers require a principal but have no application-level role authorization: an authenticated human, bot service token, or development bypass can reach operational mutations. Scanner credentials use an independent dependency and are not bypassed by `AUTH_DISABLED`.

**PROPOSED:** Keep Discord OAuth as identity and initial admission, add a DB-owned `UserAccount` with one VIEWER/MANAGER/ADMIN role, load role and active state on every human request, and require a real human ADMIN for security operations. Keep `Member` and `MemberRole` as Siege participant concepts. Provision the first ADMIN through a trusted local operator command, never an unauthenticated web endpoint.

## Current authentication architecture

The human path is `frontend/src/pages/LoginPage.tsx` → `GET /api/auth/login` → Discord authorize → `GET /api/auth/callback` → Discord profile and bot-sidecar guild check → `Member` lookup → `session` cookie → `get_current_user()` in `backend/app/dependencies/auth.py` → route. `backend/app/main.py` mounts health, version, config and auth without router-level authentication; `/api/auth/me` adds its own `Depends(get_current_user)`. Other ordinary routers are mounted with that dependency. `backend/app/dependencies/scanner.py` authenticates scanner calls separately. `backend/app/services/bot_client.py` uses its own Bearer credential to contact the bot sidecar; the incoming bot-service token is handled in `get_current_user()` and is a different credential.

There is no persistent application user or security role model. `AuthenticatedUser` is a request dataclass with `member_id`, name, `is_service`, optional `MemberRole` string and Discord ID. Router-level authentication currently establishes identity, not operational permission. No ordinary endpoint-level ADMIN dependency was found.

## Current Discord OAuth flow

`backend/app/api/auth.py::login` creates a 32-byte random state encoded as 64 hex characters, stores it in a 300-second HttpOnly, SameSite=Lax `oauth_state` cookie, and returns an authorize URL for scope `identify`. `LoginPage.tsx` navigates the browser to that URL. Login and callback are IP-rate-limited (`backend/app/rate_limit.py`, default 10/minute and 5/minute).

`auth.py::callback` compares the query state with the cookie using `secrets.compare_digest`, exchanges the code for an access token, reads Discord `/users/@me`, and asks `bot_client.get_member(discord_id)` for guild membership and `role_names`. It rejects non-members and identities lacking `settings.discord_required_role` (default `Clan Deputies`). It then requires `Member.discord_id == discord_user["id"]`; username fallback is deliberately absent in human login. Missing Member is denied. On success it signs a JWT and redirects to `/`; error paths redirect to `/login?error=...`. Discord guild/required-role checks happen at callback, not on each authenticated request. The Discord role is an admission gate today, but there is no separate Manager authorization check afterward.

## Current session/token model

`auth.py::callback` signs an HS256 JWT with `settings.session_secret`, `sub=str(member.id)`, `name`, `iat` and `exp` at 24 hours. The HttpOnly, SameSite=Lax `session` cookie has a 23-hour max age and is Secure except in development. `get_current_user()` decodes the cookie and looks up `Member` by `sub` on every request. There is no server-side session/revocation table. The JWT does not contain a Manager role; the returned `role` comes from the current `Member.role`, which is a player classification. No refresh flow exists. `POST /api/auth/logout` deletes the browser cookie only; a copied, still-valid JWT is not invalidated server-side. The callback uses a Discord access token in memory for `/users/@me`; inspected auth/model code has no persistent Discord access or refresh token storage.

The current dependency checks that the Member row exists but not `Member.is_active`, current guild membership or required Discord role. Thus participant deactivation cannot immediately deny the cookie, and a removed Discord role can remain effective until session expiry. With a separate `UserAccount`, DB lookup per request can make account disable and role downgrade immediate without changing the cookie format's overall mechanism.

## Current AUTH_DISABLED behavior

`settings.auth_disabled` defaults false. `backend/app/main.py` lifespan rejects `AUTH_DISABLED=true` unless `ENVIRONMENT=development`, providing a production startup guard. `get_current_user()` checks the flag **first** and returns `AuthenticatedUser(member_id=None, name="dev-user", is_service=False, role=None)` without reading Bearer or cookie credentials. This principal passes the ordinary router-level dependency and can currently invoke ordinary planning, Member and Siege mutations because no role check follows. It does not supply a Member ID for `/members/me/preferences` or changelog operations that require one. The rate-limit key code also gives bypassed development calls independent keys, effectively avoiding the usual per-IP login/callback bucket. Scanner endpoints use `get_authenticated_scanner`, so this flag does not authenticate scanner ingestion.

**PROPOSED:** A development stub may explicitly satisfy VIEWER/MANAGER for local operational work, with tests and the existing startup guard. It must never satisfy ADMIN, create/rotate/revoke scanner credentials, manage user roles or grant ADMIN. ADMIN dependencies must require a real active human account even in development. Because `AUTH_DISABLED` currently wins before a real cookie, any future admin route using the old dependency alone would be unsafe.

## Current Member / MemberRole relationship

`backend/app/models/member.py` defines `Member` as a global Siege participant: unique name, nullable unique Discord ID, Discord username, `is_active`, optional power level, role, condition preferences and associations with Siege membership/positions. `MemberRole` in `backend/app/models/enums.py` is `heavy_hitter`, `advanced`, `medium`, `novice`. Services and frontend use it for participant/attack-day and board behavior; it has no ADMIN/MANAGER/VIEWER meaning. Nonetheless, human login requires a Member, the JWT subject is its PK, `/api/auth/me` returns its role, `/members/me/preferences` resolves its ID, and changelog seen state is tied to it. `Member` therefore currently represents both participant and login identity, while `is_active` is not an authentication disable flag.

**PROPOSED:** `UserAccount` owns application identity and permissions. A nullable, unique `member_id` link can preserve Member-specific `/me` preferences and changelog behavior for existing participants while allowing a human account without a Siege participant. Backfill this link only from an unambiguous Discord ID match; do not reuse username fallback or infer ADMIN from `MemberRole`. Define behavior for account-only users on Member-specific endpoints (prefer 404/empty state as appropriate), and move changelog seen state to account identity later if product users without Member must use it. Bot acting-Member behavior remains a separate path.

## Current frontend auth behavior

`frontend/src/context/AuthContext.tsx` loads `/api/auth/me` on app mount and stores its response in React state; it stores no token in local or session storage. Browser cookies carry the session. `frontend/src/components/RequireAuth.tsx` checks only whether a user object exists, and `frontend/src/App.tsx` wraps all Manager pages with the same gate. `Layout.tsx` shows navigation without permission checks. `LoginPage.tsx` begins the OAuth redirect; logout posts `/api/auth/logout` then navigates to `/login`. `frontend/src/api/client.ts` redirects to `/login` on non-auth API 401 responses and has no 403 handling. The existing `role` response field means `MemberRole`, so Task #5B should expose a distinct `app_role` and minimally hide/disable forbidden mutations while relying on backend enforcement. A hidden button is not authorization.

## Current API authorization matrix

`backend/app/main.py` supplies the principal dependency to the ordinary routers; the following is a route-group inventory, not a claim that each mutation has a separate permission check.

| Group / representative routes | Current boundary | Proposed minimum |
|---|---|---|
| Health, version, config; auth login/callback/logout | PUBLIC (`/auth/me` individually authenticated) | Preserve public endpoints; review config data |
| `/api/auth/me` | Human/bot/dev principal via `get_current_user` | Human account identity and distinct app role; scoped service behavior |
| `/api/scanner/snapshots` | SCANNER machine credential only | Preserve independent scanner boundary |
| Reference catalogs, Siege/board/building/post/Member reads, comparison, notification results, changelog reads | Authenticated human, bot service or dev stub | VIEWER or higher human; explicitly scoped bot reads |
| Siege lifecycle, buildings, board assignments, posts/conditions, Members/preferences, Siege members, global post priorities | Same authentication only; mutating routes lack app RBAC | MANAGER for ordinary planning; decide global catalog writes explicitly |
| Validation, auto-fill/attack-day/post-suggestion previews | Same authentication; some POSTs compute a preview | VIEWER if read-only and side-effect-free after verification |
| Auto-fill/attack-day/post-suggestion apply, images, notifications, Discord sync apply | Same authentication; writes and/or external effects | MANAGER with route-specific service authorization |
| Future user role/account and scanner credential administration | No HTTP routes yet | Real human ADMIN only |

Important existing routers include `api/sieges.py`, `buildings.py`, `board.py`, `posts.py`, `members.py`, `siege_members.py`, `lifecycle.py`, `validation.py`, `autofill.py`, `post_suggestions.py`, `attack_days.py`, `comparison.py`, `notifications.py`, `images.py`, `discord_sync.py`, `post_priority.py` and `changelog.py`. Authentication is router-wide, while role/verb enforcement is absent. The bot service Bearer path is accepted by that same broad dependency; Task #5B must preserve its needed integration operations through explicit service permissions rather than accidentally granting it human ADMIN.

## Security gaps

The central gap is `logged in == allowed` for ordinary mutations. Discord required role is checked only at login, and `MemberRole` is unrelated to app authority. Member deactivation does not deny requests; the JWT has no server-side revocation; logout clears only one browser cookie. A bot Bearer principal and development stub pass broad ordinary router protection. Future ADMIN endpoints would be exposed if they reused that dependency alone. OAuth state guards the callback, but cookie-authenticated mutating API calls have no separate CSRF token or Origin enforcement identified. SameSite=Lax helps against cross-site requests but does not replace an explicit CSRF review for same-site subdomains/admin actions. Login/callback settings and CORS deserve review during Task #5B, before security routes ship. Scanner ingestion already has its own bounded, scoped machine authentication.

## Proposed UserAccount model

Use one `user_account` table with `id` stable integer PK, `discord_user_id` non-null unique numeric Snowflake **string**, `display_name` non-null, `app_role` non-null, `is_active` non-null default true, `member_id` nullable unique FK to Member with `ON DELETE SET NULL`, `created_at` non-null UTC and `last_login_at` nullable UTC. An `updated_at` timestamp is useful for auditing changes but is not needed to decide current permissions; if included, update it on role/active changes. Keep Discord identity and display name distinct from the optional participant record. Do not store Discord OAuth tokens or plaintext credentials. This small schema permits later addition of an identity-provider mapping without treating Member or Discord roles as permanent authority.

`member_id` is a compatibility link, not authorization. If it introduces excessive coupling, Task #5B may instead resolve Member by exact Discord ID for Member-specific operations; it must avoid the bot username-fallback/backfill mechanism in human auth. Preserve application account history on disable and avoid cascading account deletion from participant records.

## Proposed RBAC model

Store exactly one mutually exclusive `app_role` per account: `viewer`, `manager`, `admin`, enforced with a DB CHECK plus application type validation. A normalized many-to-many user-role relation would add join and consistency rules without meeting a current requirement; introduce it only if independent concurrent roles later appear. Never derive `app_role` from Discord guild roles, `MemberRole`, bot identity or scanner capabilities. VIEWER reads Manager state; MANAGER runs normal Siege planning and operational mutations; ADMIN manages security/system state and can perform lower-role operations. Route assignment must be explicit, especially for global catalogs, notifications, service side effects and read-only POST previews.

## Role hierarchy

`ADMIN >= MANAGER >= VIEWER`. A `require_role(minimum)` helper should compare a central ordering, not scattered string checks. A real ADMIN can use regular planning routes, but an application role does not confer a Siege `MemberRole` or a participant record. A bot service and scanner identity are outside this hierarchy; they receive purpose-specific machine permissions. Development bypass may be allowed VIEWER/MANAGER but is outside the ADMIN tier.

## Proposed FastAPI authorization dependencies

Adapt `backend/app/dependencies/auth.py` so principal resolution distinguishes `human(UserAccount)`, `bot_service`, `dev_stub` and scanner (the last remains in its existing dependency). Human JWT decoding should lookup UserAccount and active state every request. Introduce reusable `require_human_user()`, `require_role(minimum)`, `require_manager()` and `require_admin()` dependencies; preserve a scoped bot dependency for existing bot calls. Use these at router or endpoint boundaries according to actual verbs, not only frontend visibility. Return 401 for missing/invalid/expired identity or disabled account so the client can reauthenticate; return 403 for an authenticated active account below the required role or a non-human principal trying a human-only route. Bot may use explicit service routes without acquiring a human role. Avoid silently extending today's broad `get_current_user()` to ADMIN.

## Proposed Discord admission behavior

Keep existing Discord OAuth, guild-membership check and configured required role as **login admission** initially, because the current product already requires them. They prove neither MANAGER nor ADMIN. Once an admitted Discord ID is known, load Manager `UserAccount` and decide application authorization from its DB role. No Discord Administrator-role-to-Manager-ADMIN mapping. Any future relaxation of required-role admission is a separate product/security decision; losing the Discord role during a session currently cannot be detected without checking Discord again or shortening the session.

## Unknown-user behavior

Evaluate A: auto-create active VIEWER after guild/role admission. It improves onboarding but allows every holder of that Discord role to read all Manager data and differs from today's explicit Member registration. Evaluate B: deny until an ADMIN/operator provisions `UserAccount`. It preserves the present fail-closed behavior and is recommended. An unknown user should receive a clear non-secret login denial, and admin provisioning can later create an account using a validated Discord ID. An account can exist without `Member`; Siege participant management stays independent. Existing Member Discord IDs should be seeded as VIEWER during migration, with operational roles granted explicitly before enforcement. Do not auto-create ADMIN or infer it from MemberRole/Discord roles.

## Disabled-user behavior

Reject disabled accounts at callback and on every authenticated request, regardless of an unexpired JWT. `Member.is_active` remains participant status and does not disable `UserAccount`. Disable should retain audit/history. A disabled account's copied JWT becomes unusable as soon as the DB change commits. Decide a last-active-ADMIN safety rule for role downgrade/disable so an installation is not locked out; the operator CLI should remain the recovery path.

## Session / role-refresh behavior

Keep signed HttpOnly cookie JWTs, change subject to `UserAccount.id`, and **never trust a JWT role claim for authorization**. The per-request DB load enforces current `app_role` and `is_active`; role downgrade and account disable take effect on the next request. Emit an explicit token type/version claim (for example `typ=manager-user-v2`) because legacy `sub` is a Member PK and numeric IDs may collide with new UserAccount IDs. Reject legacy cookies at the RBAC cutover and require re-login, or use a distinct cookie/verifier during a carefully bounded transition; never reinterpret an old Member JWT as a UserAccount JWT. Keep 24-hour JWT and shorter cookie initially. Logout still only removes the cookie unless Task #5B adds a server-side revocation/session-version mechanism; do not claim immediate revocation of a copied JWT. Review CSRF protection for new admin cookie-backed mutations.

## First ADMIN bootstrap

Use a trusted H3 local operator CLI/management command taking a validated Discord Snowflake, for example a conceptual `python -m app.cli users grant-admin <discord-user-id>`. Require operator filesystem/DB access, log the actor/action, operate transactionally, be idempotent, refuse ambiguous identity, and never print secrets. It may create an account with a placeholder display name if the Discord ID is not yet a Member; actual login still requires Discord admission. No public unauthenticated bootstrap route, source-coded personal ID or migration-seeded ADMIN. Before switching RBAC enforcement on, run this command and grant MANAGER to existing operators explicitly; retain CLI as lockout recovery and prevent deletion/downgrade of the last active ADMIN through normal API.

## Scanner provisioning integration

Task #5B supplies a durable `require_admin()` human dependency. Task #6 can then add `POST /api/admin/scanners` → existing `provision_scanner()` (one-time plaintext credential response), and rotate/revoke routes calling existing service functions. These routes must reject bot tokens, scanner tokens, development stubs and non-ADMIN humans. Provisioning changes the credential store through existing `ScannerIdentity` logic; it does not merge scanner machine auth with human sessions. No scanner provisioning HTTP route is implemented by this audit.

## Proposed migration 0015

Add `user_account` with the fields and constraints above. Prefer VARCHAR plus `CHECK (app_role IN ('viewer','manager','admin'))` over a PostgreSQL enum for three product roles; use a unique index/constraint on `discord_user_id`, unique nullable `member_id`, FK `ON DELETE SET NULL`, DB defaults for `is_active`, and timestamp defaults/UTC handling consistent with existing models. Do not edit 0014. Backfill one VIEWER account for each existing Member with a non-null unique Discord ID, set display name from the existing Member name as a migration fallback, link `member_id`, leave `last_login_at` null, and do **not** copy `Member.is_active` or MemberRole into account authorization. Members lacking Discord IDs are not human login accounts today and need no automatic account. Verify no duplicate/conflicting IDs and reconcile exceptions before enforcement. No hardcoded ADMIN seed.

Stage deploy as additive schema/backfill → operator ADMIN bootstrap and MANAGER grants → versioned UserAccount sessions plus `/auth/me` compatibility fields → explicit permission dependencies and minimal frontend app-role handling → reject legacy Member JWTs at cutover. Existing Member-specific endpoints and bot service calls need regression verification. If migration rollback is needed, first run compatible old application/auth and account for v2 cookies; database downgrade may drop the new table only after dependencies/data are intentionally discarded. A strict downgrade is data-losing, so production rollback should prefer retaining the additive table. This proposal is not a migration file.

## Task #5B implementation boundaries

Implement UserAccount model/migration, Discord callback lookup, v2 cookie principal, DB-loaded role/active checks, role dependencies, operator bootstrap, minimal account/admin management as needed for grants, frontend `app_role` consumption and explicit route classification. Preserve Discord OAuth and scanner machine credentials. Do not repurpose MemberRole, change Siege planning semantics or create scanner provisioning routes as part of this foundation. Before enforcement, resolve Member-specific `/me` and changelog coupling, bot-service route scopes and whether global post-priority writes are MANAGER or ADMIN. `AUTH_DISABLED` admin prohibition must be enforced even if other protected routes still accept a development principal.

## Task #5B test plan

Test Discord callback state/guild/required-role admission, unknown account denial, stable Discord-ID-to-UserAccount mapping, duplicate-ID DB constraint, account-only user and optional Member link, `last_login_at` updates, and disabled account denial at login and on every request. Test VIEWER reads and mutation 403s; MANAGER operational mutations and ADMIN-route 403s; ADMIN grants/admin actions and lower-role access; MemberRole independence; exact 401/403 handling; bot-specific permissions. Test a role downgrade and account disable after JWT issuance, legacy Member token collision rejection, expiry, cookie logout's documented client-only behavior, and CSRF defenses chosen for admin mutations. Test development bypass VIEWER/MANAGER behavior, production startup rejection, **never ADMIN**, and scanner credential authentication unaffected. Verify first-admin CLI idempotency and last-admin protection, migration/backfill on PostgreSQL, existing auth/Manager API, scanner auth/ingestion and Compare regressions. Frontend tests should cover distinct `app_role`, protected navigation/actions and 401/403 responses.

## Risks

Numeric legacy Member JWT subjects can collide with UserAccount IDs; token versioning and cutover are mandatory. Seeding everyone VIEWER creates an intentional operational downgrade until ADMIN grants MANAGER, so sequence grants before route enforcement. Today's bot token passes broad ordinary routers and needs route-by-route scope analysis. The optional Member link preserves current personal workflows but must not restore security coupling. Callback-only Discord role checks allow a removed role to persist for a session; whether that admission revocation must be immediate is unresolved. Cookie-backed admin mutations need a CSRF decision. Last-admin lockout and audit of security changes require explicit design. Existing tests often use `AUTH_DISABLED` and will need deliberate role fixtures rather than accidental broad access.

## Deferred items

Actual Task #5B implementation, migration 0015, Discord settings changes, session revocation store, stronger/continuous guild admission checks, additional identity providers, MFA, Scanner credential HTTP provisioning (Task #6), scanner heartbeat/leases/Fleet Management, SiegeScanner and extractor changes, Tower Bonus/Gear Audit, frontend redesign and planning-domain changes are deferred. The only repository artifact from this task is this audit/design document.
