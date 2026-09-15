# Baseline testów regresyjnych Siege Managera

Data: 2026-09-15. Zadanie obejmuje wyłącznie obecne zachowanie Managera przed integracją ze Scannerem. Nie zmieniono kodu produkcyjnego, migracji, Discorda ani UI.

## HEAD i stan przed pracą

- HEAD: `1f1025ae7f10d27f3ca10f4b438699fd0751b466`.
- `git status --short` przed pracą: `?? docs/SCANNER_MANAGER_INTEGRATION_AUDIT.md`. Ten istniejący, nieśledzony raport pozostawiono bez zmian.

## Siege Rotation Semantics

**CONFIRMED PRODUCT REQUIREMENT:** Conditions przypisane do Postów są danymi konkretnego Siege/rotacji i mogą losowo zmienić się w następnym cyklu. To samo logiczne miejsce Posta może mieć inne Conditions w Siege A i Siege B. Globalny `PostCondition` definiuje Condition; `post_active_condition` wiąże ją z `Post` należącym do określonego Siege. Nie należy utrwalać mapowania „Post N → stałe Conditions” ani zmieniać historycznych Conditions po utworzeniu nowej rotacji.

**FUTURE / UNVERIFIED:** Bonusy Tower mogą utrzymywać się między rotacjami, ale nie potwierdzono tego w badaniach nad SiegeScannerem. Żaden dodany test ani założenie produkcyjne nie zależy od takiej trwałości.

## Testy sprawdzone przed dodaniem

Przejrzano `backend/tests/test_posts.py`, `test_buildings.py`, `test_validation.py`, `test_comparison.py`, `test_lifecycle.py`, `test_lifecycle_integration.py`, `test_sieges.py`, `test_board.py`, `test_auth.py`, `test_config_endpoint.py`, `test_health.py`, `test_version.py`, `test_remove_siege_member.py`, `test_deactivate_stale_siege_member.py` i `test_post_suggestions.py` oraz powiązane usługi. Obecne `test_validation.py` pokrywa reprezentatywne błędy, ostrzeżenia, strukturę, puste miejsca, preferencje, Attack Day, rezerwy, mniej niż trzy Conditions i zachowanie uszkodzonych budynków. `test_auth.py` oraz testy publicznych endpointów pokrywają obecny podział na trasy chronione i publiczne. Nie powielano tych reguł.

## Testy dodane

Dodano **11** testów w `backend/tests/test_manager_rotation_baseline.py`. Używają krótkiej, deterministycznej bazy SQLite w pamięci z włączonymi kluczami obcymi oraz rzeczywistych usług i modeli Managera. Asercje dotyczą zachowania zgodnego z PostgreSQL; nie opierają się na ponownym wykorzystaniu lub nieponownym wykorzystaniu usuniętych kluczy całkowitych.

| Test | Chroniony kontrakt |
|---|---|
| `test_post_conditions_are_rotation_scoped_and_catalog_is_unchanged` | Dwa Siege z tym samym numerem Posta mają różne zestawy Conditions; zmiana jednego Posta nie zmienia drugiej rotacji, innego Posta ani katalogu |
| `test_post_condition_limit_siege_identity_and_completed_lock` | Maksimum 3 ID, odrzucenie Posta z innego Siege i blokada ukończonego Siege |
| `test_replacing_post_conditions_keeps_existing_position_match` | Obecne zastępowanie aktywnych Conditions nie zmienia `Position.matched_condition_id` |
| `test_building_identity_is_unique_within_rotation_but_reusable_across_rotations` | Unikalność typu/numeru wewnątrz Siege, możliwość użycia tego samego typu/numeru w innym Siege |
| `test_level_rebuild_preserves_retained_positions_and_deletes_trimmed_groups` | Zmiana poziomu dodaje/usuwa miejsca; zachowuje ID i przypisania w pozostawionych miejscach; nie dotyka poprzedniego Siege |
| `test_break_and_unbreak_remove_and_recreate_positions_only_in_selected_rotation` | Broken redukuje strukturę do bazowej; przywrócenie tworzy miejsca bez utraconych przypisań; inne Siege jest nienaruszone |
| `test_active_and_completed_sieges_reject_building_mutations` | Zmiana poziomu/stan broken jest blokowana w aktywnym i ukończonym Siege |
| `test_post_level_change_does_not_rebuild_its_single_group` | Post zachowuje jedną grupę/miejsca przy zmianie poziomu |
| `test_clone_keeps_source_rotation_while_clearing_new_post_conditions` | Clone kopiuje osobne budynki, miejsca i członkostwo, ale nie kopiuje aktywnych Conditions; źródło pozostaje historycznie poprawne |
| `test_compare_default_can_select_a_later_completed_rotation` | Charakterystyka obecnego wyboru domyślnego Siege do porównania |
| `test_compare_history_changes_after_global_member_deactivation` | Charakterystyka obecnego filtrowania historii według bieżącego `Member.is_active` |

