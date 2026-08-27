# Chart Alert Interval Label Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Chart-alert notifications (email subject, Telegram/email plain body, Telegram/email HTML body) show the raw interval code (e.g. `1D`, `5min`, `4h`) instead of a human-readable label (`Daily chart`, `5-minute chart`, `4-hour chart`) whenever an alert entry has no `checklist` field and falls through to the legacy formatting branch. Fix: apply the existing `_interval_label()` helper in that branch too, so raw codes never reach user-facing alert text regardless of which branch an alert takes.

**Architecture:** `backend/app/routers/chart_alerts.py`'s `_build_notification_text()` already has a human-readable interval lookup (`_interval_label()`, backed by the `_INTERVAL_LABELS` dict) and already uses it in the newer checklist-driven branch. The legacy fallback branch (used for any alert entry without a `checklist` field — today this includes at least the `DG Pre breakout` rule) was never updated to use it when that branch was added, so it still interpolates the raw `interval` value in three places: the shared `subject` line (used as both the email subject and, verbatim, as the Telegram bold headline for legacy-branch alerts), the plain-text body's `Interval:` line, and the HTML body's `<b>Interval:</b>` line. All three get one-line fixes to call `_interval_label(ival)` instead of `ival`.

**Tech Stack:** Python 3 / FastAPI (backend only — no frontend changes). Test via pytest.

---

### Task 1: Route the legacy branch's interval text through `_interval_label()`

**Files:**
- Modify: `backend/app/routers/chart_alerts.py:343` (subject line, shared by both branches)
- Modify: `backend/app/routers/chart_alerts.py:417-419` (legacy plain body)
- Modify: `backend/app/routers/chart_alerts.py:425-429` (legacy HTML body)
- Test: `backend/tests/test_chart_alerts_notification_text.py`

Today, `_build_notification_text()` builds the subject once near the top of the function, before branching on whether `checklist` is present:

```python
    subject = f'Bamendjou Chart Alert - {rule_label} - {sym} [{ival}]'
```

For an entry with `interval='1D'`, this renders `Bamendjou Chart Alert - DG Pre breakout - DG [1D]` — this exact string, with the `Trigger:`/`Values:`/`Rule:` fields that only the legacy branch produces, is what the user actually received in a real Telegram alert (screenshot on file) and prompted this fix; they had no way to know `1D` meant "daily chart" from the notification text alone. This confirms the legacy branch fires in production today for at least this rule, regardless of the exact reason a checklist wasn't attached to that particular entry (out of scope to trace further here — the fix must cover this branch either way, since `_build_notification_text()`'s own docstring already documents it as a live fallback path, not dead code).

Because `subject` is shared, fixing it here improves *both* branches' email subject line, not just the legacy one — the checklist branch already uses `_interval_label()` inside its own body text, but its returned `subject` (used for the email `Subject:` header, though not for its Telegram bold line — the checklist branch's Telegram headline is just the rule name) still carried the raw code until this fix. This is a natural consequence of `subject` being one shared variable, not scope creep — no extra files are touched.

Then, further down, the legacy (non-checklist) branch has its own plain-text and HTML bodies that separately interpolate the raw `ival` a second and third time:

```python
    plain = (f'Symbol:    {sym}\nInterval:  {ival}\n'
             f'Date:      {date_str}\nTime:      {time_str} {_TZ_LABEL}\n'
             f'Trigger:   {reason}\nValues:    {values_str}\nRule:      {rule_label}\n')

    # Telegram mirrors the email body exactly (same fields, same order), with a
    # bold first line equal to the email subject (which carries the rule name).
    # Escaped for the same reason as the checklist branch above: rule name and
    # reason text are free-form and could otherwise be parsed as invalid HTML.
    html = (f'<b>{html_lib.escape(subject)}</b>\n\n'
            f'<b>Symbol:</b>    {html_lib.escape(sym)}\n<b>Interval:</b>  {html_lib.escape(ival)}\n'
            f'<b>Date:</b>      {date_str}\n<b>Time:</b>      {time_str} {_TZ_LABEL}\n'
            f'<b>Trigger:</b>   {html_lib.escape(reason)}\n<b>Values:</b>    {html_lib.escape(values_str)}\n'
            f'<b>Rule:</b>      {html_lib.escape(rule_label)}\n')

    return subject, plain, html
```

