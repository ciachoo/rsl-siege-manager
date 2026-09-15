# Scanner Ingestion Foundation

## Decision summary

Use the existing FastAPI/backend service/database boundary. No current isolation or scale requirement justifies a Coordinator. This task establishes an internal persistence contract, without a public ingestion route.

## Existing Manager boundaries

`Siege` is the rotation boundary; its date is nullable. `Building` type/number and `Post` links are Manager identities. `PostCondition` is a global catalog but `post_active_condition` is per-Siege planning. Cleanup #1 historical Compare stays separate and unchanged.

## Planning state vs observed state

Four additive tables are proposed: `scanner_identity`, `scanner_snapshot`, `observed_building`, `observed_post`. Scanner writes only these tables. No planning column or association is altered.

## Scanner identity

`scanner_identity.id` is a stable installation identifier, distinct from mutable hostname. The server must bind it to a future scanner-scoped credential; this internal foundation does not issue credentials. One installation works now; many installations can be added later.

## Snapshot envelope

`schema_version`, `snapshot_id`, `scanner_id`, `scanner_version`, `observed_at`, optional `siege_id`, optional opaque `cycle_ref`, optional building/Post observations. Omitted/null category means unknown coverage; an explicit `[]` means the scanner positively supplied an empty visible collection, but does not prove complete Siege absence. Example with fake values:

```json
{
  "schema_version": 1,
  "snapshot_id": "example-snapshot-001",
  "scanner_id": "example-installation-001",
  "scanner_version": "0.1.0",
  "observed_at": "2026-09-15T10:00:00Z",
  "siege_id": null,
  "cycle_ref": "example-cycle-correlation",
  "buildings": [{"external_building_id": "example-building-3001", "level": 2, "is_broken": null}],
  "posts": [{"external_post_id": "example-post-3001", "modifier_ids": ["example-modifier-X"]}]
}
```

The example describes the internal contract, not a frozen SiegeScanner payload. Raid credentials, session tokens, raw responses and memory are excluded.

## Siege/cycle association

Only an explicit, existing Manager `siege_id` is accepted as matched. Without one, snapshot stays `unmatched` with `siege_id=NULL`, preserving `cycle_ref` for later review. Dates and current active Siege never cause automatic attachment. Ambiguous correlation remains unresolved; future manual mapping needs an audit trail.

## Observed building model

`observed_building` stores snapshot FK, opaque external building ID, nullable level and nullable broken state. No automatic mapping to `Building.id` or type/number is claimed.

## Observed Post condition model

`observed_post` stores snapshot FK, opaque external Post ID and nullable JSON array of opaque modifier IDs. `NULL` means not observed; `[]` means observed empty. Each snapshot is retained, so Post conditions can differ by rotation. No write to `post_active_condition` occurs. A future modifier-to-catalog map requires Scanner research.

## Provenance

Every observation points to a snapshot. Snapshot records source installation, scanner version, observation and receipt times, optional Siege, correlation reference and association status. It retains a canonical content digest.
The snapshot also retains category-presence flags for buildings and Posts.

## Idempotency

Unique `(scanner_id, snapshot_id)` is the deduplication key. Identical retries return the existing snapshot; same key with different content is a conflict. The database uniqueness constraint is the final concurrency guard. Timestamps are not keys.

## UNKNOWN semantics

Absent/null field means unobserved. False is observed false. Zero is an actual zero only where the domain permits it. A null Post modifier collection is unknown; an empty collection is positively observed empty. Omitted observations cannot establish absence of a building/Post. Complete category coverage is deferred until Scanner can state it reliably.

## Freshness / timestamps

`observed_at` comes from Scanner; `received_at` is server time. Both are stored separately in UTC. A future authenticated API should bound future clock skew, stale submissions and payload size; no guessed freshness threshold is imposed now.

## Authentication boundary

Existing Bearer token is bot-oriented and `get_current_user` also accepts browser sessions/dev bypass. Future scanner delivery needs a scanner-specific scoped credential, bound server-side to installation identity, stored only as a hash/verification reference, with rotation and revocation. No temporary public endpoint is added.

## Database changes

One additive revision `0013` creates four tables and constraints, with no changes to planning tables. Observations depend on snapshots, not on deletable planning buildings or Posts.

## API changes

None. `SnapshotEnvelope` and `record_snapshot` are internal schema/service boundaries; authenticated delivery is deferred.

## Tests

Focused service/model tests cover planning isolation, per-rotation history, retry deduplication, unknown/empty/false, invalid level zero, source/timestamp provenance and unresolved association. Existing Compare tests remain in the broad regression suite.
Revision `0013` upgrade/downgrade was checked on SQLite. PostgreSQL migration execution remains unverified in this local environment.

## Deferred Scanner-dependent fields

Raid build, stable cycle IDs, building status vocabulary, category completeness, exact Post IDs/modifier mapping, payload limits and freshness thresholds require SiegeScanner evidence. Tower bonus persistence is unverified. Teams/champions/gear are not modeled.

## Future evolution

Heartbeat, capabilities, version compatibility and ACTIVE/STANDBY leases can extend identity metadata without changing snapshot keys. Scanner Validation can compare observed versus planning data with UNKNOWN. Tower Bonus Recommendation and Siege Defense Gear Audit can add typed observation tables once evidence exists. Fleet Management can add leases and health records later without replacing the ingestion foundation.
