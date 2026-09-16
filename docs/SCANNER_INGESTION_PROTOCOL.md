# Scanner → Manager — protokół ingestion v1

Ten dokument opisuje pierwszy stabilny kontrakt HTTP dla przyszłego klienta Windows SiegeScanner. Opisuje wyłącznie funkcje istniejące w Managerze. Endpoint nie służy do zarządzania flotą ani do zmiany planu Siege.

## Endpoint i uwierzytelnianie

`POST /api/scanner/snapshots` przyjmuje `Content-Type: application/json` oraz `Authorization: Bearer <scanner-credential>`. Credential jest wydawany jednorazowo przez HUMAN_ADMIN poprzez `POST /api/scanners`; opisowo ma format `ssm_scanner_<selector>.<secret>`. Klient przechowuje cały credential jak sekret. Manager zapisuje tylko selector i SHA-256 verifier części secret.

Poświadczenie jest przypisane do dokładnego `ScannerIdentity.id`. Pole `scanner_id` w payloadzie musi być identyczne z identity uwierzytelnioną credentialem. Sesja człowieka, BOT_SERVICE i development bypass nie uwierzytelniają ingestion.

## Canonical request schema

Wszystkie niewymienione pola są zabronione.

| Pole | Status | Kontrakt |
|---|---|---|
| `schema_version` | REQUIRED | integer `>= 1`; serwer obecnie akceptuje wyłącznie `1` |
| `snapshot_id` | REQUIRED | string 1–128 znaków, generowany przez Scanner; stabilny dla retry tej samej obserwacji |
| `scanner_id` | REQUIRED | string 1–128 znaków; musi odpowiadać credentialowi |
| `scanner_version` | REQUIRED | niepusty string do 64 znaków |
| `observed_at` | REQUIRED | timestamp ze strefą czasową; maksymalnie 10 minut w przyszłość względem Managera |
| `siege_id` | OPTIONAL, NULLABLE | integer `>= 1`; tylko jawne ID Managera albo `null`/brak |
| `cycle_ref` | OPTIONAL, NULLABLE | string do 256 znaków; metadane korelacyjne, nie uruchamiają heurystyki |
| `buildings` | OPTIONAL, NULLABLE | do 100 unikalnych obserwacji; brak/`null` oznacza kategorię niezaobserwowaną, `[]` oznacza zaobserwowaną pustą kategorię |
| `posts` | OPTIONAL, NULLABLE | do 100 unikalnych obserwacji; taka sama semantyka obecności jak `buildings` |

Obserwacja building:

| Pole | Status | Kontrakt |
|---|---|---|
| `external_building_id` | REQUIRED | niepusty string do 128 znaków, unikalny w kategorii snapshotu |
| `level` | OPTIONAL, NULLABLE | integer `>= 1`; `null` oznacza UNKNOWN |
| `is_broken` | OPTIONAL, NULLABLE | boolean; `null` oznacza UNKNOWN, `false` jest znaną wartością |

Obserwacja post:

| Pole | Status | Kontrakt |
|---|---|---|
| `external_post_id` | REQUIRED | niepusty string do 128 znaków, unikalny w kategorii snapshotu |
| `modifier_ids` | OPTIONAL, NULLABLE | najwyżej 3 różne, niepuste stringi do 128 znaków; `null` oznacza UNKNOWN, `[]` oznacza zaobserwany brak modifierów |

Kolejność `modifier_ids` jest zachowywana w JSON observation. Manager nie mapuje tych wartości na globalny katalog condition definitions i nie utrwala permanentnego przypisania Post → modifiers.

## Przykład syntetyczny

```json
{
  "schema_version": 1,
  "snapshot_id": "capture-2026-09-16T12:00:00Z-001",
  "scanner_id": "windows-scanner-example",
  "scanner_version": "0.1.0",
  "observed_at": "2026-09-16T12:00:00Z",
  "siege_id": null,
  "cycle_ref": "synthetic-cycle-reference",
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
      "modifier_ids": ["modifier-example-a", "modifier-example-b"]
    }
  ]
}
```

## Odpowiedź i association

