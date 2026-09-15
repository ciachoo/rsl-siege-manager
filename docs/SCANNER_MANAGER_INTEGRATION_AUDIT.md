# Audyt architektury integracji Scannera z Managerem

Podstawa audytu: HEAD repozytorium `rsl-siege-manager`: `1f1025ae7f10d27f3ca10f4b438699fd0751b466`, 2026-09-15. **POTWIERDZONE** oznacza informacje zweryfikowane w kodzie repozytorium; **WNIOSEK** oznacza rekomendację wynikającą z analizy; **PRZYSZŁE / NIEZWERYFIKOWANE** zależy od badań nad SiegeScannerem. Kierunek opisany w `D:/RSL-DEV-LOCAL-AI/Scanner-Siege-Management/architecture/SIEGE_MANAGER_DEVELOPMENT_PLAN.md` traktujemy jako aktualny plan, a nie dowód dostępności pól Scannera. Raport nie określa implementacji ani ostatecznego schematu snapshotu.

## 1. Podsumowanie

**POTWIERDZONE:** Manager już modeluje budynki, miejsca, Posty i członków dla poszczególnych Siege, a także walidację, historię przypisań oraz dostarczanie wiadomości przez Discord. Repozytorium zawiera 12 klas mapowanych przez SQLAlchemy, 14 tabel łącznie z tabelami asocjacyjnymi, 22 routery FastAPI, 64 dekoratory tras oraz 12 liniowych rewizji Alembic. Nie istnieją jeszcze obserwacje ani mechanizm przyjmowania danych ze Scannera. **WNIOSEK:** Backend należy zachować i rozszerzyć. Obserwacje Scannera wymagają informacji o pochodzeniu danych i obsługi danych częściowych, odrębnych od wartości planistycznych. Bezpośrednie nadpisywanie planu mogłoby uszkodzić przypisania i porównania historyczne.

## 2. Mapa obecnej architektury

**POTWIERDZONE:** `backend/app/main.py` tworzy aplikację FastAPI i montuje routery z `backend/app/api/`. Routery wywołują `backend/app/services/`, które korzystają z `backend/app/models/`, `backend/app/schemas/` i asynchronicznych sesji z `backend/app/db/session.py`. `frontend/src/App.tsx` określa trasy Reacta, a `frontend/src/api/` zawiera warstwę HTTP. Bot Discorda działa jako osobny sidecar FastAPI w `bot/app/http_api.py`. **WNIOSEK:** Istniejący podział na API, usługi, schematy i modele jest naturalnym miejscem rozszerzenia o Scanner. Osobna usługa Coordinator wymagałaby wykazanego powodu związanego ze skalowaniem lub izolacją.

## 3. Mapa modeli bazy danych

**POTWIERDZONE:** Klasy mapowane w `backend/app/models/` to: `Siege`, `Building`, `BuildingGroup`, `BuildingTypeConfig`, `Position`, `Post`, `PostCondition`, `PostPriorityConfig`, `Member`, `SiegeMember`, `NotificationBatch` i `NotificationBatchResult`. `post_active_condition` oraz `member_post_preference` są tabelami asocjacyjnymi z kluczami złożonymi. `Siege` posiada budynki, Posty, członkostwo i partie powiadomień danego cyklu; `Member`, `PostCondition`, `BuildingTypeConfig` i `PostPriorityConfig` są globalne. Obiekty podrzędne poszczególnych Siege zwykle mają usuwanie kaskadowe `CASCADE`; `Position.member_id` oraz `matched_condition_id` są opcjonalnymi kluczami obcymi z `SET NULL`. Ograniczenia unikalności obejmują nazwę Membera i opcjonalny identyfikator Discorda, opis Condition, numer Posta w konfiguracji priorytetów, `Building(siege_id,building_type,building_number)`, numery grup/miejsc oraz `Post(siege_id,building_id)`. Nie wykazano, aby te wewnętrzne klucze odpowiadały identyfikatorom Raid.

