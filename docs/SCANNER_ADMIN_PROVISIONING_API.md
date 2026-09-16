# Administracyjne zarządzanie Scannerami

API provisioningu jest dostępne wyłącznie dla aktywnej sesji HUMAN_ADMIN. MANAGER, VIEWER, BOT_SERVICE, SCANNER, użytkownik anonimowy i development stub nie mają dostępu.

## Kontrakt

- `POST /api/scanners` — tworzy stabilną identity i zwraca credential jeden raz;
- `GET /api/scanners` — zwraca bezpieczną listę identity;
- `GET /api/scanners/{scanner_id}` — zwraca bezpieczne metadata;
- `POST /api/scanners/{scanner_id}/rotate-credential` — natychmiast zastępuje credential i zwraca nowy plaintext jeden raz;
- `POST /api/scanners/{scanner_id}/revoke` — idempotentnie unieważnia credential bez usuwania identity i historii.

Przykładowe żądanie create:

```json
{
  "scanner_id": "ciachoo-main"
}
```

`scanner_id` jest stabilną tożsamością instalacji i musi składać się z liter ASCII, cyfr, kropki, podkreślenia lub łącznika. Nie jest credentialem.

Odpowiedzi list/detail/revoke zawierają wyłącznie `id`, `created_at`, `credential_revoked_at` oraz wyliczone `is_active`. Nie zawierają plaintextu, selectora, verifiera ani pełnego credentialu. Selector pozostaje wyłącznie technicznym kluczem wyszukiwania przechowywanym w bazie; API administracyjne nie potrzebuje go ujawniać.

## Credential

Format pozostaje zgodny z istniejącym uwierzytelnianiem snapshotów:

```text
ssm_scanner_<selector>.<secret>
```

Selector służy do wyszukania identity i nie jest sekretem. Część secret ma wysoką entropię. Baza zapisuje wyłącznie SHA-256 verifier części secret, a porównanie odbywa się przez `secrets.compare_digest`. Plaintext występuje tylko w odpowiedzi create albo rotate i musi zostać od razu bezpiecznie zapisany przez administratora.

Rotacja zachowuje `scanner_id`, unieważnia poprzedni credential w chwili zatwierdzenia transakcji i aktywuje nowy. Rotacja wcześniej unieważnionej identity ponownie ją aktywuje. Revoke zachowuje wszystkie `scanner_snapshot`, `observed_building` i `observed_post`.

Klucz główny `ScannerIdentity.id` jest ostateczną ochroną przed równoległym utworzeniem tej samej identity. Konflikt zapisu jest wycofywany i zwracany jako kontrolowane HTTP 409 bez ujawnienia wygenerowanego credentialu. Równoległe rotacje mają semantykę „ostatni zatwierdzony zapis wygrywa”; każda rotacja zapisuje selector, verifier i stan revoke atomowo, więc nie istnieje stan częściowego credentialu ani dwa aktywne credentiale.

Task #6 nie dodaje heartbeat, `last_seen_at`, leases, Fleet Management, fingerprintu maszyny ani Windows handshake. Te elementy pozostają poza zakresem do Task #7.
