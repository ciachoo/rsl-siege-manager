# Manager Cleanup #1 — Historical Compare

HEAD przy rozpoczęciu: `1f1025ae7f10d27f3ca10f4b438699fd0751b466`. Stan przed pracą: `?? backend/tests/test_manager_rotation_baseline.py`, `?? docs/MANAGER_REGRESSION_BASELINE.md`, `?? docs/SCANNER_MANAGER_INTEGRATION_AUDIT.md`. Wcześniejszych raportów nie zmieniono.

## Before

- **Bug A:** `get_most_recent_completed()` mógł wybrać ukończony Siege późniejszy od targetu.
- **Bug B:** `Member.is_active` w chwili wyświetlania mógł usunąć członka z porównania historycznych przypisań, mimo że oba Siege pozostawały bez zmian.

## Product semantics

Domyślny „poprzedni Siege” oznacza ukończony Siege z najpóźniejszą datą **wcześniejszą** od daty targetu. W ramach tej samej daty wcześniejszych kandydatów wybór pozostaje deterministyczny: najwyższe ID. Endpoint ręczny nadal pozwala wybrać dowolny istniejący Siege, także późniejszy lub nieprzylegający chronologicznie. Porównanie historyczne opiera się na zapisanych przypisaniach, a późniejsza dezaktywacja Membera nie usuwa go z wyników.

## Implementation

W `backend/app/services/comparison.py::get_most_recent_completed` odczytywana jest data targetu; kandydaci muszą mieć status `complete`, inne ID i `Siege.date < target.date`. Zachowano sortowanie `date DESC, id DESC`. W `backend/app/services/comparison.py::_load_assignments` usunięto filtr bieżącego `Member.is_active` i niepotrzebne złączenie z `Member`; filtry przypisania, reserve i disabled pozostały. `compare_sieges`, schemat odpowiedzi, `backend/app/api/comparison.py` oraz frontend nie zostały zmienione. Żadna usługa zarządzania Memberami nie została zmieniona.

## Tests

Testy TDD najpierw ujawniły siedem niepowodzeń związanych z Bug A/B; po zmianie usługi `tests/test_comparison.py` i `tests/test_manager_rotation_baseline.py` zakończyły się wynikiem **28 passed**. W `test_manager_rotation_baseline.py` zastąpiono nazwy testów charakteryzujących błędy nazwami wymaganych niezmienników i dodano przypadki: wcześniejszy/późniejszy kandydat, tylko późniejszy, kilka wcześniejszych, remis daty, wykluczenie targetu/statusów innych niż complete, brak daty, nieaktywny członek z added/removed, automatyczny i ręczny endpoint HTTP. W `tests/test_comparison.py` zmieniono dwa dotychczasowe testy utrwalające błędny filtr.

Testy Compare i powiązane lifecycle/Siege: **44 passed**. Praktyczny pełny backend: **502 passed, 1 deselected** przy wyłączeniach znanych z `MANAGER_REGRESSION_BASELINE.md`: `test_schema.py` wymaga PostgreSQL, `integration/sidecar/` wymaga brakującego Windowsowego środowiska bota, a istniejący test domyślnego `auth_disabled` nie przechodzi przy lokalnych ustawieniach. `ruff check` przeszedł; pliki testowe sformatowano przez Black.

## Edge cases

- **NULL `Siege.date` targetu:** brak bezpiecznego kryterium „wcześniejszy”, więc automatyczny wybór zwraca brak kandydata, a istniejący endpoint zwraca 404. Ręczne porównanie nie ma ograniczenia daty.
- **Ta sama data co target:** nie jest wcześniejsza; kandydat jest wykluczony przez ścisłe `<`.
- **Remis między wcześniejszymi completed:** wybierane jest najwyższe ID zgodnie z wcześniejszym porządkiem.
- **Brak wcześniejszego completed:** istniejąca odpowiedź 404 pozostaje bez zmian.

## Deferred

Nie zmieniono Posts/Conditions, Buildings, Validation, Scanner, Tower Bonus, Gear Audit, Discorda, migracji ani UI. Wcześniejszy `MANAGER_REGRESSION_BASELINE.md` pozostaje zapisem stanu sprzed poprawki i dlatego zawiera dawną charakterystykę obu błędów.