**POTWIERDZONE:** `backend/alembic/versions/` zawiera liniowy łańcuch: 0001 tworzy tabele bazowe i enumy PostgreSQL; 0002 dodaje podglądy JSON/terminy ważności Auto-fill i Attack Day; 0003 dopuszcza pustą datę Siege; 0004 dodaje globalne priorytety Postów; 0005 dodaje opis priorytetu; 0006 zastępuje pola power/sort opcjonalnym power level członka; 0007 zwiększa limit numeru grupy do 10; 0008 dodaje opcjonalny klucz obcy do dopasowanej Condition; 0009 dodaje opcjonalny, unikalny identyfikator Discorda; 0010 dodaje opcjonalny czas ostatniego przeczytania changelogu; 0011 dodaje podgląd/termin ważności sugestii Postów; 0012 dodaje wymagany, ograniczony typ Condition wraz z uzupełnieniem istniejących danych. 0001 definiuje enumy statusu Siege i typu budynku, ograniczenie Stronghold Level 1–3 dla Condition oraz większość bazowych ograniczeń kaskadowych i unikalności. **WNIOSEK:** Migracje rozszerzające powinny uwzględniać istniejące Siege i uzupełniać dane przed dodaniem pól wymaganych. Nie należy włączać stanu Scannera do enumów planistycznych bez ustalenia semantyki.

## 4. Mapa API

**POTWIERDZONE:** `backend/app/main.py` udostępnia health/version/config/auth bez uwierzytelnienia, a pozostałe routery montuje z `Depends(get_current_user)`. Przykładowe trasy obejmują `/api/sieges`, operacje lifecycle activate/complete/reopen/clone, budynki/grupy, Board/miejsca/masowe przypisania, Members/preferencje/członków Siege, Posts/zmianę Conditions/dane referencyjne/priorytety, Auto-fill/sugestie, Attack Days, `POST /api/sieges/{siege_id}/validate`, `GET /api/sieges/{siege_id}/compare` i `/{other_id}`, powiadomienia/synchronizację Discorda, obrazy i changelog. Dokładne dekoratory znajdują się w odpowiednich plikach `backend/app/api/*.py`. Nie istnieje router ani endpoint Scannera.

## 5. Mapa frontendu

**POTWIERDZONE:** `frontend/src/App.tsx` używa React Router: strona startowa/logowanie; po uwierzytelnieniu globalne Members, Sieges, Post Priorities i System; w ramach Siege: Settings, Board, Posts, Members i Compare. Strony używają TanStack Query do odczytów, mutacji i unieważniania danych w pamięci podręcznej. `frontend/src/api/client.ts`, moduły domenowe API i `types.ts` są warstwą kontraktu, którą można ponownie wykorzystać. `pages/BoardPage.tsx` obsługuje Board, przypisania, Auto-fill i Validate; `pages/PostsPage.tsx` pozwala wybierać Conditions; `components/PostsTab.tsx` korzysta z aktywnych Conditions na Board; `pages/SiegeMembersPage.tsx`, `MembersPage.tsx`, `SiegeSettingsPage.tsx` i `ComparisonPage.tsx` obsługują odpowiednie procesy. `components/ui/` zawiera komponenty shadcn. **WNIOSEK:** Warto zachować React/TypeScript, kontrakt API i logikę zapytań. Nawigacja i układ stron są warstwą prezentacji do późniejszego przeprojektowania; Board i Posts obecnie łączą logikę domenową z renderowaniem.

## 6. Analiza mechanizmu walidacji

**POTWIERDZONE:** `backend/app/services/validation.py::validate_siege` ładuje graf danych Siege i wykonuje ponumerowane reguły planistyczne w jednej funkcji. `backend/app/schemas/validation.py` definiuje `ValidationIssue(rule:int,message:str,context:dict|None)` oraz `ValidationResult(errors,warnings)`. Ważność problemu wynika z listy, w której się znajduje; nie ma rejestru walidatorów, kodu tekstowego, kategorii, stanów PASS/UNKNOWN ani tabeli wyników. `backend/app/api/validation.py::validate_siege` sprawdza istnienie Siege i oblicza wynik na żądanie. `frontend/src/api/sieges.ts::validateSiege`, `BoardPage.tsx` i `SiegeSettingsPage.tsx` wywołują tę operację na żądanie. Błędy obejmują nieaktywnego przypisanego członka, limit scrolli, zakresy/liczby elementów struktury, spójność miejsca i brak Attack Day (reguła 13). Ostrzeżenia obejmują nierozstrzygnięte miejsca, brak dopasowania preferencji (11), liczbę osób na Day 2 (14), konfigurację rezerw (15) i mniej niż trzy aktywne Conditions na Poście (16). Uszkodzone budynki nie generują ostrzeżeń o pustych miejscach, lecz nadal są uwzględniane w regułach strukturalnych i scrollowych. **WNIOSEK:** Walidatory Planning/Scanner/Gear/Bonus można podzielić na moduły, zachowując numery reguł dla kompatybilności i dodając stabilne kody, kategorie, dowody oraz stany UNKNOWN/pominięty. `SCAN-01`, `GEAR-01` i `BONUS-01` są przykładami przyszłych kodów, a nie obecnymi kodami.

