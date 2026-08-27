# Notification CRLF Sanitization + Portfolio Alert Category Label Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two deferred notification bugs found during the 2026-07-31 chart-alert interval-label audit and the 2026-07-30 notification redesign, but never actioned:

1. **Silent email-delivery-failure bug:** a `\r`/`\n` embedded in any free-text field interpolated into an SMTP `Subject:` header (e.g. an alert rule name pasted with a line break) makes `email.message.Message` raise `HeaderParseError`/`HeaderWriteError` the instant the header is set — and that exception is caught by `dispatch.py`'s broad `except Exception` and silently logged, so the entire email is dropped with zero user-visible signal. Fix by sanitizing header values at the single SMTP-boundary choke point (`gmail.py::send_gmail`), which protects every current and future caller (chart alerts, portfolio alerts, strategy watches) without touching three separate call sites.
2. **Missing portfolio-alert category label:** the 2026-07-30 notification redesign (`d9733d5`) deliberately dropped the old `Bamendjou Portfolio Alert — SYMBOL [ALERT_TYPE]` Telegram headline in favor of a plain-language `SYMBOL — Type label` headline, but this also removed the only signal that told the user *which system* sent the alert. Chart-alert, portfolio-alert, and strategy-watch notifications can all land in the same Telegram chat, and the current portfolio headline (e.g. `CLX — Stop hit`) is indistinguishable in kind from a chart-alert or strategy-watch headline. Fix by restoring a short `Portfolio:` category prefix on the Telegram headline only (the email `Subject:` line already carries `Bamendjou Portfolio Alert —` and needs no change) — keeping the plain-language body the redesign intended, while giving the user back a way to tell alert sources apart at a glance.

**Architecture:** Task 1 touches only `backend/app/services/notifications/gmail.py` — the shared SMTP send path every notification builder (`chart_alerts.py`, `alert_notifier.py`, `strategy_watch_evaluator.py`) already funnels through via `dispatch.py`. Task 2 touches only `backend/app/services/notifications/alert_notifier.py`'s `_build_notification()` — the single function that builds every portfolio-alert email/Telegram body. Neither task touches chart-alert or strategy-watch notification text (see Self-Review Notes for why that's explicitly out of scope, not an oversight).

**Tech Stack:** Python 3 / FastAPI (backend only — no frontend changes). Test via pytest + pytest-asyncio.

---

### Task 1: Sanitize CR/LF out of the SMTP `Subject:` header at the send boundary

**Files:**
- Modify: `backend/app/services/notifications/gmail.py:13-41`
- Test: `backend/tests/test_notifications.py` (`TestGmail` class)

Today, `send_gmail()` sets the header directly from the caller-supplied `subject` string with no sanitization:

```python
async def send_gmail(
    to: str,
    subject: str,
    body: str,
    smtp_host: str = 'smtp.gmail.com',
    smtp_port: int = 465,
    smtp_user: str = '',
    smtp_password: str = '',
) -> bool:
    """Send plain-text email via SMTP. Runs smtplib in a thread to avoid blocking."""
    user = smtp_user or os.getenv('BAMENDJOU_GMAIL_USER', '')
    password = smtp_password or os.getenv('BAMENDJOU_GMAIL_PASSWORD', '')
    if not user or not password:
        logger.warning('Gmail not configured; skipping send')
        return False

    def _send() -> None:
        msg = MIMEText(body, 'plain')
        msg['Subject'] = subject
        msg['From'] = user
        msg['To'] = to
        with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
            server.login(user, password)
            server.send_message(msg)

    logger.info('Sending email to %s via %s:%s', to, smtp_host, smtp_port)
    await asyncio.to_thread(_send)
    logger.info('Email delivered to %s', to)
    return True
```