## Posts i Conditions

**CONFIRMED CURRENT BEHAVIOR:** `services/posts.py::set_post_conditions` odrzuca więcej niż trzy ID, nie przyjmuje Posta z innego Siege, nie zmienia ukończonego Siege i zastępuje wyłącznie powiązania wskazanego Posta. Nowe testy na bazie dowodzą, że historyczny Post zachowuje Conditions po zmianach w nowej rotacji; globalny katalog pozostaje bez zmian. `Position.matched_condition_id` pozostaje w obecnym API po zmianie aktywnych Conditions. To ostatnie jest charakterystyką bieżącego zachowania, nie gwarancją, że takie dopasowanie nadal jest semantycznie aktualne.

## Buildings

**CONFIRMED CURRENT BEHAVIOR:** Typ/numer są unikalne dla Siege, nie globalnie. `services/buildings.py::_rebuild_groups_for_level` zachowuje istniejące miejsca w pozostawionych grupach, dodaje miejsca przy rozszerzeniu, a usuwa nadmiarowe grupy/miejsca przy zmniejszeniu poziomu. Broken może usunąć grupy i miejsca wraz z przypisaniami; unbroken przywraca strukturę bez tych przypisań. Mutacje budynku są blokowane dla active/complete. Dla Posta zmiana poziomu nie przebudowuje grupy. Istniejące `test_sieges.py` i `test_buildings.py` sprawdzają pojemności poziomów, scroll count, broken i odtwarzanie grup; nowe testy dodają obserwację skutku dla rzeczywistych rekordów miejsc oraz izolację rotacji.

## Validation baseline

**CONFIRMED CURRENT BEHAVIOR:** `services/validation.py::validate_siege` wylicza wynik dynamicznie jako `errors` i `warnings` z numerami reguł. Istniejący `test_validation.py` obejmuje wszystkie reprezentatywne obszary wskazane w zadaniu, łącznie z regułami 1–16, structural, unresolved positions, preference mismatch, Attack Day, reserve, mniej niż 3 Conditions i broken building. Nie dodano kategorii, stanów UNKNOWN ani nowych kodów. Nowe testy Posts/Buildings utrwalają dane wejściowe, od których późniejsza modularizacja walidacji będzie zależeć.

## Compare: charakterystyka i istniejące problemy

**CONFIRMED CURRENT BEHAVIOR / CONFIRMED BUG A:** `services/comparison.py::get_most_recent_completed` sortuje inne ukończone Sieges według daty i ID malejąco, bez warunku, że są starsze od wskazanego Siege. Test na bazie pokazuje, że dla target 2026-01-01 funkcja wybiera complete 2026-02-01. **DESIRED FUTURE BEHAVIOR:** Decyzja produktowa, czy domyślne „poprzednie ukończone Siege” ma bezwzględnie oznaczać wcześniejszy cykl. **IMPACT:** Porównanie może opisać przyszły cykl jako wcześniejszy. Nie zmieniono kodu produkcyjnego.

**CONFIRMED CURRENT BEHAVIOR / CONFIRMED BUG B:** `services/comparison.py::_load_assignments` filtruje po bieżącym `Member.is_active`. Test na bazie pokazuje, że ten sam historyczny wynik zawiera członka, gdy jest aktywny, i staje się pusty po jego dezaktywacji. **DESIRED FUTURE BEHAVIOR:** Ustalić, czy historyczne Compare ma być niezmienne, czy ma świadomie odzwierciedlać bieżącą listę aktywnych członków. **IMPACT:** Raport historyczny może zmienić się bez zmiany danych któregokolwiek Siege. Istniejące `test_comparison.py` już chroni filtr obecnie nieaktywnych członków; nowy test pokazuje konsekwencję historyczną. Nie zmieniono kodu produkcyjnego.

## Historyczna izolacja cykli

