# Scanner Observations — read-only API

API udostępnia człowiekowi historyczne fakty zapisane przez [`SCANNER_INGESTION_PROTOCOL.md`](SCANNER_INGESTION_PROTOCOL.md). Nie jest API provisioningu, planowania ani zarządzania flotą.

## Authorization

Wszystkie trasy wymagają centralnego `require_viewer`. HUMAN_VIEWER, HUMAN_MANAGER i HUMAN_ADMIN mają dostęp. Użytkownik anonimowy, SCANNER i BOT_SERVICE są odrzucani. Development `AUTH_DISABLED` zachowuje istniejącą semantykę dostępu VIEWER/MANAGER.

Odpowiedzi nie zawierają credentialu, selectora, verifiera, stanu revoke, nagłówka Authorization, secretów ani wewnętrznego `content_digest`. Revoke nie ukrywa historycznego evidence.

## Endpointy

### `GET /api/scanner-observations/snapshots`

Zwraca lekką listę metadata bez `buildings` i `posts`.

Query params:

- `limit`: 1–100, domyślnie 50;
- `offset`: integer `>= 0`, domyślnie 0;
- `scanner_id`: opcjonalna dokładna identity Scannera;
- `siege_id`: opcjonalne dokładne DB association;
- `association_status`: opcjonalnie `matched` albo `unmatched`.

Kolejność jest deterministyczna: `observed_at DESC`, następnie wewnętrzne `id DESC`. Nieznany filtr zwraca pustą listę.

### `GET /api/scanner-observations/snapshots/latest`

Zwraca pierwszy snapshot według tej samej kolejności. Obsługuje filtry `scanner_id`, `siege_id` i `association_status`. Brak pasującego snapshotu zwraca 404. „Latest” nie oznacza najlepszego Scannera, lidera ani najbardziej wiarygodnego evidence.

### `GET /api/scanner-observations/snapshots/{snapshot_db_id}`

Zwraca metadata oraz deterministycznie uporządkowane children. `snapshot_db_id` jest wewnętrznym integer PK, odmiennym od zewnętrznego `snapshot_id`. Nieistniejące ID zwraca 404.

Buildings są uporządkowane przez `external_building_id`, a Posts przez `external_post_id`, z wewnętrznym ID jako niewidocznym tie-breakerem. `modifier_ids` pozostają w zapisanej kolejności.

## Summary response

```json
{
  "id": 42,
  "snapshot_id": "synthetic-capture-001",
  "scanner_id": "windows-scanner-example",
  "scanner_version": "0.1.0",
  "schema_version": 1,
  "observed_at": "2026-09-16T12:00:00Z",
  "received_at": "2026-09-16T12:00:01Z",
  "siege_id": null,
  "association_status": "unmatched",
  "cycle_ref": "synthetic-cycle",
  "buildings_present": false,
  "posts_present": true
}
```

## Detail response

Detail rozszerza summary o:

```json
{
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

## UNKNOWN i obecność kategorii

Puste child arrays zawsze należy interpretować razem z flagą presence:

- `buildings_present=false` i `buildings=[]`: kategoria nie była obserwowana;
- `buildings_present=true` i `buildings=[]`: kategoria była obserwowana jako pusta;
- analogicznie dla Posts;
- `level=null`, `is_broken=null` i `modifier_ids=null`: UNKNOWN;
- `is_broken=false`: znane false;
- `modifier_ids=[]`: znany pusty zestaw.

API nie zastępuje UNKNOWN wartością domyślną.

## Siege association

`matched` oznacza wyłącznie zapisane `siege_id != null`. `unmatched` oznacza `siege_id == null`. API nie używa `cycle_ref`, czasu obserwacji, aktywnego Siege ani lifecycle do zgadywania association i nie zwraca pełnego obiektu Siege.

## Query shape i read-only invariant

LIST i LATEST nie ładują children. DETAIL używa dwóch zbiorczych `selectinload` dla Buildings i Posts, bez zapytania per child. Endpointy nie wykonują flush ani commit, nie aktualizują last-seen i nie zmieniają Scanner identity, snapshots, observations ani planned state.

## Świadomie poza zakresem

API nie wybiera „najlepszego” Scannera, nie wzbogaca modifier IDs, nie mapuje observations na planned conditions, nie wykonuje automatic Siege matching i nie implementuje Web UI, Fleet Management, heartbeat, leases, capabilities ani mutation endpoints.
