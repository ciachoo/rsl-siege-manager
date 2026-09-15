# Scanner Ingestion API

## Security boundary

`POST /api/scanner/snapshots` is mounted with a Scanner-only credential dependency, outside normal browser/bot router auth. `AUTH_DISABLED` does not bypass it. The route accepts normalized facts only. Extra fields such as Raid JWT, signin-session, raw HTTP data or process memory fail validation.

## Scanner provisioning

`provision_scanner` is an internal service for a trusted operator context. It creates a stable installation ID (or provisions an existing Task #3 identity) and returns a credential once. **No provisioning HTTP route is exposed.** Current Manager auth has no persistent admin entitlement: `MemberRole` is a player tier and Discord's required role is checked only at login. Before an admin HTTP route can issue credentials, the product must define a durable admin grant and require a real user session with that grant. Bot principals and the `AUTH_DISABLED` stub must not qualify.

## Credential format/storage

Header secret format: `ssm_scanner_<128-bit-selector>.<256-bit-random-secret>`. The selector is a lookup key; `scanner_identity` stores only a SHA-256 verifier of the high-entropy secret, not the plaintext credential. SHA-256 is used as a verifier for random 256-bit material, not as a password hash for human-chosen secrets. The scanner installation ID stays separate from the selector.

## Credential rotation

`rotate_scanner_credential` issues a new selector/secret for the same installation ID and replaces the verifier atomically. The old credential immediately fails. The new plaintext is returned once to the trusted caller.

## Revocation

`revoke_scanner` sets `credential_revoked_at`; ingestion rejects that credential. The identity and historical snapshots remain. A deliberate rotation can re-enable the installation with a new credential.

## Authentication request

`Authorization: Bearer <scanner-credential>`. The server resolves one Scanner identity from the credential. Envelope `scanner_id` must equal that identity; it is never authentication proof.

## Snapshot endpoint

`POST /api/scanner/snapshots` reads a bounded JSON body, validates schema version and time, then calls the existing transactional evidence service. It does not reconcile or mutate Manager planning data.

## Request example

Fake values only:

```http
POST /api/scanner/snapshots
Authorization: Bearer ssm_scanner_example-selector.example-secret-not-real
Content-Type: application/json

{"schema_version":1,"snapshot_id":"example-snapshot-1","scanner_id":"scanner_example_123","scanner_version":"0.1.0","observed_at":"2026-09-15T10:00:00Z","siege_id":null,"cycle_ref":"example-cycle","buildings":[{"external_building_id":"example-building","level":2,"is_broken":null}],"posts":[{"external_post_id":"example-post","modifier_ids":["example-modifier"]}]}
```

## Response examples

Created (201): `{"snapshot_id":"example-snapshot-1","status":"created","received_at":"2026-09-15T10:01:00Z","association_status":"unmatched","siege_id":null}`.

Idempotent retry (200): same metadata with `"status":"duplicate"` and the original `received_at`.

Matched (201/200): `"association_status":"matched","siege_id":42` after an explicit existing Manager Siege ID.

Conflict (409): `{"detail":"Snapshot identity conflict"}`. Unauthorized (401): `{"detail":"Invalid scanner credential"}` or missing-credential detail. Unmatched is a valid accepted result with `siege_id:null`.

## Schema version

Only `schema_version=1` is accepted. Other versions return 422.

## Request bounds

Actual streamed body is limited to 256 KiB, including when `Content-Length` is missing or false. IDs: installation and snapshot 128 characters, scanner version 64, cycle reference 256, building/Post external IDs 128, modifier IDs 128. At most 100 building and 100 Post observations, and at most three distinct modifier IDs per Post. Duplicate external IDs inside one category fail validation. These are defensive API limits, not claims about Raid internals.

## Timestamp rules

`observed_at` must be timezone-aware and cannot exceed Manager time by more than 10 minutes. Old offline retries are accepted. Manager records `received_at` separately in UTC and never replaces observation time.

## Siege association

An explicit existing `siege_id` gives `matched`; unknown explicit ID returns 422. Omitted ID gives `unmatched`. Active Siege, nearest date and `cycle_ref` never cause automatic attachment.

## UNKNOWN semantics

Omitted/null category is unknown; explicit `[]` records a positively supplied empty visible collection, without asserting full Siege absence. Nullable observed building fields remain unknown; `false` is observed false. Null Post modifiers differ from empty modifiers.

## Idempotency

Unique `(scanner_id,snapshot_id)` plus canonical content digest. Identical retry returns 200; changed content for the same key returns 409. Database uniqueness is the concurrency guard.

## Transaction semantics

Snapshot and children commit together. On a uniqueness race the service rolls back, reads the winning snapshot and applies digest comparison. No partial children are committed.

## Logging / secret handling

Scanner result logs include installation ID, snapshot ID, result, association and counts. Existing request logging includes method/path/status/request ID. Neither path logs Authorization, credential, raw body or Raid authentication material. Acknowledgements contain no verifier or plaintext secret.

## Error/status codes

201 created; 200 identical retry; 401 missing/invalid/revoked credential; 403 credential/body Scanner ID mismatch; 409 reused snapshot key with different content; 413 oversized body; 422 malformed/unsupported envelope, future observation time or unknown explicit Siege ID.

## Deferred

Admin HTTP provisioning awaits a durable Manager admin grant. Heartbeat, leases, fleet/version policy, automatic cycle matching, Raid ID maps, planning reconciliation, teams, gear and Tower Bonus are outside this slice. PostgreSQL migration `0014` will be validated separately on H3 before commit.