Nowe testy obejmują osobne `Building`, `Post`, `post_active_condition`, `BuildingGroup` i `Position` dla dwóch Sieges. Test Clone sprawdza odrębne miejsca i kopię `SiegeMember` oraz to, że nowe aktywne Conditions są puste, a historyczne powiązania źródła pozostają. Istniejący `test_remove_siege_member.py::test_remove_siege_member_does_not_affect_other_sieges` chroni izolację członkostwa przy usuwaniu; `test_deactivate_stale_siege_member.py` charakterystyzuje celowe globalne efekty dezaktywacji na planowane Sieges. Izolacja nie oznacza, że globalny Member nigdy nie wpływa na widoki historii — właśnie to pokazuje Compare bug B.

## Granica uwierzytelnienia

Istniejące `test_auth.py` sprawdza odmowę bez auth, poprawny/niepoprawny token usługi, cookie JWT oraz publiczne health/version i zachowanie auth login/callback. `test_config_endpoint.py` chroni publiczne config, a testy innych tras sprawdzają zastosowanie obecnej zależności `get_current_user`. Nie dodano osobnego testu, bo aktualne pokrycie jest wystarczające dla tego zadania. Nie projektowano poświadczeń Scannera.

## Ograniczenia i świadomie odłożone obszary

- Nie dodano testów Scanner, ID Raid, snapshotów, UNKNOWN, Tower Bonus, Gear Audit, Fleet Management ani UI.
- `backend/tests/test_schema.py` wymaga działającego PostgreSQL i jest standardowo pomijany według `CLAUDE.md`; nie uruchomiono go lokalnie.
- `backend/tests/integration/sidecar/` oczekuje Windowsowego `bot/.venv/Scripts/python.exe`, którego w tym checkoutcie brak. Nie zmieniono infrastruktury sidecara ani bota.
- Nie rozstrzygnięto przyszłej semantyki Compare A/B ani aktualności `matched_condition_id` po wymianie Conditions.

## Polecenia i wyniki

Uruchomiono testy przez lokalne środowisko Python 3.12 z zależnościami `backend/requirements-dev.txt` w katalogu TEMP, bez dodawania środowiska do repozytorium.

| Polecenie (z katalogu `backend/`) | Wynik |
|---|---|
| `python -m pytest tests/test_posts.py tests/test_buildings.py tests/test_validation.py tests/test_comparison.py tests/test_auth.py tests/test_lifecycle.py tests/test_sieges.py tests/test_remove_siege_member.py -q --ignore=tests/test_schema.py` przed zmianami | 107 passed |
| `python -m pytest tests/test_manager_rotation_baseline.py -q --tb=short` po dodaniu | Początkowo 10 passed, 1 failed: test zakładał, że SQLite nie użyje ponownie usuniętego ID; poprawiono asercję do zachowania przypisania |
| To samo po korekcie i formatowaniu | 11 passed |
| `python -m pytest --ignore=tests/test_schema.py -q --tb=short` | 498 passed, 1 failed, 45 errors; niepowodzenia lokalnego środowiska opisane niżej |
| `python -m pytest --ignore=tests/test_schema.py --ignore=tests/integration/sidecar --deselect=tests/test_config.py::TestSettingsDefaults::test_auth_disabled_defaults_to_false -q --tb=short` | 495 passed, 1 deselected |
| `ruff check tests/test_manager_rotation_baseline.py` i `black --check tests/test_manager_rotation_baseline.py` | Ruff passed; po `black` format testu jest zgodny |

**Pre-existing/environmental failure:** `test_config.py::TestSettingsDefaults::test_auth_disabled_defaults_to_false` zwraca `True` przy lokalnym konstruowaniu `Settings`, mimo oczekiwanego `False`. Próba usunięcia `AUTH_DISABLED` z środowiska procesu nie zmieniła wyniku. Możliwy wpływ lokalnej konfiguracji; nie odczytywano plików `.env`, więc źródła nie potwierdzono. Ten test nie został dodany w tym zadaniu. 45 błędów setup sidecara to brak interpretera Windows w `bot/.venv`, nie regresja dodanych testów. Praktyczny szeroki zestaw bez tych lokalnych ograniczeń jest zielony.

## Zmienione pliki i stan końcowy

- Nowy: `backend/tests/test_manager_rotation_baseline.py` — 11 testów regresyjnych.
- Nowy: `docs/MANAGER_REGRESSION_BASELINE.md` — ten raport.
- Istniejący `docs/SCANNER_MANAGER_INTEGRATION_AUDIT.md` był nieśledzony przed pracą i pozostaje niezmieniony.
- Nie wykonano commit ani push.
