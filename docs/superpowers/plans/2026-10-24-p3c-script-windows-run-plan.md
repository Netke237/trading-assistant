# P3C-SCRIPT-WINDOWS-RUN Implementation Plan (#537)

**Phase ID:** `P3C-SCRIPT-WINDOWS-RUN`  
**Tracking Issue:** [#537](https://github.com/Netke237/trading-assistant/issues/537)  
**Branch:** `board/p3c-script-windows-run-bdea78e9`  
**Scope:** `backend/scripts/p3c_data_checks.py` and its tests only  

---

## 1. Executive Summary & Root Cause Analysis

### 1.1 Windows cp1252 Encoding Crash
- **Observation:** Running `python backend/scripts/p3c_data_checks.py --sections db` on Windows with redirected stdout (or non-UTF8 console) crashes immediately on the first symbol with:
  ```
  UnicodeEncodeError: 'charmap' codec can't encode character '\u0394' in position 17: character maps to <undefined>
  ```
- **Root Cause:** Line 513 in `backend/scripts/p3c_data_checks.py` prints `|Δclose|` containing the Greek capital delta character `Δ` (U+0394). When stdout is redirected to a pipe or file on Windows, Python defaults to the system ANSI code page (`cp1252`), where `Δ` does not exist.
- **Remediation:**
  1. Dynamically reconfigure `sys.stdout` and `sys.stderr` to UTF-8 with `errors="replace"` on script entry.
  2. Make the output text ASCII-only: replace `|Δclose|` with `|delta_close|` (or `|d_close|`). Doing both ensures total safety even if stdout stream reconfiguring is bypassed.

### 1.2 Repo-Root `.env` Resolution
- **Observation:** On the mini PC (and in developer setups using `start-backend.bat`), `DATABASE_URL` is configured in the repo-root `.env` file (`.env`). Running `p3c_data_checks.py` fails with:
  ```
  DATABASE_URL resolves to SQLite (.../backend/dev.db), not Postgres. Set DATABASE_URL (environment or backend/.env) to your Postgres URL, or pass --allow-sqlite to read this file.
  ```
- **Root Cause:** `resolve_url()` in `backend/scripts/p3c_data_checks.py:107-115` only checks `BACKEND / ".env"`. It never checks the repository root `.env` (`BACKEND.parent / ".env"`), falling back to the default SQLite dev database.
- **Remediation:**
  Extend `resolve_url()` to check:
  1. `os.environ["DATABASE_URL"]` (source: `"environment"`).
  2. `BACKEND / ".env"` (source: `"backend/.env"`).
  3. `REPO_ROOT / ".env"` (`BACKEND.parent / ".env"`, source: `"repo-root .env"`).
  4. Default `Settings().DATABASE_URL` (source: `"default"`).
  Disclose the source file in the script output while ensuring the URL password remains masked (`hide_password=True`).

---

## 2. Design & Architecture

### 2.1 Output Encoding Protection
In `backend/scripts/p3c_data_checks.py`:
- At module import / start of `main()`:
  ```python
  if hasattr(sys.stdout, "reconfigure"):
      try:
          sys.stdout.reconfigure(encoding="utf-8", errors="replace")
      except Exception:
          pass
  if hasattr(sys.stderr, "reconfigure"):
      try:
          sys.stderr.reconfigure(encoding="utf-8", errors="replace")
      except Exception:
          pass
  ```
- In `report_symbol` line 513:
  Change:
  ```python
  print(f"largest one-day |Δclose| (adjusted): "
  ```
  to:
  ```python
  print(f"largest one-day |delta_close| (adjusted): "
  ```

### 2.2 Hierarchical URL Resolution & Disclosure
In `backend/scripts/p3c_data_checks.py`:
- Implement `resolve_url() -> tuple[str, str]`:
  Returns `(url, source_label)`.
  1. If `"DATABASE_URL"` in `os.environ` and `os.environ["DATABASE_URL"].strip()`:
     return `os.environ["DATABASE_URL"].strip()`, `"environment"`
  2. Check `backend_env = BACKEND / ".env"`:
     If `backend_env.is_file()`:
     Use `dotenv_values(backend_env)` or file parser. If `"DATABASE_URL"` is present and non-empty:
     return `val`, `"backend/.env"`
  3. Check `root_env = BACKEND.parent / ".env"`:
     If `root_env.is_file()`:
     Use `dotenv_values(root_env)` or file parser. If `"DATABASE_URL"` is present and non-empty:
     return `val`, `"repo-root .env"`
  4. Fallback:
     from `app.config import Settings`
     return `Settings().DATABASE_URL`, `"default"`
- Backward Compatibility with `route_url`:
  `route_url(url: str, allow_sqlite: bool) -> tuple[str, object]` signature remains unchanged.
- Output Presentation:
  To maintain 100% compatibility with existing test assertions (`assert out.splitlines()[0] == "reading ..."`):
  Line 0 remains:
  - SQLite: `reading SQLite file {target}`
  - Postgres: `reading {target.render_as_string(hide_password=True)}`
  Line 1 immediately follows:
  - `print(f"DATABASE_URL supplied by {source}")`
  This ensures:
  1. Line 0 matches all existing assertions in `test_p3c_data_checks.py` (`assert out.splitlines()[0] == ...`).
  2. The source file is clearly reported to the user.
  3. Passwords are never leaked.

---

## 3. Build Tickets

### T1 — Windows Encoding & Env Resolution Unit Tests (#537.1)
- **Role:** Author test suite `backend/tests/test_p3c_data_checks_windows.py` test-first.
- **Coverage:**
  - `test_windows_encoding_safety`: Executes `p3c_data_checks.py` in a subprocess with `PYTHONIOENCODING=cp1252` and redirected stdout/stderr against mock/fixture data. Asserts returncode 0, no `UnicodeEncodeError`, and expected output.
  - `test_resolve_url_repo_root_env`: Creates a temp root `.env`, runs `resolve_url()`, verifies it reads the root file when `backend/.env` is absent and `DATABASE_URL` is unset in environment.
  - `test_resolve_url_backend_env_precedence`: Verifies `backend/.env` takes precedence over repo-root `.env`.
  - `test_resolve_url_environ_precedence`: Verifies `os.environ["DATABASE_URL"]` takes precedence over both files.
  - `test_discloses_source_without_password`: Verifies `DATABASE_URL supplied by ...` is printed on line 1, and no secret password from `.env` is leaked.
- **Verification:** Run `python -m pytest backend/tests/test_p3c_data_checks_windows.py`. Confirm failure before implementation.

### T2 — Implementation & Full Regression (#537.2)
- **Role:** Update `backend/scripts/p3c_data_checks.py`.
- **Files:** `backend/scripts/p3c_data_checks.py`
- **Verification:**
  - `python -m pytest backend/tests/test_p3c_data_checks_windows.py` passes 100%.
  - `python -m pytest backend/tests/test_p3c_data_checks.py` passes all 25 tests.
  - Local real-environment verification: run `python backend/scripts/p3c_data_checks.py --sections db` directly from repo root; confirm it loads the root `.env` and reaches local Postgres.

---

## 4. Risks & Mitigations

1. **Risk:** Output formatting changes break existing CLI tests in `test_p3c_data_checks.py`.
   - **Mitigation:** Existing tests assert on `out.splitlines()[0] == "reading ..."`. Placing `DATABASE_URL supplied by {source}` on line 1 strictly preserves line 0.
2. **Risk:** Password in repo-root `.env` is printed in logs or terminal.
   - **Mitigation:** The source line prints only the file identifier (`"repo-root .env"`, `"backend/.env"`, `"environment"`), never the URL. The URL is printed only by SQLAlchemy's `render_as_string(hide_password=True)`.
3. **Risk:** Non-standard environments where `sys.stdout` has no `reconfigure` attribute (e.g. custom test streams).
   - **Mitigation:** Guard with `hasattr(sys.stdout, "reconfigure")` inside a `try/except`. Furthermore, replacing `|Δclose|` with ASCII `|delta_close|` guarantees the text itself is 100% encodable in cp1252 regardless of stream configuration.

---

## 5. Gate Checklist

- [ ] Does any change alter live trading signals, order sizes, or gate verdicts? **No. Script is a diagnostic tool only.**
- [ ] Are all database operations read-only? **Yes. Script enforces `SET TRANSACTION READ ONLY`.**
- [ ] Are passwords or sensitive credentials leaked in output? **No.**