## 7. Analiza Posts / Conditions

**POTWIERDZONE:** `Post` należy do danego Siege i jest unikalnie powiązany z budynkiem typu Post. `PostCondition` jest globalny; ma wewnętrzny identyfikator całkowity, unikalny opis, Stronghold Level 1–3 i ograniczony typ: role/affinity/faction/league/rarity/effect/other. `post_active_condition` to tabela relacji wiele-do-wielu z kluczem złożonym, bez źródła danych, czasu, zewnętrznego ID i kolejności. `backend/app/services/sieges.py::create_siege` tworzy Posty z globalnej konfiguracji. `backend/app/services/posts.py::set_post_conditions` przyjmuje maksymalnie trzy wewnętrzne ID, odrzuca zmianę ukończonego Siege i usuwa, a następnie ponownie zapisuje wszystkie powiązania. Limit trzech jest egzekwowany w aplikacji. `backend/app/api/posts.py::_serialize_post` zwraca obiekty aktywnych Conditions z katalogu, używane przez `pages/PostsPage.tsx` i `components/PostsTab.tsx`. Reguły walidacji 11/16 oraz `services/post_suggestions.py::preview_post_suggestions` korzystają z aktywnych ID; `Position.matched_condition_id` przechowuje wybrane dopasowanie planistyczne. **WNIOSEK:** Zewnętrzne ID modyfikatorów należy mapować do globalnych Conditions z uwzględnieniem wersji i niejednoznaczności. Obserwowane Conditions powinny pozostać osobno do czasu zastosowania jawnej polityki uzgadniania. Obecne API zastępujące listę usunęłoby ręczny wybór awaryjny. **PRZYSZŁE / NIEZWERYFIKOWANE:** Identyfikatory Postów 3001–3018 i ID modyfikatorów wymagają potwierdzenia w badaniach nad Scannerem.

## 8. Analiza budynków

**POTWIERDZONE:** `BuildingType` obejmuje Stronghold, Mana Shrine, Magic Tower, Defense Tower i Post. `Building` przechowuje Siege/typ/numer, poziom i stan uszkodzenia; `BuildingTypeConfig` przechowuje globalne liczby budynków i domyślne grupy. `BuildingGroup` przechowuje numer grupy i liczbę miejsc; `Position` przechowuje numer miejsca, opcjonalnego przypisanego członka, znaczniki reserve/disabled i dopasowaną Condition. `services/sieges.py::create_siege` tworzy strukturę; `services/building_capacity.py::get_team_count` oblicza pojemność zależną od poziomu, traktując Posty szczególnie. `services/buildings.py::_rebuild_groups_for_level` zmienia miejsca po zmianie poziomu lub przywróceniu budynku; `update_building` zabrania zmian budynku w Siege aktywnym lub ukończonym. **WNIOSEK:** Obserwowany stan należy dopasowywać do istniejącego Siege/typu/numeru, ale obserwowany poziom i stan uszkodzenia przechowywać osobno. Bezrefleksyjne wywołanie `update_building` naruszyłoby blokadę lifecycle i mogłoby przebudować miejsca.

## 9. Analiza członków

**POTWIERDZONE:** Globalny `Member` przechowuje nazwę, tożsamość Discorda, rolę, opcjonalny power level, status aktywności i preferencje Conditions. `SiegeMember` dodaje Attack Day, opcjonalny zestaw rezerw i override Attack Day. `Position.member_id` oznacza przypisanie planistyczne. Nie istnieją modele gracza Raid, drużyny obronnej, championa ani ekwipunku. **WNIOSEK:** Powiązany rekord zewnętrznej tożsamości/źródła jest bezpieczniejszy niż jedna zakładana kolumna ID w Member, ponieważ dopasowanie może być nieobecne, niejednoznaczne lub później poprawione. Brak obserwacji rosteru lub gear oznacza UNKNOWN, a nie ich brak w Raid.

