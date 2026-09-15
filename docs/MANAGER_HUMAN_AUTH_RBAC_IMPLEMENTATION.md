# Uwierzytelnianie użytkowników i RBAC Managera — implementacja #5B

Podstawa: Task #5B na HEAD `72ed626aec8ea6a0479ccdffb5a7260643e7a407`. Zmiany #5A/#5B pozostają niezatwierdzone w Git. Migracja `0015` została zastosowana na H3 w PostgreSQL 18.6; nie wykonywano destrukcyjnego downgrade.

## Architektura i tożsamość

Discord OAuth potwierdza tożsamość, członkostwo w guild i wymaganą rolę Discord. `UserAccount` przechowuje rolę aplikacyjną oraz stan aktywności człowieka. Ciasteczko JWT wskazuje `UserAccount`; Bearer bota i poświadczenia skanera pozostają oddzielnymi tożsamościami. Zwykłe routery nadal korzystają z szerokiego `get_current_user()`, ale reprezentatywne mutacje Siege i Buildings wymagają MANAGER. Pełna klasyfikacja tras należy do #5C.

`backend/app/models/user_account.py` definiuje tabelę `user_account`: całkowite `id`, unikalne `discord_user_id` jako ciąg cyfr, `display_name`, `app_role` z wartościami `viewer`, `manager`, `admin`, `is_active`, opcjonalny unikalny `member_id` z FK `ON DELETE SET NULL`, `created_at` i opcjonalny `last_login_at`. Rola aplikacyjna i aktywność konta są niezależne od `MemberRole` i `Member.is_active`. Tokeny OAuth Discorda nie są przechowywane.

## OAuth i dopuszczenie do logowania

`backend/app/api/auth.py` zachowuje ciasteczko `oauth_state`, porównanie stanu odporne na różnice czasowe, zakres `identify`, limity żądań login/callback, sprawdzenie guild przez sidecar oraz dokładne sprawdzenie `DISCORD_REQUIRED_ROLE`. Na H3 wymagana rola to `Bimbrownik`. Po przejściu tych kontroli callback wyszukuje aktywne, wcześniej utworzone `UserAccount` po dokładnym Discord ID. Nieznane i nieaktywne konta są odrzucane; callback nie tworzy konta ani nie wyprowadza roli Managera z roli Discord.

Po udanym OAuth callback aktualizuje `UserAccount.display_name` z bieżącego `global_name` Discorda, a jeśli go brak — z `username`. W tej samej transakcji zapisuje `last_login_at`. Nie zmienia `app_role`, `is_active` ani `member_id`. Nazwa tymczasowa używana przez lokalny bootstrap nie pozostaje normalną nazwą po logowaniu.

## Sesja i uprawnienia

JWT v2 ma `typ="manager-user-v2"`, `sub=str(UserAccount.id)`, `name`, `iat` i `exp` po 24 godzinach. Ciasteczko `session` pozostaje HttpOnly, SameSite=Lax, ma 23-godzinny max-age i jest Secure poza środowiskiem development. Dawne JWT wskazujące Membera nie mają wymaganego `typ` i otrzymują 401. Konto i jego bieżąca rola/aktywność są odczytywane z bazy przy każdym żądaniu; rola z JWT nie jest źródłem autoryzacji. Wylogowanie usuwa ciasteczko klienta; skopiowany JWT nie jest unieważniany po stronie serwera przed wygaśnięciem.

Hierarchia to ADMIN >= MANAGER >= VIEWER, bez związku z `MemberRole`. `backend/app/dependencies/auth.py` udostępnia `require_human_user`, `require_role(minimum)`, `require_viewer`, `require_manager` i `require_admin`. Brak, błędna lub wygasła sesja oraz nieaktywne konto zwracają 401; aktywny użytkownik ze zbyt niską rolą i tożsamość niebędąca człowiekiem na trasie wymagającej roli zwracają 403. ADMIN wymaga rzeczywistego aktywnego `UserAccount`.

`AUTH_DISABLED` pozostaje ograniczone do development przez kontrolę przy starcie. Lokalna tożsamość development ma uprawnienia odpowiadające MANAGER dla wybranych operacji, lecz nigdy nie spełnia `require_admin`. Flaga nie uwierzytelnia skanera. Powiązanie `member_id` jest opcjonalne: konto ADMIN bez Membera może się zalogować, natomiast osobiste operacje `/members/me/preferences` i changelog wymagające uczestnika zwracają 404 bez powiązania. Mechanizm bota działającego w imieniu Membera pozostaje osobny.

Botowy Bearer ma `principal_type="bot_service"` i nie uzyskuje ludzkiej roli aplikacyjnej. Poświadczenia skanera nadal obsługuje oddzielne `get_authenticated_scanner`; ciasteczko człowieka, token bota i bypass development nie uwierzytelniają `/api/scanner/snapshots`. Skaner nie spełnia `require_admin`.