`_interval_label()` is defined a few lines above (`chart_alerts.py:213-221`):

```python
_INTERVAL_LABELS = {
    '1D': 'Daily chart', '1W': 'Weekly chart',
    '1min': '1-minute chart', '5min': '5-minute chart', '15min': '15-minute chart',
    '1h': 'Hourly chart', '4h': '4-hour chart',
}


def _interval_label(interval: str) -> str:
    return _INTERVAL_LABELS.get(interval, f'{interval} chart')
```

Note `_interval_label()`'s fallback (`f'{interval} chart'`) passes an unrecognized `interval` value through **unescaped** — this matters for the HTML body, since `interval` is free-text at the API boundary (`AlertRuleCreate.interval: str`, no enum). The checklist branch already handles this correctly by wrapping the call in `html_lib.escape()` (see `test_interval_value_is_escaped_in_checklist_branch` in the test file) — the legacy branch's HTML fix below does the same.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_chart_alerts_notification_text.py`, inside `class TestBuildNotificationTextChecklistBranch` (this class already holds the legacy-branch tests too, e.g. `test_falls_back_to_legacy_format_without_checklist` and `test_legacy_fallback_html_is_also_escaped` — despite its name, it's the home for all `_build_notification_text()` tests in this file), add these five tests immediately after `test_legacy_fallback_html_is_also_escaped` (which ends around line 215). The first four are true TDD red/green tests for this fix (they fail before Steps 3-5, pass after). The fifth, `test_legacy_fallback_escapes_malicious_interval_in_html_body`, is a regression-safety test, not a red/green one — the legacy branch already wrapped raw `ival` in `html_lib.escape()` before this fix, so it passes both before and after; it exists to mirror the checklist branch's own `test_interval_value_is_escaped_in_checklist_branch` and pin that escaping specifically survives the switch to `_interval_label()`, since nothing else in this file would catch a future regression that dropped the wrapper from the legacy branch:

```python
    def test_legacy_fallback_uses_human_readable_interval_in_subject(self):
        entry = self._entry(checklist=[], interval='1D')
        entry.pop('checklist')
        subject, _plain, _html = _build_notification_text(entry, 'DG Pre breakout')
        assert '[Daily chart]' in subject
        assert '[1D]' not in subject

    def test_legacy_fallback_uses_human_readable_interval_in_plain_body(self):
        entry = self._entry(checklist=[], interval='5min')
        entry.pop('checklist')
        _subject, plain, _html = _build_notification_text(entry, 'DG Pre breakout')
        assert 'Interval:  5-minute chart' in plain
        assert 'Interval:  5min' not in plain

    def test_legacy_fallback_uses_human_readable_interval_in_html_body(self):
        entry = self._entry(checklist=[], interval='4h')
        entry.pop('checklist')
        _subject, _plain, html = _build_notification_text(entry, 'DG Pre breakout')
        assert '<b>Interval:</b>  4-hour chart' in html
        assert '<b>Interval:</b>  4h' not in html
        _assert_telegram_safe_html(html)

    def test_checklist_branch_subject_also_uses_human_readable_interval(self):
        # subject is built once, shared by both branches -- confirm the fix
        # benefits the checklist branch's email subject too, not just legacy.
        entry = self._entry(interval='1W')
        subject, _plain, _html = _build_notification_text(entry, 'DG Pre breakout')
        assert '[Weekly chart]' in subject
        assert '[1W]' not in subject

    def test_legacy_fallback_escapes_malicious_interval_in_html_body(self):
        # Mirrors test_interval_value_is_escaped_in_checklist_branch, but for
        # the legacy branch: _interval_label()'s fallback for an unrecognized
        # interval (f'{interval} chart') passes the raw, unconstrained value
        # through verbatim, so this specifically pins that the legacy branch's
        # html_lib.escape() wrapper (added in this fix) is present and doing
        # its job, not just that the branch mentions the interval at all.
        entry = self._entry(checklist=[], interval='<script>x</script>')
        entry.pop('checklist')
        _subject, _plain, html = _build_notification_text(entry, 'R')
        assert '<script>' not in html
        _assert_telegram_safe_html(html)