## 10. Analiza Compare

**POTWIERDZONE:** `services/comparison.py::get_most_recent_completed` wybiera inne ukończone Siege według daty malejąco, a następnie ID malejąco; nie wymaga, aby porównywany Siege był wcześniejszy od bieżącego. `compare_sieges` bierze przypisane miejsca bez znaczników reserve/disabled dla członków aktywnych obecnie, używając klucza Member ID oraz typ/numer budynku/grupa/miejsce. Wynik zawiera added/removed/unchanged. `api/comparison.py` pozwala wybrać domyślny lub konkretny Siege, a `pages/ComparisonPage.tsx` wyświetla wynik. **WNIOSEK:** Funkcję należy zachować jako porównanie historii Siege, oddzielne od Scanner Validation. Zmiana obecnego statusu aktywności Membera może zmienić wynik historyczny.

## 11. Granica integracji z Discordem

**POTWIERDZONE:** `services/bot_client.py` wywołuje sidecar z uwierzytelnieniem Bearer; `bot/app/http_api.py::verify_api_key` chroni endpointy bota. `api/notifications.py` zapisuje `NotificationBatch` i `NotificationBatchResult`. Synchronizacja Discorda i ról Attack Day korzysta z tej granicy. **WNIOSEK:** Dane Scannera należy przyjmować i walidować w Managerze, po czym Discord powinien korzystać ze zweryfikowanego stanu Managera.

## 12. Miejsca rozszerzenia dla integracji Scannera

**WNIOSEK:** Nowy router można dodać w `backend/app/api/`, schematy w `backend/app/schemas/`, usługi przyjmowania danych i uzgadniania w `backend/app/services/`, a modele dowodów/tożsamości w `backend/app/models/`. Router należy zamontować w `main.py` i użyć istniejących sesji asynchronicznych. Na początek wystarczą tożsamość/wersja/capabilities, heartbeat/status i potwierdzenie przyjęcia danych; lease ACTIVE/STANDBY i pełny Fleet Management można odłożyć. Obecnie nie ma konkretnego powodu do tworzenia osobnej usługi.

## 13. Proponowana granica znormalizowanego snapshotu

**PRZYSZŁE / NIEZWERYFIKOWANE:** Koncepcyjna koperta danych powinna zawierać tożsamość/wersję/capabilities Scannera, czas przechwycenia, wersję Raid, odniesienie do cyklu, stabilną tożsamość snapshotu oraz informację o obecności/kompletności kategorii. Możliwe obserwacje typowane obejmują budynki, Posty, przypisania/drużyny, bonusy i gear; żadna kategoria nie jest gwarantowana. Należy walidować ID, zakresy i limity kategorii, zachowywać możliwe do prześledzenia dowody oraz uzgadniać dane dopiero po przyjęciu. To nie jest ostateczny schemat ani kontrakt API.

## 14. Strategia źródła danych i ręcznego override

**WNIOSEK:** Należy zachować wartość planistyczną/ręczną, wartość obserwowaną wraz ze Scannerem i czasem, jawny override/preferencję oraz wyliczony status porównania MATCH/OUT_OF_SYNC/UNKNOWN. Samo otrzymanie snapshotu nie powinno zmieniać `Building.level`, `is_broken`, `Position.member_id` ani `Post.active_conditions`. Jawny, możliwy do audytu krok promote/apply może aktualizować efektywny plan, jeśli pozwala na to lifecycle.

## 15. Strategia UNKNOWN i częściowych snapshotów

**WNIOSEK:** Należy odróżnić pominiętą kategorię, niezaobserwowany obiekt, zaobserwowany pusty stan, nieznane mapowanie i przestarzały dowód. Tylko kategoria zadeklarowana jako kompletna uzasadnia twierdzenie o braku obiektu. Starsze dowody pozostają w historii, lecz bieżące porównania przy niespełnionej polityce pokrycia/świeżości powinny mieć status UNKNOWN. Częściowo widoczny Post nie powinien być uznawany przez Scanner Validation za „brak Conditions”. **PRZYSZŁE / NIEZWERYFIKOWANE:** Progi pokrycia i świeżości wymagają obserwacji zachowania Scannera.

