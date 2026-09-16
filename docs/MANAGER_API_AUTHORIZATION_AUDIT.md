# Manager Task #5C — audyt autoryzacji API

Podstawa: czysty checkpoint `164c33882e30a3e898c805195cadb7f826dec0cf`, 2026-09-16. Dokument powstał przed zmianami implementacyjnymi #5C. Inwentaryzacja obejmuje wszystkie 65 tras aplikacyjnych FastAPI zarejestrowanych przez `backend/app/main.py`. Trasy dokumentacji OpenAPI istnieją tylko w development i są opisane osobno.

## Zasady klasyfikacji

- **PUBLIC** — świadomie dostępne przed logowaniem.
- **HUMAN_VIEWER** — odczyt stanu Managera albo osobisty, idempotentny stan UI.
- **HUMAN_MANAGER** — zwykłe operacje planowania Siege, generowanie/stosowanie podglądów oraz skutki zewnętrzne.
- **HUMAN_ADMIN** — globalne katalogi/tożsamości i operacje administracyjne.
- **SCANNER** — wyłącznie poświadczenie skanera.
- **BOT_SERVICE** — wyłącznie zaufany token usługi bota.

`ADMIN >= MANAGER >= VIEWER`. Bypass `AUTH_DISABLED` jest MANAGER-equivalent wyłącznie w development. Skaner i bot są poza hierarchią ludzką. Wyjątek zgodności stanowi `/members/me/preferences`: to udokumentowany kontrakt BOT_SERVICE, a #5B zachował również dostęp powiązanego HUMAN_VIEWER. Zostanie zabezpieczony dedykowaną zależnością dopuszczającą dokładnie te dwa typy, bez skanera i innych usług.

## Pełna macierz endpointów

