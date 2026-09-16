# Siege Scanner Evidence — read-only projection

Endpoint przedstawia jeden jawny Scanner snapshot w kontekście istniejącego Siege. Jest projekcją przy odczycie: nie kopiuje observations do planned state i nie zastępuje historii dostępnej przez [`SCANNER_OBSERVATIONS_READ_API.md`](SCANNER_OBSERVATIONS_READ_API.md). Dane powstają zgodnie z [`SCANNER_INGESTION_PROTOCOL.md`](SCANNER_INGESTION_PROTOCOL.md).

## Endpoint i authorization

`GET /api/sieges/{siege_id}/scanner-evidence` wymaga centralnego `require_viewer`. Dostęp mają HUMAN_VIEWER, HUMAN_MANAGER, HUMAN_ADMIN oraz development principal zgodnie z istniejącą semantyką `AUTH_DISABLED`. Anonymous, SCANNER i BOT_SERVICE są odrzucani.

Nieistniejący `siege_id` zwraca 404, a nieprawidłowy path parameter 422.

## Wybór source snapshot

Projection bierze wyłącznie rekordy z jawnym:

```text
ScannerSnapshot.siege_id == requested siege_id
```

Spośród nich wybiera dokładnie jeden snapshot przez:

```text
observed_at DESC
id DESC
LIMIT 1
```

Wybór odbywa się across all provisioned Scanner identities. Jest bezpieczny jako minimalna semantyka, ponieważ nie scala observations, nie przyznaje Scannerowi priorytetu i jawnie zwraca `scanner_id` wybranego źródła. Nie istnieje leader election, trust score, ACTIVE/STANDBY ani fallback do unmatched evidence. Nowszy unmatched snapshot lub snapshot innego Siege nie wpływa na wynik.

## Evidence istnieje

```json
{
  "siege_id": 123,
  "has_evidence": true,
  "source_snapshot": {
    "id": 42,
    "snapshot_id": "synthetic-capture-001",
    "scanner_id": "windows-scanner-example",
    "scanner_version": "0.1.0",
    "schema_version": 1,
    "observed_at": "2026-09-16T12:00:00Z",
    "received_at": "2026-09-16T12:00:01Z",
    "cycle_ref": "synthetic-cycle"
  },
  "buildings_present": true,
  "posts_present": true,
  "buildings": [
    {
      "external_building_id": "raid-building-example",
      "level": null,
      "is_broken": false
    }
  ],
  "posts": [
    {
      "external_post_id": "raid-post-example",
      "modifier_ids": ["modifier-b", "modifier-a"]
    }
  ]
}
```

Source metadata nie zawiera credential fields, stanu revoke ani digestu. `observed_at` jest zwracany bez clock correction.

## Brak evidence

Istniejący Siege bez jawnie matched snapshotu zwraca 200:

```json
{
  "siege_id": 123,
  "has_evidence": false,
  "source_snapshot": null,
  "buildings_present": null,
  "posts_present": null,
  "buildings": [],
  "posts": []
}
```

Presence ma wartość `null`, ponieważ brak source snapshotu nie oznacza tego samego co snapshot z `buildings_present=false` albo `posts_present=false`. Endpoint nie zwraca planned state jako zastępczego evidence i nie zgaduje po `cycle_ref`, czasie, dacie Siege ani lifecycle.

## Presence i UNKNOWN

Gdy source snapshot istnieje:

- `present=false` plus `[]` oznacza kategorię niezaobserwowaną;
- `present=true` plus `[]` oznacza kategorię zaobserwowaną jako pustą;
- `level=null`, `is_broken=null` i `modifier_ids=null` oznaczają UNKNOWN;
- `is_broken=false` oznacza znane false;
- `modifier_ids=[]` oznacza znany pusty zestaw.

Buildings i Posts są deterministycznie uporządkowane po external ID, z niewidocznym internal child ID jako tie-breakerem. Kolejność `modifier_ids` pozostaje dokładnie taka, jak w historycznym JSON evidence.

## Planned-domain separation

Manager nie posiada jawnego mapowania external building/post IDs na planned `Building` lub `Post`. Projection zwraca surowe external IDs. Nie dopasowuje po numerze, nazwie, pozycji ani kolejności i nie mutuje Buildings, Posts, conditions, assignments, members lub lifecycle.

Observed Post modifiers pozostają per-snapshot/per-cycle evidence. Endpoint nie aktualizuje planned conditions, nie zmienia globalnego katalogu i nie wzbogaca IDs o display names.

## Revoked Scanner i historia

Credential lifecycle jest niezależny od evidence validity. Snapshot może pozostać source projection po późniejszym revoke Scannera. Starsze snapshots nie są usuwane ani nadpisywane i nadal są dostępne przez Scanner Observations Read API.

## Query i read-only invariant

Endpoint sprawdza istnienie Siege, a następnie wykonuje bounded query `WHERE siege_id`, deterministic ordering i `LIMIT 1`, z dwoma zbiorczymi `selectinload` dla children. Nie ładuje całej historii i nie wykonuje query per child.

Endpoint nie wykonuje INSERT, UPDATE, DELETE, flush ani commit. Nie aktualizuje last-seen, Scanner identity, snapshots, Siege ani planned state.

## Świadomie poza zakresem

Projection nie implementuje Web UI, Fleet Management, scanner priority, heartbeat, leases, Windows handshake, automatic Siege matching, modifier enrichment, building/post names, Tower Bonus, Gear Audit ani recommendations.