## 16. Strategia integracji capabilities

**POTWIERDZONE:** `backend/app/config.py` zawiera ustawienia i operacyjne feature flags, np. synchronizacji ról; `dependencies/auth.py::get_current_user` udostępnia tożsamość Membera/usługi i rolę. Nie znaleziono ogólnego rejestru capabilities ani systemu licencyjnego. **WNIOSEK:** Należy używać nazwanych capabilities produktu (`scanner_validation`, `gear_audit`, `tower_bonus`, `analytics`, `discord`, `fleet_management`), odrębnych od capabilities ekstrakcji zgłaszanych przez Scanner. Źródło uprawnień pozostaje otwartą decyzją; kontroli subskrypcji nie należy wpisywać na stałe w UI ani walidatory.

## 17. Bezpieczeństwo i granica zaufania

**POTWIERDZONE:** `dependencies/auth.py::get_current_user` akceptuje obejście deweloperskie, token Bearer usługi lub cookie JWT. `api/auth.py` obsługuje OAuth Discorda i wymaganą rolę. Chronione routery mają zależność uwierzytelniającą; health/version/config/auth pozostają publiczne. Istnieją limity żądań login/callback i ustawienia CORS. Obecne uwierzytelnienie usługi Bearer jest ukierunkowane na bota, a nie na Scanner. Pydantic waliduje istniejące dane wejściowe. Nie istnieją jeszcze limity wielkości danych, kontrola powtórzeń/idempotencji, dopuszczalnego przesunięcia czasu ani obsługa duplikatów specyficzna dla Scannera. **WNIOSEK:** Należy zastosować uprawnienia ograniczone do Scannera, limitowane payloady, walidację czasu przechwycenia i cyklu, transakcyjną deduplikację według Scanner+snapshot ID oraz ostrożne traktowanie wszystkich zewnętrznych ID. Nie odczytywano zawartości plików .env ani poświadczeń.

## 18. Ocena pokrycia testami

**POTWIERDZONE:** W repozytorium jest 80 plików testowych pasujących do `test_*.py`, `*.test.tsx`, `*.spec.ts` lub `*.Tests.ps1`. `backend/tests/conftest.py` dostarcza przykładowe ustawienia i domyślnie wyłącza uwierzytelnianie w testach; testy API często korzystają z HTTPX `ASGITransport` oraz podmiany zależności DB. `backend/tests/integration/sidecar/` sprawdza komunikację z botem. Testy obejmują schemat, Posty, budynki, walidację, porównanie, auth, lifecycle i powiadomienia. Frontend używa Vitest w `frontend/src/test/` i Playwright w `frontend/e2e/`. **WNIOSEK:** Przed integracją warto zwiększyć pokrycie regresyjne dla zastępowania Conditions/limitu trzech, lifecycle budynków/przebudowy miejsc, kolejności porównania/filtra obecnej aktywności oraz granicy auth. Po ustaleniu kontraktu Scannera należy testować snapshoty częściowe/UNKNOWN/przestarzałe, ponowne wysłanie, zachowanie ręcznego override i ograniczenia migracji PostgreSQL.

## 19. Ryzyka i dług techniczny

**POTWIERDZONE:** Powiązania Conditions nie mają informacji o pochodzeniu; Validation ma tylko numery reguł i nie obsługuje UNKNOWN; Compare filtruje członków nieaktywnych obecnie, a domyślny Siege porównawczy może być późniejszy; zmiany budynku przebudowują przypisania; Stronghold Level Condition jest ograniczony do 3, chociaż budynki osiągają poziom 6. **WNIOSEK:** Są to ryzyka przy rozszerzaniu, a nie powody do przepisywania backendu. Globalna unikalność nazw/opisów oraz enumy bazy komplikują mapowanie zewnętrzne. Przed mapowaniem ID modyfikatorów trzeba potwierdzić semantykę Conditions.

## 20. KEEP / EXTEND / NEW / REDESIGN