| Metoda i ścieżka | Plik / funkcja | Operacja | Obecna granica na 164c338 | Klasyfikacja docelowa |
|---|---|---|---|---|
| GET `/api/health` | `api/health.py::health` | odczyt health | brak | PUBLIC |
| GET `/api/version` | `api/version.py::get_version` | odczyt wersji | brak | PUBLIC |
| GET `/api/config` | `api/config.py::get_config` | publiczna flaga `auth_disabled` | brak | PUBLIC |
| GET `/api/auth/login` | `api/auth.py::login` | rozpoczęcie OAuth | brak | PUBLIC |
| GET `/api/auth/callback` | `api/auth.py::callback` | callback OAuth / utworzenie sesji | własne kontrole OAuth | PUBLIC |
| POST `/api/auth/logout` | `api/auth.py::logout` | usunięcie ciasteczka | brak | PUBLIC |
| GET `/api/auth/me` | `api/auth.py::me` | odczyt własnej tożsamości | `get_current_user` | HUMAN_VIEWER |
| POST `/api/scanner/snapshots` | `api/scanner.py::ingest_snapshot` | zapis snapshotu | `get_authenticated_scanner` | SCANNER |
| GET `/api/post-conditions` | `api/reference.py::get_post_conditions` | odczyt katalogu | router `get_current_user` | HUMAN_VIEWER |
| GET `/api/building-types` | `api/reference.py::get_building_types` | odczyt katalogu | router `get_current_user` | HUMAN_VIEWER |
| GET `/api/member-roles` | `api/reference.py::get_member_roles` | odczyt katalogu | router `get_current_user` | HUMAN_VIEWER |
| POST `/api/members/discord-sync/preview` | `api/discord_sync.py::preview_discord_sync` | globalny podgląd tożsamości z Discord | router `get_current_user` | HUMAN_ADMIN |
| POST `/api/members/discord-sync/apply` | `api/discord_sync.py::apply_discord_sync` | globalna zmiana tożsamości Memberów | router `get_current_user` | HUMAN_ADMIN |
| GET `/api/members` | `api/members.py::list_members` | odczyt globalnego rosteru | router `get_current_user` | HUMAN_VIEWER |
| POST `/api/members` | `api/members.py::create_member` | utworzenie globalnego Membera | router `get_current_user` | HUMAN_ADMIN |
| GET `/api/members/{member_id}` | `api/members.py::get_member` | odczyt Membera | router `get_current_user` | HUMAN_VIEWER |
| PUT `/api/members/{member_id}` | `api/members.py::update_member` | globalna zmiana Membera/tożsamości | router `get_current_user` | HUMAN_ADMIN |
| DELETE `/api/members/{member_id}` | `api/members.py::delete_member` | globalna dezaktywacja/usunięcie | router `get_current_user` | HUMAN_ADMIN |
| GET `/api/members/me/preferences` | `api/members.py::get_my_preferences` | własne preferencje / kontrakt bota | router `get_current_user` + `get_acting_member_id` | BOT_SERVICE (także HUMAN_VIEWER zgodnie z #5B) |
| PUT `/api/members/me/preferences` | `api/members.py::set_my_preferences` | własne preferencje / kontrakt bota | router `get_current_user` + `get_acting_member_id` | BOT_SERVICE (także HUMAN_VIEWER zgodnie z #5B) |
| GET `/api/members/{member_id}/preferences` | `api/members.py::get_member_preferences` | odczyt preferencji Membera | router `get_current_user` | HUMAN_VIEWER |
| PUT `/api/members/{member_id}/preferences` | `api/members.py::set_member_preferences` | globalna zmiana preferencji Membera | router `get_current_user` | HUMAN_ADMIN |
| GET `/api/sieges` | `api/sieges.py::list_sieges` | odczyt Siege | router `get_current_user` | HUMAN_VIEWER |
| POST `/api/sieges` | `api/sieges.py::create_siege` | planowanie | router `get_current_user` + `require_manager` | HUMAN_MANAGER |
| GET `/api/sieges/{siege_id}` | `api/sieges.py::get_siege` | odczyt Siege | router `get_current_user` | HUMAN_VIEWER |
| PUT `/api/sieges/{siege_id}` | `api/sieges.py::update_siege` | planowanie | router `get_current_user` + `require_manager` | HUMAN_MANAGER |
| DELETE `/api/sieges/{siege_id}` | `api/sieges.py::delete_siege` | planowanie | router `get_current_user` + `require_manager` | HUMAN_MANAGER |
| GET `/api/sieges/{siege_id}/buildings` | `api/buildings.py::list_buildings` | odczyt budynków | router `get_current_user` | HUMAN_VIEWER |
| POST `/api/sieges/{siege_id}/buildings` | `api/buildings.py::add_building` | planowanie | router + `require_manager` | HUMAN_MANAGER |
| PUT `/api/sieges/{siege_id}/buildings/{building_id}` | `api/buildings.py::update_building` | planowanie | router + `require_manager` | HUMAN_MANAGER |
| DELETE `/api/sieges/{siege_id}/buildings/{building_id}` | `api/buildings.py::delete_building` | planowanie | router + `require_manager` | HUMAN_MANAGER |
| POST `/api/sieges/{siege_id}/buildings/{building_id}/groups` | `api/buildings.py::add_group` | planowanie | router + `require_manager` | HUMAN_MANAGER |
| DELETE `/api/sieges/{siege_id}/buildings/{building_id}/groups/{group_id}` | `api/buildings.py::delete_group` | planowanie | router + `require_manager` | HUMAN_MANAGER |
| GET `/api/sieges/{siege_id}/members/preferences` | `api/siege_members.py::get_siege_member_preferences` | odczyt planowania | router `get_current_user` | HUMAN_VIEWER |
| GET `/api/sieges/{siege_id}/members` | `api/siege_members.py::list_siege_members` | odczyt rosteru Siege | router `get_current_user` | HUMAN_VIEWER |
| POST `/api/sieges/{siege_id}/members` | `api/siege_members.py::add_siege_member` | planowanie | router `get_current_user` | HUMAN_MANAGER |
| DELETE `/api/sieges/{siege_id}/members/{member_id}` | `api/siege_members.py::remove_siege_member` | planowanie + opcjonalny webhook | router `get_current_user` | HUMAN_MANAGER |
| PUT `/api/sieges/{siege_id}/members/{member_id}` | `api/siege_members.py::update_siege_member` | planowanie + opcjonalny webhook | router `get_current_user` | HUMAN_MANAGER |
| GET `/api/sieges/{siege_id}/board` | `api/board.py::get_board` | odczyt planszy | router `get_current_user` | HUMAN_VIEWER |
| PUT `/api/sieges/{siege_id}/positions/{position_id}` | `api/board.py::update_position` | przypisanie | router `get_current_user` | HUMAN_MANAGER |
| POST `/api/sieges/{siege_id}/assignments/bulk` | `api/board.py::bulk_update_positions` | przypisania zbiorcze | router `get_current_user` | HUMAN_MANAGER |
| POST `/api/sieges/{siege_id}/activate` | `api/lifecycle.py::activate_siege` | zmiana lifecycle | router `get_current_user` | HUMAN_MANAGER |
| POST `/api/sieges/{siege_id}/complete` | `api/lifecycle.py::complete_siege` | zmiana lifecycle | router `get_current_user` | HUMAN_MANAGER |
| POST `/api/sieges/{siege_id}/reopen` | `api/lifecycle.py::reopen_siege` | zmiana lifecycle | router `get_current_user` | HUMAN_MANAGER |
| POST `/api/sieges/{siege_id}/clone` | `api/lifecycle.py::clone_siege` | utworzenie planu | router `get_current_user` | HUMAN_MANAGER |
| GET `/api/sieges/{siege_id}/posts` | `api/posts.py::list_posts` | odczyt Postów | router `get_current_user` | HUMAN_VIEWER |
| PUT `/api/sieges/{siege_id}/posts/{post_id}` | `api/posts.py::update_post` | planowanie | router `get_current_user` | HUMAN_MANAGER |
| PUT `/api/sieges/{siege_id}/posts/{post_id}/conditions` | `api/posts.py::set_post_conditions` | planowanie | router `get_current_user` | HUMAN_MANAGER |
| POST `/api/sieges/{siege_id}/validate` | `api/validation.py::validate_siege` | obliczenie bez zapisu | router `get_current_user` | HUMAN_VIEWER |
| POST `/api/sieges/{siege_id}/auto-fill` | `api/autofill.py::preview_autofill` | zapis tymczasowego podglądu | router `get_current_user` | HUMAN_MANAGER |
| POST `/api/sieges/{siege_id}/auto-fill/apply` | `api/autofill.py::apply_autofill` | zastosowanie planu | router `get_current_user` | HUMAN_MANAGER |
| POST `/api/sieges/{siege_id}/post-suggestions` | `api/post_suggestions.py::preview_post_suggestions` | zapis tymczasowego podglądu | router `get_current_user` | HUMAN_MANAGER |
| POST `/api/sieges/{siege_id}/post-suggestions/apply` | `api/post_suggestions.py::apply_post_suggestions` | zastosowanie planu | router `get_current_user` | HUMAN_MANAGER |
| GET `/api/sieges/{siege_id}/compare` | `api/comparison.py::compare_with_most_recent` | odczyt porównania | router `get_current_user` | HUMAN_VIEWER |
| GET `/api/sieges/{siege_id}/compare/{other_id}` | `api/comparison.py::compare_with_specific` | odczyt porównania | router `get_current_user` | HUMAN_VIEWER |
| POST `/api/sieges/{siege_id}/members/auto-assign-attack-day` | `api/attack_day.py::preview_attack_day` | zapis tymczasowego podglądu | router `get_current_user` | HUMAN_MANAGER |
| POST `/api/sieges/{siege_id}/members/auto-assign-attack-day/apply` | `api/attack_day.py::apply_attack_day` | zastosowanie + webhook | router `get_current_user` | HUMAN_MANAGER |
| GET `/api/changelog/status` | `api/changelog.py::get_changelog_status` | osobisty odczyt | router + `get_current_user` + kontrola w ciele | HUMAN_VIEWER |
| POST `/api/changelog/mark-seen` | `api/changelog.py::mark_changelog_seen` | osobisty stan UI | router + `get_current_user` + kontrola w ciele | HUMAN_VIEWER |
| POST `/api/sieges/{siege_id}/generate-images` | `api/images.py::generate_images` | generowanie bez zapisu domenowego | router `get_current_user` | HUMAN_VIEWER |
| POST `/api/sieges/{siege_id}/notify` | `api/notifications.py::notify_siege_members` | zapis batcha + DM | router `get_current_user` | HUMAN_MANAGER |
| GET `/api/sieges/{siege_id}/notify/{batch_id}` | `api/notifications.py::get_notification_batch` | odczyt wyniku | router `get_current_user` | HUMAN_VIEWER |
| POST `/api/sieges/{siege_id}/post-to-channel` | `api/notifications.py::post_to_channel` | publikacja w Discord | router `get_current_user` | HUMAN_MANAGER |
| GET `/api/post-priorities` | `api/post_priority_config.py::list_post_priorities` | odczyt globalnego katalogu | router `get_current_user` | HUMAN_VIEWER |
| PUT `/api/post-priorities/{post_number}` | `api/post_priority_config.py::update_post_priority` | zmiana globalnego katalogu | router `get_current_user` | HUMAN_ADMIN |

Development dodaje frameworkowe `GET /openapi.json`, `GET /api/docs` i `GET /docs/oauth2-redirect`. Nie są częścią API produktu; są wyłączone poza development. Ich dostęp pozostaje decyzją środowiskową FastAPI.

## Luki znalezione przed implementacją

1. Wspólna zależność routerów `get_current_user` uwierzytelnia, ale nie autoryzuje. Token bota może obecnie odczytywać i mutować prawie cały Manager.
2. VIEWER może wykonywać większość mutacji poza zabezpieczonymi wcześniej Siege/Buildings.
3. MANAGER i VIEWER mogą zmieniać globalne Membery, powiązania Discord oraz priorytety Postów.
4. Trasy tylko do odczytu przyjmują token bota, mimo że nie są kontraktem usługi.
5. Kontrole changelogu rozpoznające człowieka znajdują się w ciele tras i zwracają semantykę 400 zamiast centralnego 403 dla złego typu principal.
6. Podobne mutacje Board, Posts, SiegeMember, lifecycle, apply/preview i skutki Discord nie mają spójnego `require_manager`.
7. `/auth/me` używa szerokiego `get_current_user`, więc może zwrócić tożsamość bota; docelowo jest trasą ludzką.
8. Granica skanera jest poprawnie odrębna i nie korzysta z `AUTH_DISABLED`; należy ją zachować.
9. `/members/me/preferences` świadomie obsługuje dwa typy principal. Wymaga dedykowanej, wąskiej zależności zamiast odziedziczonego dostępu do całego API.
10. Brak centralnej zależności „tylko bot”; obecny `get_current_user` rozpoznaje bota, ale nie ogranicza tras do tego typu.
11. Publiczne health/version/config oraz OAuth login/callback/logout są świadomie publiczne; nie stwierdzono niezamierzonej publicznej trasy domenowej.


## Stan implementacji Task #5C

Każda z 65 tras produktu ma teraz jawnie przypisaną granicę autoryzacji zgodną z macierzą powyżej. Trasy ludzkie korzystają z centralnych zależności `require_viewer`, `require_manager` albo `require_admin`. `/api/auth/me` wymaga człowieka z rolą VIEWER lub wyższą. Trasy odczytu Managera nie przyjmują tokenu bota ani poświadczenia skanera, a mutacje planowania wymagają MANAGER. Globalne operacje na Memberach, synchronizacja tożsamości Discord i zmiana globalnego katalogu priorytetów wymagają ADMIN.

Kontrakt `/api/members/me/preferences` zachowuje dostęp dla zaufanego `rsl-mom-bot` działającego w imieniu Membera oraz dla powiązanego konta ludzkiego VIEWER lub wyższego. `BOT_SERVICE_TOKEN` uwierzytelnia cały proces bota, a `X-Acting-Discord-Id` jest delegowanym kontekstem podmiotu, który upstream pobiera bezpośrednio z `discord.Interaction.user.id`. Manager nie uwierzytelnia niezależnie końcowego użytkownika Discord. Służy temu wąska zależność `require_bot_service_or_human_viewer`; nie daje ona botowi dostępu do pozostałych tras Managera.

Manager rozwiązuje podmiot bota wyłącznie przez dokładne `Member.discord_id == X-Acting-Discord-Id`. `X-Acting-Discord-Username` nie wybiera Membera, nie ustanawia tożsamości i nie powoduje zapisu ani automatycznego backfillu. Brak dokładnego powiązania Discord ID zwraca 404 bez mutacji; powiązanie musi zostać utworzone przez kontrolowany workflow Discord sync/admin. Ludzkie `/me` nadal opiera się na opcjonalnym `UserAccount.member_id` i ignoruje nagłówki acting-user. Endpoint skanera nadal korzysta wyłącznie z `get_authenticated_scanner`. Publiczne trasy oraz model OAuth/UserAccount nie zostały zmienione.

Bypass `AUTH_DISABLED` pozostaje development-only i przechodzi wymagania VIEWER/MANAGER, ale jest odrzucany przez ADMIN. Kontrole changelogu korzystają z centralnej zależności VIEWER, a istniejąca kontrola opcjonalnego powiązania Member nadal zachowuje semantykę osobistego profilu.

## Testy implementacji

Dodano regresyjny test kompletności macierzy, który enumeruje wszystkie 65 tras i wykrywa brak trasy, nową niesklasyfikowaną trasę albo niewłaściwą zależność. Macierz principal obejmuje anonimowego użytkownika, VIEWER, MANAGER, ADMIN, development stub, skaner i bot service. Testy wykonujące rzeczywiste żądania HTTP potwierdzają obustronną izolację tras HUMAN_VIEWER/HUMAN_MANAGER/HUMAN_ADMIN, SCANNER i kontraktu BOT_SERVICE. Obejmują również development stub oraz stabilne rozwiązywanie Membera wyłącznie po Discord ID: zmiana username nie zmienia podmiotu, a nieznany ID z pasującą nazwą zwraca 404 bez zapisu. Istniejące testy bota, changelogu, Memberów i Discord sync zaktualizowano do nowych granic bez zmiany zachowania domenowego.

Wyniki końcowe:

- testy skupione #5C i powiązanych endpointów: **191 passed**;
- pełny zestaw auth/RBAC/scanner/bootstrap/migration: **92 passed**;
- praktyczny pełny backend z wcześniejszymi lokalnymi wyłączeniami PostgreSQL schema, Windows sidecar oraz testu zależnego od lokalnego `AUTH_DISABLED`: **551 passed, 1 deselected**;
- Ruff dla `app` i `tests`: zaliczony;
- Black dla zmienionych plików oraz kontrola całego `app` i `tests`: zaliczone;
- `git diff --check`: zaliczony.

Frontend nie został zmieniony: istniejąca obsługa 403 nadal pokazuje komunikat o braku uprawnień. Task #5C dotyczy granic API, dlatego nie uruchamiano zestawu frontendowego. Nie pozostała nierozstrzygnięta trasa ani blocker implementacyjny. Provisioning skanera pozostaje poza zakresem do Task #6.