```

- [ ] **Step 2: Run the four red/green tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_chart_alerts_notification_text.py -v -k "human_readable_interval"`
Expected: all four FAIL (this filter does not match `test_legacy_fallback_escapes_malicious_interval_in_html_body`, which is checked separately in Step 2b) — current output still has `[1D]`/`5min`/`4h`/`[1W]` raw codes, e.g. `assert '[Daily chart]' in subject` fails because `subject` is literally `'Bamendjou Chart Alert - DG Pre breakout - DG [1D]'`.

- [ ] **Step 2b: Run the fifth (safety-net) test to confirm it already passes**

Run: `cd backend && python -m pytest tests/test_chart_alerts_notification_text.py -v -k "test_legacy_fallback_escapes_malicious_interval_in_html_body"`
Expected: PASS, even before the fix — the legacy branch already escapes raw `ival`, so this just confirms the starting point before Steps 3-5 swap in `_interval_label(ival)`.

- [ ] **Step 3: Fix the subject line**

In `backend/app/routers/chart_alerts.py`, change line 343 from:

```python
    subject = f'Bamendjou Chart Alert - {rule_label} - {sym} [{ival}]'
```

to:

```python
    subject = f'Bamendjou Chart Alert - {rule_label} - {sym} [{_interval_label(ival)}]'
```

- [ ] **Step 4: Fix the legacy plain body**

In the same file, change (currently lines 417-419):

```python
    plain = (f'Symbol:    {sym}\nInterval:  {ival}\n'
             f'Date:      {date_str}\nTime:      {time_str} {_TZ_LABEL}\n'
             f'Trigger:   {reason}\nValues:    {values_str}\nRule:      {rule_label}\n')
```

to:

```python
    plain = (f'Symbol:    {sym}\nInterval:  {_interval_label(ival)}\n'
             f'Date:      {date_str}\nTime:      {time_str} {_TZ_LABEL}\n'
             f'Trigger:   {reason}\nValues:    {values_str}\nRule:      {rule_label}\n')
```

- [ ] **Step 5: Fix the legacy HTML body**

In the same file, change (currently lines 425-429):

```python
    html = (f'<b>{html_lib.escape(subject)}</b>\n\n'
            f'<b>Symbol:</b>    {html_lib.escape(sym)}\n<b>Interval:</b>  {html_lib.escape(ival)}\n'
            f'<b>Date:</b>      {date_str}\n<b>Time:</b>      {time_str} {_TZ_LABEL}\n'
            f'<b>Trigger:</b>   {html_lib.escape(reason)}\n<b>Values:</b>    {html_lib.escape(values_str)}\n'
            f'<b>Rule:</b>      {html_lib.escape(rule_label)}\n')
```

to:

```python
    html = (f'<b>{html_lib.escape(subject)}</b>\n\n'
            f'<b>Symbol:</b>    {html_lib.escape(sym)}\n<b>Interval:</b>  {html_lib.escape(_interval_label(ival))}\n'
            f'<b>Date:</b>      {date_str}\n<b>Time:</b>      {time_str} {_TZ_LABEL}\n'
            f'<b>Trigger:</b>   {html_lib.escape(reason)}\n<b>Values:</b>    {html_lib.escape(values_str)}\n'
            f'<b>Rule:</b>      {html_lib.escape(rule_label)}\n')
```

- [ ] **Step 6: Run the four red/green tests to verify they now pass**

Run: `cd backend && python -m pytest tests/test_chart_alerts_notification_text.py -v -k "human_readable_interval"`
Expected: PASS, all four.

- [ ] **Step 7: Run the full notification-text test file to check for regressions**

Run: `cd backend && python -m pytest tests/test_chart_alerts_notification_text.py -v`
Expected: PASS, all tests — including the five new tests from Step 1 (the fifth, safety-net one, was already passing since Step 2b) and the pre-existing `test_falls_back_to_legacy_format_without_checklist`, `test_legacy_fallback_html_is_also_escaped`, and `test_intraday_intervals_render_as_plain_labels_not_raw_codes` (none of these pin the raw-code subject/Interval-line text, so none should break; they only check for presence of `'Interval:'`/`'Symbol:'`/`'chart'` substrings, which the fix still satisfies).