| Obszar | Decyzja | Powód |
|---|---|---|
| Backend/domeny/model danych | ZACHOWAĆ + ROZSZERZYĆ | Istniejące granice danych planistycznych |
| Budynki/Posty/Members/Positions | ZACHOWAĆ + ROZSZERZYĆ | Zachować wewnętrzne ID i plany ręczne |
| Validation | ROZSZERZYĆ | Dodać moduły, kody, kategorie i UNKNOWN |
| Historyczne Compare | ZACHOWAĆ | Osobne zadanie historyczne |
| Tożsamość/dowody/przyjmowanie danych Scannera | NOWE | Brak obecnego odpowiednika |
| React/TypeScript/API/TanStack Query | ZACHOWAĆ + ROZSZERZYĆ | Kontrakt i zachowanie nadają się do ponownego użycia |
| Nawigacja i wygląd stron | PRZEPROJEKTOWAĆ PÓŹNIEJ | Plan produktowy |
| Sidecar Discorda | ZACHOWAĆ | Istniejąca granica integracji |

## 21. Zalecana kolejność implementacji

**WNIOSEK:** (1) Utrwalić testami niezmienniki planu; (2) zweryfikować tożsamość, dane wyjściowe Scannera i dopasowanie cyklu; (3) ustalić politykę częściowych danych, UNKNOWN i pochodzenia; (4) dodać tożsamość Scannera o ograniczonych uprawnieniach oraz idempotentne przyjmowanie dowodów; (5) dodać uzgadnianie budynków/Postów tylko do odczytu; (6) podzielić walidację na moduły i grupować wyniki; (7) dodać drużyny/bonusy/gear wyłącznie tam, gdzie istnieją dowody; (8) przeprojektować UX, a potem rozszerzać obsługę floty.

## 22. Pliki, które prawdopodobnie zmienią się później

**WNIOSEK; żaden z tych plików nie został zmieniony teraz:** `backend/app/main.py` (router); `backend/app/dependencies/auth.py`, `backend/app/config.py` (uprawnienia/ustawienia Scannera); `backend/app/models/building.py`, `post.py`, `post_condition.py`, `member.py` (relacje pochodzenia/mapowania); `backend/app/services/posts.py`, `buildings.py`, `validation.py` (uzgadnianie/reguły); `backend/app/schemas/validation.py`, `backend/app/api/validation.py` (kontrakt wyników); `frontend/src/api/types.ts`, `client.ts`, `sieges.ts`, `posts.ts` (kontrakty); `frontend/src/App.tsx`, `frontend/src/pages/BoardPage.tsx`, `PostsPage.tsx`, `SiegeSettingsPage.tsx`, `ComparisonPage.tsx`, `frontend/src/components/PostsTab.tsx` (widoki dowodów/późniejszy UX); `backend/alembic/versions/` (przyszła migracja rozszerzająca). Nowe pliki Scannera będą potrzebne, lecz raport nie przedstawia ich jako istniejących.

## 23. Pytania otwarte wymagające badań nad SiegeScannerem

**PRZYSZŁE / NIEZWERYFIKOWANE:** Czy ID Postów 3001–3018 oraz modyfikatorów są stabilne między wersjami i cyklami? Czy Scanner odróżnia wszystkie trzy Conditions i stan zaobserwowany jako pusty od niezaobserwowanego? Jakie są stabilne ID budynków i znaczenie stanu broken/damaged? Czy przypisania można powiązać ze stabilnym ID gracza Raid? Czyje drużyny, championy i gear są widoczne? Czy można obserwować ID bonusów i odblokowane kategorie? Jaka jest dokładność czasu przechwycenia, częstotliwość snapshotów, zachowanie duplikatów, maksymalny rozmiar payloadu, sygnał wersji Raid i wymagania rotacji poświadczeń? Jak przypisać snapshot do Siege w Managerze, gdy data jest pusta lub cykle się nakładają?

## 24. Rekomendacja końcowa

**WNIOSEK:** Należy zachować Manager jako system planowania i dodać w istniejącym backendzie FastAPI obserwacje Scannera z informacją o pochodzeniu i obsługą danych częściowych. Dane należy uzgadniać z istniejącymi obiektami domenowymi bez automatycznego nadpisywania planu. Compare powinno pozostać funkcją historyczną, a Validation należy rozszerzyć o stan UNKNOWN. Szczegóły gear, bonusów i floty powinny poczekać na potwierdzenie dostępności danych w badaniach nad Scannerem.