## Bootstrap i ochrona żądań

Pierwszy ADMIN jest nadawany z zaufanej powłoki operatora po migracji: `python -m app.cli users grant-admin <numeric-discord-user-id>`. `grant-manager` przygotowuje operatorów. CLI dopasowuje dokładny Discord ID, działa transakcyjnie i idempotentnie, nie wypisuje poświadczeń oraz może utworzyć konto bez Membera. Nie ma publicznego endpointu bootstrap. Obniżenie roli ostatniego aktywnego ADMIN jest odrzucane. CLI pozostaje drogą odzyskania dostępu.

`cookie_origin_guard` odrzuca mutujące żądania z ciasteczkiem bez `Origin` lub spoza `ALLOWED_ORIGINS`; dodatkowy błędny Bearer nie omija tej kontroli. Frontend i API działają pod tym samym origin przez proxy Vite/nginx. Mechanizm `oauth_state` chroni callback niezależnie od kontroli Origin. Przed przyszłymi mutacjami administracyjnymi należy zweryfikować politykę origin dla wdrożenia.

`/api/auth/me` zwraca odrębne `app_role` i `user_account_id`, zachowując uczestnicze `role`. Frontend rozpoznaje 401 jako potrzebę logowania, a 403 pokazuje komunikat odmowy uprawnień. Pozostałe przyciski mutacji zostaną przyporządkowane do ról w #5C; autoryzacja backendu jest rozstrzygająca.

## Migracja i rzeczywista walidacja H3

`0015_user_account.py` rozszerza `0014` o tabelę i backfill aktywnych kont VIEWER dla Memberów z poprawnym Discord ID. Nie kopiuje `MemberRole` ani `Member.is_active` do uprawnień i nie tworzy ADMIN. Ograniczenia UNIQUE/CHECK odrzucają konflikty i niepoprawne role. Izolowane testy SQLite migracji przeszły. Migracja `0015` została zastosowana na H3 w PostgreSQL 18.6. Downgrade usunąłby tabelę i dane, więc nie był wykonywany na H3.

Na H3 potwierdzono pełny przebieg Discord OAuth, działający sidecar bota na porcie 8001 (`/api/health` zgłasza `bot_connected=true`), sprawdzenie guild i roli `Bimbrownik`, dopuszczenie aktywnego ADMIN z `member_id=NULL`, działające `/api/auth/me` i zapis `last_login_at`. Po rzeczywistym wylogowaniu i ponownym logowaniu UI wyświetla nazwę Discorda zamiast nazwy tymczasowej. Rola, aktywność i powiązanie Membera nie uległy zmianie. Błędne konto utworzone podczas bootstrap usunięto; pozostało jedno poprawne konto ADMIN. Usługa OpenRC `siege-manager-bot` jest zainstalowana, uruchomiona i zweryfikowana.

## Testy i stan checkpointu

Testy auth/RBAC obejmują wymagania guild/roli, konta nieznane i nieaktywne, logowanie ADMIN/MANAGER z `member_id=NULL`, nazwę `global_name` i fallback do `username`, zachowanie roli/linku, wersję sesji, zmianę roli i aktywności po wystawieniu JWT, bootstrap, Origin, wybrane mutacje Siege oraz izolację bota i skanera. Zestaw #5B: **95 passed**. Praktyczny pełny backend: **535 passed, 1 deselected** z wcześniejszymi lokalnymi wyłączeniami: PostgreSQL-only `test_schema.py`, integracja sidecara wymagająca linuksowego środowiska bota oraz test lokalnie zależny od `AUTH_DISABLED`. Ruff, Black i `git diff --check` przeszły.

Frontend ma skrypt `npm test` (`vitest run`). Poprzednia walidacja #5B obejmowała TypeScript, build Vite i 4 skupione testy Vitest. Pełny zestaw uruchomiono na H3: **26 plików, 259 testów passed**. H3 używa Node 26, który w tym środowisku wymaga `--localstorage-file`; dla uniknięcia blokady współdzielonego pliku testy uruchomiono z jednym workerem (`NODE_OPTIONS=--localstorage-file=... npm test -- --silent --maxWorkers=1 --minWorkers=1`). Nie zmieniono kodu aplikacji ani konfiguracji Vitest.

## Dalszy zakres

#5C obejmie klasyfikację wszystkich pozostałych tras zwykłych, uprawnienia bota, globalne katalogi, powiadomienia, mutacje i odpowiadające im kontrolki frontendu. Szerokie `get_current_user()` na niesklasyfikowanych routerach pozostaje świadomym długiem autoryzacyjnym #5C. `require_admin` przygotowuje granicę dla przyszłych tras provision/rotate/revoke skanera w #6; żadna taka trasa HTTP nie została dodana w #5B.