- [ ] **Step 8: Run the broader chart-alerts test suite**

Run: `cd backend && python -m pytest tests/test_chart_alerts_notification_text.py tests/test_alert_rule_disabled_cannot_fire.py tests/test_chart_alerts_composite_ws.py tests/test_composite_sustain.py -v`

(`test_alert_rule_disabled_cannot_fire.py`, `test_chart_alerts_composite_ws.py`, and `test_composite_sustain.py` are the three test files in the whole suite that call `chart_alerts.evaluate_and_notify_for_symbol(...)` directly and unmocked — that's the function that calls `_build_notification_text()`, so all three genuinely exercise the changed `subject` line end-to-end. `test_chart_alert_scheduler.py` was considered but rejected: its two tests `monkeypatch.setattr('app.routers.chart_alerts.evaluate_and_notify_for_symbol', mock_evaluate)`, so they never reach the changed code. `test_alert_router.py` was also rejected: it only covers rule CRUD, never the notify path.)

Expected: PASS, all tests.

- [ ] **Step 9: Commit**

```bash
git add backend/app/routers/chart_alerts.py backend/tests/test_chart_alerts_notification_text.py
git commit -m "fix(chart-alerts): show human-readable interval labels in the legacy notification branch"
```

---

## Self-Review Notes

- **Spec coverage:** the one requirement — raw interval codes must not reach user-facing alert text — is covered in all three places they appeared (subject, legacy plain body, legacy HTML body). The checklist branch already used `_interval_label()` before this plan; confirmed via `test_checklist_branch_subject_also_uses_human_readable_interval` that the shared `subject` fix benefits it too.
- **No placeholders:** every step shows exact before/after code and exact commands.
- **Escaping consistency:** the HTML fix wraps `_interval_label(ival)` in `html_lib.escape()`, matching the existing pattern the checklist branch already uses for the same helper (see `test_interval_value_is_escaped_in_checklist_branch` in the test file) — `_interval_label()`'s unknown-interval fallback (`f'{interval} chart'`) passes the raw, unconstrained `interval` value through verbatim, so anywhere its output reaches an HTML body it must be escaped.
- **Blast radius:** only one file changed (plus its test file). `subject` is not pattern-matched anywhere else in the codebase (checked: no test or code greps for `[1D]` or a raw interval bracket), so widening its content is safe.
- **Deferred, out of scope — pre-existing CRLF/subject-header gap found during audit, not caused by this fix:**
  - **What:** `subject = f'Bamendjou Chart Alert - {rule_label} - {sym} [{ival}]'` interpolates three unescaped, unconstrained free-text API fields into the SMTP `Subject:` header (`backend/app/services/notifications/gmail.py:31`) — `rule_label` (`AlertRuleCreate.name: str`), `sym` (`AlertRuleCreate.symbol: str`), and `interval` (via `_interval_label()`'s unescaped fallback `f'{interval} chart'` for unrecognized codes). A `\r`/`\n` in *any* of the three could hit this, not just `interval`.
  - **Why it's pre-existing, not introduced here:** `rule_label` and `sym` were already interpolated into `subject` unescaped before this fix, and so was `interval` — this plan only changes what value replaces `ival` in that position, not whether it's escaped.
  - **Actual impact (verified, not assumed):** directly reproduced in Python 3 (`email.mime.text.MIMEText`) — a `\r`/`\n`-laced subject does **not** smuggle extra headers or get delivered maliciously. `msg['Subject'] = subject` succeeds, but the later `msg.as_string()` call inside `smtplib.send_message()` raises an `email.errors` exception (`HeaderParseError` for CRLF payloads resembling a colon-delimited fake header, `HeaderWriteError` — a sibling class, not a subtype — otherwise), which `dispatch.py`'s broad `except Exception` (confirmed at `dispatch.py:36`) swallows into a log line either way. Net effect: a silently-dropped notification for that one alert — a delivery-reliability bug, not header/recipient injection.
  - **Why out of scope here:** a real fix means sanitizing/validating `name`/`symbol`/`interval` at the API boundary or in the shared subject-building path — not a one-line change inside `_build_notification_text()`.
  - **Follow-up:** worth a dedicated fix covering all three fields, framed correctly as a silent-delivery-failure bug rather than an injection vulnerability.
