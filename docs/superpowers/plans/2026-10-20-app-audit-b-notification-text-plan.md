# APP-AUDIT-B-NOTIFICATION-TEXT — Notifications help text renders literal Unicode escape (#375)

Part of #350 · programme #348.
Task ID: `APP-AUDIT-B-NOTIFICATION-TEXT` · Size XS · Complexity 1/5 · Lanes: J (presentation) & B (settings surface).

## Problem & Root Cause

In `frontend/app/(frame)/settings/page.tsx`, the `NotificationsForm` section intro currently declares:
```tsx
<SectionIntro
  title="Notifications"
  blurb="Configure alert delivery. Gmail uses SMTP (App Password), Telegram uses Bot API. Settings are persisted to the backend config file. Passwords are write-only \u2014 leave blank to keep the existing saved value."
/>
```

Because `blurb="..."` is a static JSX attribute enclosed in double quotes rather than a JavaScript expression (`{...}`), the unicode escape sequence `\u2014` is not evaluated by the compiler; instead, it is parsed and rendered as six literal characters: `\` `u` `2` `0` `1` `4`. In the browser, users viewing Settings → Notifications visibly see:
`Passwords are write-only \u2014 leave blank to keep the existing saved value.`
rather than a readable em dash (`—`).

## Scope of Changes

1. **Settings UI (`frontend/app/(frame)/settings/page.tsx`)**:
   - Replace literal `\u2014` in the `SectionIntro` `blurb` prop of `NotificationsForm` with the literal UTF-8 em dash character `—`:
     `blurb="Configure alert delivery. Gmail uses SMTP (App Password), Telegram uses Bot API. Settings are persisted to the backend config file. Passwords are write-only — leave blank to keep the existing saved value."`
   - Strictly preserve all write-only secret semantics, password handling, notification form inputs, backend API endpoints, and configuration persistence unchanged.

2. **Regression Test (`frontend/app/(frame)/settings/__tests__/NotificationsBlurb.test.tsx`)**:
   - Render the Settings page with the active section set to `'notifications'`.
   - Query the rendered `SectionIntro` text.
   - Assert that the rendered DOM text contains the em dash character `—`.
   - Assert that the rendered DOM text does not contain the literal characters `\u2014`.

## Implementation & Test Strategy (TDD)

1. **Regression test (Red -> Green)**:
   - Create `frontend/app/(frame)/settings/__tests__/NotificationsBlurb.test.tsx`.
   - Run Jest: verify test fails against the current `\u2014` literal string in `settings/page.tsx`.
2. **Apply UI fix**:
   - Update `blurb` in `frontend/app/(frame)/settings/page.tsx`.
   - Re-run Jest: verify test passes.
3. **Repository verification**:
   - `npm run typecheck` clean (0 errors).
   - Focused Jest tests pass.
   - `python scripts/state.py` clean (0 drift).

## Review & Audit Gates

1. **Independent plan audit**: spawn a fresh subagent running `bmad-review-adversarial-general` against this plan under the numeric/persistence gate. Record 0 gate findings in `docs/superpowers/audits/APP-AUDIT-B-NOTIFICATION-TEXT/plan-r1.md`.
2. **Record plan stage** in `PROJECT_STATE.json` (`plan_stage`: rounds 1, clean true; `audit_rounds`: 1).
3. **Build implementation**: create build sub-issue/ticket on #375, apply code changes and tests, verify green.
4. **Independent code audit**: spawn a fresh subagent running `bmad-review-adversarial-general` against the diff `origin/main..HEAD` under the numeric/persistence gate. Record 0 gate findings in `docs/superpowers/audits/APP-AUDIT-B-NOTIFICATION-TEXT/code-r1.md`.
5. **Self-merge**: execute self-merge of PR per `board.md` step 7 once CI passes on exact audited head.