Verified directly in this Python install (3.14.3) — the assignment itself does **not** raise; the exception fires during serialization (`msg.as_string()`, which is exactly what `smtplib`'s `send_message()` calls internally via `Generator.flatten()`):

```python
>>> from email.mime.text import MIMEText
>>> msg = MIMEText('body', 'plain')
>>> msg['Subject'] = 'Bad subject\r\nBcc: evil@example.com'   # no exception here
>>> msg.as_string()
email.errors.HeaderParseError: header value appears to contain an embedded header: 'Bad subject\nBcc: evil@example.com'
```

This matters for how Task 1's test has to be written (see Step 1) — a test that mocks `smtplib.SMTP_SSL` without also making the mocked `send_message()` call `.as_string()` on the message it receives would never trigger this exception at all, before or after the fix, and would prove nothing.

The exception fires inside `_send()` (during `server.send_message(msg)`), propagates out of `await asyncio.to_thread(_send)`, out of `send_gmail()` (which has no try/except of its own), and is only ever caught by the caller — `dispatch.py::_safe_notify()`:

```python
async def _safe_notify(channel: str, _subject: str = '', **kwargs) -> None:
    try:
        if channel == 'gmail':
            sent = await send_gmail(**kwargs)
            ...
    except Exception:
        logger.error('Alert notification failed (channel=%s)', channel, exc_info=True)
```

This is **not** a header-injection vector — `email.message.Message` raises rather than smuggling extra headers through — it is a delivery-reliability bug: any `\r`/`\n` in a subject-bound value (today: `rule_label`/`sym` in `chart_alerts.py`, `symbol` in `alert_notifier.py`, `ev.symbol` in `strategy_watch_evaluator.py` — all free text with no format constraint) silently drops the notification with nothing but a log line.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_notifications.py`, inside `class TestGmail`, add this test anywhere in the class (order doesn't affect pytest collection) — it mocks `smtplib.SMTP_SSL` the same way the existing tests do, but makes the mocked `send_message()` call `.as_string()` on the message it receives, mirroring what `smtplib` actually does internally during a real send. Without that, the mock would swallow `HeaderParseError` behind an unconditional `MagicMock` and the test would prove nothing (see the repro above):

```python
    @pytest.mark.asyncio
    async def test_gmail_sends_successfully_when_subject_contains_crlf(self):
        from app.services.notifications.gmail import send_gmail
        with patch('app.services.notifications.gmail.smtplib.SMTP_SSL') as mock_smtp:
            mock_server = MagicMock()
            # smtplib.SMTP.send_message() serializes the message internally
            # (Generator.flatten() -> msg.as_string()) -- that serialization,
            # not the header assignment, is what raises HeaderParseError on an
            # embedded CR/LF. Mimic it here so this test actually exercises
            # the real failure mode instead of masking it behind a mock that
            # never touches the message content.
            mock_server.send_message.side_effect = lambda msg: msg.as_string()
            mock_smtp.return_value.__enter__.return_value = mock_server
            ok = await send_gmail(
                to='test@example.com',
                subject='Bamendjou Chart Alert - Bad\r\nBcc: evil@example.com - DG [Daily chart]',
                body='Body', smtp_user='user@gmail.com', smtp_password='app-pass',
            )
            assert ok is True
            sent_msg = mock_server.send_message.call_args[0][0]
            assert '\r' not in sent_msg['Subject']
            assert '\n' not in sent_msg['Subject']
            assert sent_msg['Subject'] == 'Bamendjou Chart Alert - Bad Bcc: evil@example.com - DG [Daily chart]'
```

Also add this standalone (non-async, no mocking needed) unit test for the sanitizer itself, anywhere at module level in the same file:

```python
def test_sanitize_header_value_collapses_crlf_to_single_space():
    from app.services.notifications.gmail import _sanitize_header_value
    assert _sanitize_header_value('Bad\r\nBcc') == 'Bad Bcc'
    assert _sanitize_header_value('Bad\rBcc') == 'Bad Bcc'
    assert _sanitize_header_value('Bad\nBcc') == 'Bad Bcc'
    assert _sanitize_header_value('Bad\r\n\r\nBcc') == 'Bad Bcc'
    assert _sanitize_header_value('No newlines here') == 'No newlines here'
```

- [ ] **Step 2: Run both tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_notifications.py -v -k "test_gmail_sends_successfully_when_subject_contains_crlf or test_sanitize_header_value_collapses_crlf_to_single_space"`
Expected: both FAIL/ERROR —
- `test_gmail_sends_successfully_when_subject_contains_crlf` errors with `email.errors.HeaderParseError: header value appears to contain an embedded header: 'Bamendjou Chart Alert - Bad\nBcc: evil@example.com - DG [Daily chart]'`, raised from the `side_effect` lambda's `msg.as_string()` call inside `_send()`, propagating out of `send_gmail()` uncaught.
- `test_sanitize_header_value_collapses_crlf_to_single_space` errors with `ImportError`/`AttributeError` — `_sanitize_header_value` doesn't exist yet.

- [ ] **Step 3: Implement the sanitizer and wire it in**

In `backend/app/services/notifications/gmail.py`, add `import re` to the existing import block at the top of the file (alongside `asyncio`, `logging`, `os`, `smtplib`), then add the helper function after the module-level `logger` and before `send_gmail`:

```python
_HEADER_NEWLINES_RE = re.compile(r'[\r\n]+')


def _sanitize_header_value(value: str) -> str:
    """Collapse CR/LF runs to a single space so a free-text value (e.g. an
    alert rule name pasted with a line break) can't produce a multi-line SMTP
    header.

    email.message.Message doesn't reject an embedded newline at assignment
    time -- it raises HeaderParseError/HeaderWriteError later, during
    serialization (msg.as_string() / the Generator smtplib.send_message()
    calls internally) -- and dispatch.py's _safe_notify() catches Exception
    broadly around the whole send, so that raise never surfaces anywhere. Net
    effect without this: any interpolated field containing a stray '\\r' or
    '\\n' silently drops the entire notification, every channel, with only a
    log line to show for it. A plain .replace('\\r', ' ').replace('\\n', ' ')
    would turn a CRLF pair into two spaces instead of one -- collapsing the
    whole run in one regex pass avoids that.
    """
    return _HEADER_NEWLINES_RE.sub(' ', value)
```

Then change the `_send()` closure's three header assignments from:

```python
        msg = MIMEText(body, 'plain')
        msg['Subject'] = subject
        msg['From'] = user
        msg['To'] = to
```

to:

```python
        msg = MIMEText(body, 'plain')
        msg['Subject'] = _sanitize_header_value(subject)
        msg['From'] = _sanitize_header_value(user)
        msg['To'] = _sanitize_header_value(to)
```

`subject` is the field this task is scoped to fix (built from free-text alert data), but `From`/`To` go through the exact same `msg[...] = ...` mechanism and would crash identically on an embedded CR/LF (e.g. a misconfigured `to` address in `settings.yaml`) — sanitizing all three is what makes the "single SMTP-boundary choke point" claim in this plan's Architecture section actually true, at zero extra cost. `server.login(user, password)` a few lines below is left using the raw, unsanitized `user` — that's the real credential, not a header, and sanitizing it would only mask a genuinely broken login value instead of surfacing it.

- [ ] **Step 4: Run both tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_notifications.py -v -k "test_gmail_sends_successfully_when_subject_contains_crlf or test_sanitize_header_value_collapses_crlf_to_single_space"`
Expected: both PASS.

- [ ] **Step 5: Run the full notification test file to check for regressions**

Run: `cd backend && python -m pytest tests/test_notifications.py -v`
Expected: PASS, all tests — `test_gmail_send_called_with_correct_params` and `test_gmail_skips_when_not_configured` use subjects/addresses with no `\r`/`\n`, so `_sanitize_header_value()` is a no-op for them.

- [ ] **Step 6: Run the broader alert-notification suites that exercise `send_gmail` end-to-end**

Run: `cd backend && python -m pytest tests/test_notifications.py tests/test_alert_notifier.py tests/test_chart_alerts_notification_text.py tests/test_strategy_watch_evaluator.py -v`
Expected: PASS, all tests — these are the suites covering the three real callers (`alert_notifier.py`, `chart_alerts.py`, `strategy_watch_evaluator.py`, all named in this plan's Architecture section) whose subject strings now pass through the new sanitizer; none of their existing fixtures contain `\r`/`\n`, so no existing assertion changes.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/notifications/gmail.py backend/tests/test_notifications.py
git commit -m "fix(notifications): sanitize CR/LF out of SMTP headers"
```

---

### Task 2: Restore a `Portfolio:` category label on the Telegram headline

**Files:**
- Modify: `backend/app/services/notifications/alert_notifier.py:139-181`
- Modify: `backend/tests/test_alert_notifier.py:159-178`

Today, `_build_notification()`'s Telegram `html` body has no category signal at all — its bold first line is just `SYMBOL — Type label`:

```python
    html = (
        f'<b>{html_lib.escape(symbol)} — {html_lib.escape(type_label)}</b>\n'
        f'{html_lib.escape(reason)}\n\n'
        f'Triggered: {date_str}, {time_str} {_TZ_LABEL}\n'
        f'{still_html}'
    )
```

For a `STOP_REACHED` alert on `CLX`, this renders `<b>CLX — Stop hit</b>` — identical in shape to what a chart-alert or strategy-watch headline could look like, so a user with all three notification sources pointed at the same Telegram chat has no way to tell which system fired without reading further into the body. The email `Subject:` line does not have this problem — it already reads `Bamendjou Portfolio Alert — CLX: Stop hit` (built a few lines above and unchanged by this task) — only the Telegram headline lost its category context in the 2026-07-30 redesign.

This is a deliberate, tested behavior change from `d9733d5`, not an oversight: `test_telegram_mirrors_email_and_shows_cet` in `test_alert_notifier.py` explicitly pins the no-prefix format with a comment explaining why:

```python
    # Telegram's bold first line is the plain-language headline (symbol + type),
    # not the raw "Bamendjou Portfolio Alert" subject line.
    assert html.startswith('<b>CLX — Stop hit</b>')
```

This task restores category context without reverting to the old verbose subject-as-headline format — `Portfolio:` is a 10-character prefix, not the full `Bamendjou Portfolio Alert — SYMBOL [ALERT_TYPE]` string the redesign moved away from.

- [ ] **Step 1: Update the existing test to expect the restored prefix**

In `backend/tests/test_alert_notifier.py`, change `test_telegram_mirrors_email_and_shows_cet` (currently lines 159-178) from:

```python
def test_telegram_mirrors_email_and_shows_cet(captured):
    assert an.notify_alert('CLX', 'STOP_REACHED', 'Stop breached — CLX below $89.79',
                           'rec-1', _TS) is True
    subject, plain, html = captured[0]

    # Time is labelled CET in both channels.
    assert 'CET' in _time_line(plain)
    assert 'CET' in html

    # Telegram body carries the same plain-language content as the email body:
    # symbol + human-readable type label, the reason, and a Triggered: line.
    for text in ('CLX', 'Stop hit', 'Triggered:'):
        assert text in plain
        assert text in html
    # Telegram's bold first line is the plain-language headline (symbol + type),
    # not the raw "Bamendjou Portfolio Alert" subject line.
    assert html.startswith('<b>CLX — Stop hit</b>')
    # Symbol and trigger text appear in the Telegram message.
    assert 'CLX' in html
```

to:

```python
def test_telegram_mirrors_email_and_shows_cet(captured):
    assert an.notify_alert('CLX', 'STOP_REACHED', 'Stop breached — CLX below $89.79',
                           'rec-1', _TS) is True
    subject, plain, html = captured[0]

    # Time is labelled CET in both channels.
    assert 'CET' in _time_line(plain)
    assert 'CET' in html

    # Telegram body carries the same plain-language content as the email body:
    # symbol + human-readable type label, the reason, and a Triggered: line.
    for text in ('CLX', 'Stop hit', 'Triggered:'):
        assert text in plain
        assert text in html
    # Telegram's bold first line restores a short "Portfolio:" category tag so
    # portfolio alerts stay visually distinguishable from chart-alert and
    # strategy-watch alerts landing in the same Telegram chat, while keeping
    # the plain-language "symbol — type" headline from the July 30 redesign
    # (it does not revert to the old verbose "Bamendjou Portfolio Alert —
    # SYMBOL [ALERT_TYPE]" subject line).
    assert html.startswith('<b>Portfolio: CLX — Stop hit</b>')
    # Symbol and trigger text appear in the Telegram message.
    assert 'CLX' in html
```

- [ ] **Step 2: Add a reminder-path regression test**

`_build_notification()` builds `html` from one shared f-string used for both the first send and reminders — add a test pinning that the prefix survives on reminders too, since nothing else in the file checks the headline text on a second (reminder) send. Add this new test immediately after `test_telegram_mirrors_email_and_shows_cet`:

```python
def test_reminder_telegram_headline_keeps_portfolio_prefix(captured):
    an.notify_alert('CLX', 'STOP_REACHED', 'Stop breached — CLX below $89.79', 'rec-1', _TS)
    an.notify_alert('CLX', 'STOP_REACHED', 'Stop breached — CLX below $89.79', 'rec-1', _TS)
    _subject, _plain, html = captured[1]
    assert html.startswith('<b>Portfolio: CLX — Stop hit</b>')
    assert 'Still active as of' in html
```

- [ ] **Step 3: Run both tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_alert_notifier.py -v -k "test_telegram_mirrors_email_and_shows_cet or test_reminder_telegram_headline_keeps_portfolio_prefix"`
Expected: both FAIL — current code renders `<b>CLX — Stop hit</b>`, not `<b>Portfolio: CLX — Stop hit</b>`.

- [ ] **Step 4: Add the `Portfolio:` prefix**

In `backend/app/services/notifications/alert_notifier.py`, change the comment and `html` assignment in `_build_notification()` (currently lines 161-181, including the trailing `return`) from:

```python
    # Telegram mirrors the email body exactly (same content, same order), with a
    # bold first line equal to the plain-language headline. Telegram's HTML
    # parse_mode only recognizes a small tag allowlist (b/i/u/s/a/code/pre/
    # blockquote) -- NOT <br> or any block tag. An unsupported tag makes the Bot
    # API reject the whole message with a 400, which dispatch.py's error
    # handling swallows into a log line with no user-visible signal. Line breaks
    # must be plain '\n', exactly like the plain-text body -- Telegram renders
    # literal newlines as line breaks natively in HTML mode.
    # `reason` is built internally from f-string templates (see
    # alert_generator.py / portfolio_alert_monitor.py) so it's not truly
    # free-form user input today, but `symbol` and `alert_type` are caller-
    # supplied strings with no enforced format -- escaping all three is cheap
    # insurance against the same silent-Telegram-failure mode the <br> bug
    # caused, just via unexpected '<'/'&' characters instead of a hardcoded tag.
    html = (
        f'<b>{html_lib.escape(symbol)} — {html_lib.escape(type_label)}</b>\n'
        f'{html_lib.escape(reason)}\n\n'
        f'Triggered: {date_str}, {time_str} {_TZ_LABEL}\n'
        f'{still_html}'
    )
    return subject, plain, html
```

to:

```python
    # Telegram mirrors the email body exactly (same content, same order), with a
    # bold first line equal to the plain-language headline, prefixed with a
    # short "Portfolio:" category tag. Chart-alert and strategy-watch
    # notifications can land in the same Telegram chat as these, and neither
    # the plain-language headline nor the body distinguishes source once the
    # 2026-07-30 redesign (d9733d5) dropped the old "Bamendjou Portfolio
    # Alert" prefix -- this restores just enough context to tell them apart
    # at a glance without reverting to that verbose subject-as-headline
    # format. Telegram's HTML parse_mode only recognizes a small tag
    # allowlist (b/i/u/s/a/code/pre/blockquote) -- NOT <br> or any block tag.
    # An unsupported tag makes the Bot API reject the whole message with a
    # 400, which dispatch.py's error handling swallows into a log line with
    # no user-visible signal. Line breaks must be plain '\n', exactly like
    # the plain-text body -- Telegram renders literal newlines as line breaks
    # natively in HTML mode.
    # `reason` is built internally from f-string templates (see
    # alert_generator.py / portfolio_alert_monitor.py) so it's not truly
    # free-form user input today, but `symbol` and `alert_type` are caller-
    # supplied strings with no enforced format -- escaping all three is cheap
    # insurance against the same silent-Telegram-failure mode the <br> bug
    # caused, just via unexpected '<'/'&' characters instead of a hardcoded tag.
    html = (
        f'<b>Portfolio: {html_lib.escape(symbol)} — {html_lib.escape(type_label)}</b>\n'
        f'{html_lib.escape(reason)}\n\n'
        f'Triggered: {date_str}, {time_str} {_TZ_LABEL}\n'
        f'{still_html}'
    )
    return subject, plain, html
```

- [ ] **Step 5: Run both tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_alert_notifier.py -v -k "test_telegram_mirrors_email_and_shows_cet or test_reminder_telegram_headline_keeps_portfolio_prefix"`
Expected: both PASS.

- [ ] **Step 6: Run the full `alert_notifier` test file to check for regressions**

Run: `cd backend && python -m pytest tests/test_alert_notifier.py -v`
Expected: PASS, all tests. In particular:
- `test_telegram_html_body_is_telegram_safe` only checks the tag allowlist and that `reason` text appears — `Portfolio:` is plain text, adds no tags, so this still passes.
- `test_reason_with_angle_bracket_is_escaped_not_parsed_as_a_tag` only checks escaping of `reason`, unaffected by the headline prefix.
- No other test in the file does a prefix/`startswith` check on `html` besides the two updated/added in Steps 1-2.

- [ ] **Step 7: Run the wider portfolio-alert suite to check for regressions**

Run: `cd backend && python -m pytest tests/test_alert_notifier.py tests/test_portfolio_monitor.py -v`
Expected: PASS, all tests — `test_portfolio_monitor.py` exercises the monitor that calls into `notify_alert()`; confirm it doesn't assert on the Telegram `html` headline text anywhere (checked: it monkeypatches `notify_alert` itself in every test, so it never reaches `_build_notification()`).

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/notifications/alert_notifier.py backend/tests/test_alert_notifier.py
git commit -m "feat(alerts): restore Portfolio: category label on Telegram alert headline"
```

---

## Self-Review Notes

- **Spec coverage:** both deferred items from the handoff are covered — Task 1 fixes the silent email-delivery-failure bug (CRLF into the SMTP `Subject:` header), Task 2 restores the portfolio-alert category label on Telegram.
- **No placeholders:** every step shows exact before/after code and exact commands.
- **Task 1 scope/blast-radius:** fixed at the single SMTP-boundary choke point (`gmail.py::send_gmail`), covering all three headers it sets (`Subject`, `From`, `To`) rather than just `Subject` — this protects all three real callers (`chart_alerts.py`, `alert_notifier.py`, `strategy_watch_evaluator.py`) today and any future caller, matches this codebase's existing "shared notification dispatch" pattern (`dispatch.py`'s own module docstring), and needed only one file changed instead of three. Verified the regex sanitizer is a no-op on any string with no `\r`/`\n`, so no existing subject/address (chart alerts, portfolio alerts, strategy watches) changes behavior.
- **Task 1 correctness of framing:** confirmed via direct interpreter test (Python 3.14.3, this repo's `email`/`smtplib` stdlib, reproduced twice — once misdiagnosed as firing at assignment, corrected after an adversarial audit round caught it) that an embedded CR/LF in a header value does not raise at `msg['Subject'] = subject`; it raises `HeaderParseError` later, during serialization (`msg.as_string()`, which is what `smtplib.send_message()` calls internally) — not header-injection/`Bcc` smuggling. The fix is framed correctly as a delivery-reliability bug, matching the interval-label plan's own self-review finding on the same code path, and Task 1's test (Step 1) is written to actually trigger serialization via a `send_message` mock `side_effect`, not just mock past it.
- **Task 2 is a product-scope decision, not a pure bug fix:** the no-category-prefix Telegram headline is deliberate, recent (`d9733d5`), and pinned by an existing test with an explanatory comment. This plan changes that decision based on the handoff's carried-forward, never-confirmed note that the category label should come back. The exact prefix text (`Portfolio:`) is this plan's own choice — a short tag consistent with the plain-language goal, not a restoration of the old verbose subject line, since the original "Portfolio — BAC: Stop hit" wording was itself an approximate, unconfirmed recollection, not a specification. Flagging this explicitly: if the actual desired wording differs (e.g. an emoji tag, a different separator, applying it to email too), that's a one-line change to the f-string in Task 2 Step 4, not a re-plan.
- **Task 2 blast radius:** only `alert_notifier.py`'s Telegram `html` string changes — the email `subject`/`plain` strings, which already carry `Bamendjou Portfolio Alert —`, are untouched. Chart-alert (`chart_alerts.py`'s checklist-branch Telegram headline, currently just `rule_label` with no category tag) and strategy-watch (`strategy_watch_evaluator.py`'s headline, currently `{label}: {symbol} — {strat}` with no category tag) have the identical category-ambiguity gap this task fixes for portfolio alerts, but restoring it there is out of scope here — the handoff's deferred note named portfolio alerts specifically, and extending the same treatment to the other two notification builders is a natural, low-risk follow-up but a separate decision (different headline shapes, different test files) rather than a hidden requirement of this task.
- **Type/signature consistency:** `_sanitize_header_value(value: str) -> str` (Task 1) and the `Portfolio:` prefix (Task 2) are both pure string changes — no signature, return type, or call-site change to any function other than the two edited.