Nowy snapshot zwraca HTTP 201, a identyczny retry HTTP 200:

```json
{
  "snapshot_id": "capture-2026-09-16T12:00:00Z-001",
  "status": "created",
  "received_at": "2026-09-16T12:00:01Z",
  "association_status": "unmatched",
  "siege_id": null
}
```

`siege_id=null` albo brak pola zapisuje snapshot jako `unmatched`. Manager nie wybiera najnowszego, aktywnego ani najbliższego Siege. Jawne istniejące `siege_id` zapisuje `matched`; nieistniejące jawne ID jest odrzucane. `cycle_ref` jest zachowywany, ale sam nie tworzy association.

## Snapshot identity i retry

Klucz idempotencji to para `(uwierzytelniony scanner_id, snapshot_id)`. Scanner generuje `snapshot_id` i musi ponowić po timeoutie te same znormalizowane fakty, włącznie z `observed_at`, semantyką obecności kategorii i kolejnością list. Kolejność kluczy JSON nie ma znaczenia, a brak pola i jawne `null` mogą być równoważne tam, gdzie schema ma domyślną wartość `null`. Identyczna znormalizowana treść zwraca istniejący snapshot jako `status="duplicate"` bez nowych `ObservedBuilding` lub `ObservedPost`. To samo zewnętrzne `snapshot_id` może być użyte przez inną Scanner identity. Ponowne użycie klucza przez ten sam Scanner z inną treścią zwraca konflikt.

## Persistence i granica transakcji

Jeden commit obejmuje `ScannerSnapshot` oraz wszystkie jego `ObservedBuilding` i `ObservedPost`. Błąd constraintu wycofuje cały batch. Snapshot przechowuje osobno czas obserwacji i czas odbioru, obecność kategorii, digest treści oraz opcjonalne association.

Ingestion nie zmienia `Siege`, `Building`, `Post`, planned Post conditions, `SiegeMember`, pozycji Board, preferencji Memberów, lifecycle ani danych wykorzystywanych przez Compare. Observed state pozostaje historycznym dowodem konkretnego snapshotu/cyklu.

## Limit i błędy

Maksymalny request body wynosi 256 KiB (`262144` bajty), niezależnie od `Content-Length`; większy payload zwraca 413.

| Przypadek | HTTP | Stabilna semantyka |
|---|---:|---|
| nowy poprawny snapshot | 201 | `status="created"` |
| identyczny retry | 200 | `status="duplicate"` |
| brak Authorization | 401 | scanner credential wymagany |
| malformed, unknown, wrong, revoked lub stary credential | 401 | wspólne `Invalid scanner credential`, bez informacji o przyczynie |
| `scanner_id` inny niż credential | 403 | identity mismatch |
| malformed JSON lub schema validation | 422 | invalid envelope |
| nieobsługiwany `schema_version` | 422 | unsupported version |
| nieistniejące jawne `siege_id` | 422 | unknown explicit association |
| ten sam klucz z inną treścią | 409 | snapshot identity conflict |
| payload ponad limit | 413 | snapshot exceeds size limit |
| błąd serwera/bazy | 5xx | brak potwierdzenia zapisu; klient może bezpiecznie ponowić identyczny snapshot |

Nie należy rozróżniać błędnego secretu, nieznanego selectora i revoke na podstawie odpowiedzi. Klient nie może logować credentialu ani nagłówka Authorization. Manager nie loguje Authorization ani pełnego payloadu.

## Rotate i revoke

Rotate zachowuje `ScannerIdentity.id` i historię, natychmiast unieważnia stary credential oraz zwraca nowy plaintext jeden raz. Revoke zachowuje identity i historyczne snapshoty, ale każde kolejne ingestion tym credentialem otrzymuje 401. Retry wymaga aktualnie aktywnego credentialu nawet wtedy, gdy snapshot już istnieje.

## Brak read API

Manager ma obecnie persistence foundation, ale nie udostępnia osobnego API do odczytu snapshotów/observations dla Web UI. Minimalne read API i prezentacja evidence są następnym krokiem; nie są częścią protokołu ingestion v1.
