# Cloud environment and shared Codex skills

## Scope and prerequisites

These scripts prepare a Linux cloud checkout of this repository. They do not install
skills on the Windows host. The cloud image must already provide **Python 3.11** with
venv/pip, **Node 22** (frontend/.nvmrc), npm, Git, and the Codex CLI. Provision these
through the environment's supported image/configuration workflow. Backend numerical
tests must never run under an unintended Python version.

Before running setup in a managed cloud session, read the cloud runtime skill, query
`cloud_environment.environment_status`, and inspect `/etc/codex/network-policy.json`.
Keep inherited proxy, CA trust, and credential injection settings. Use the configured
GitHub identity for the private `Netke237/claude-dotfiles` repository; do not embed
tokens in scripts, URLs, or committed files. Allow the required GitHub, PyPI, and npm
destinations through the supported network configuration. Do not bypass denials.

## Installation (network enabled setup phase)

From the cloud repository root:

```bash
bash scripts/cloud/setup.sh
```

The installer clones `https://github.com/Netke237/claude-dotfiles.git` once into
`~/.local/share/codex/claude-dotfiles`. Its entire `skills/` directory is linked as
`${CODEX_HOME:-$HOME/.codex}/skills/claude-dotfiles` and `~/.agents/skills/claude-dotfiles`.
Skill contents stay in the clone, including supporting files. No contents are copied.
The `.agents` links support the current documented user discovery directory; the
`.codex` links provide the requested Codex user skills layout. New source skills
become visible through the same directory links; no fixed list is maintained.

Existing files, directories, broken links, and links to another source are preserved.
Matching links are reused. Any collision is printed and returns exit 2; resolve it
explicitly before retrying. Nothing in the repository's `.claude/skills` or
`.agents/skills`, user instructions, shell profiles, or Codex configuration is replaced.
Backend dependencies go into `.venv-cloud`; frontend dependencies use `npm ci` and
the committed lockfile. Setup does not start application services or migrate a database.

Repeat setup to repair missing links without changing the source revision. Updating
shared skills is explicit and only fast-forwards a clean `main` checkout:

```bash
python3.11 scripts/cloud/install_shared_skills.py --update
python3.11 scripts/cloud/verify_shared_skills.py
```

For an existing clone, pass `--checkout /path/to/claude-dotfiles` to the installer and
the verifier separately. The full setup wrapper uses the default clone location;
run custom installer/verifier commands separately when overriding paths. The printed
commit SHA identifies the source revision; all links continue to follow that clone.

## Startup (every fresh shell)

```bash
source scripts/cloud/startup.sh
```

This activates the existing Python 3.11 environment, checks skill discovery, handles
the session-resume notice when present, and renders project state. It requires no
skill fetch or dependency installation. Follow the handoff confirmation and task
claim rules in AGENTS.md before working. Start Codex from the repository root:

```bash
codex -C "$PWD"
```

If a skill does not appear in an existing session, restart Codex. Invoke
`$k-ticket-coordinator` or `$to-tickets` when the corresponding workflow is requested.

Optional application commands after reviewing the cloud's backend configuration:

```bash
# Separate shells; source startup.sh in the backend shell first.
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# Frontend shell, from repo root:
npm --prefix frontend run dev
```

Use environment-provided development settings. The mini PC Postgres, first history
backfill, and live provider smoke tests remain mini PC tasks (#114).

## Discovery verification and limits

```bash
python3.11 scripts/cloud/verify_shared_skills.py --workspace "$PWD"
```

The verifier starts a temporary Codex app-server, performs `initialize`, then
`skills/list` with `forceReload: true`. It checks every source `SKILL.md` resolves to
an **enabled user-scope skill** returned by Codex. A same-name repository skill cannot
satisfy this check. Missing/disabled skills, RPC failure, or timeout return nonzero.
No model turn is started. Load errors for other existing skills are printed for
visibility. Discovery verifies registration, not availability of each skill's MCP
dependencies. No cloud execution result may be claimed from Windows-only checks.

Official references: [skill locations and symlink support](https://learn.chatgpt.com/docs/build-skills)
and [app-server skills/list](https://learn.chatgpt.com/docs/app-server).

## Preparation evidence (2026-10-09)

The user selected **cloud scripts only**. No Windows user skills or existing shared
checkout were changed. The source was prepared from claude-dotfiles commit
`1d6f8719edcd8908cc8044cf2d8bb18ce4ec56f9` in an isolated checkout.

- Linux preservation tests: 7 passed in the existing `ta-backend-test:latest` image,
  with no network and a read-only script mount. Tests cover dynamic additions,
  idempotency, existing files/directories/wrong/broken links, source-aware discovery,
  and ignored-file update collisions using real Git repositories.
- Actual Codex CLI 0.160.0 `skills/list`: 44/44 shared source skills discovered as
  enabled user skills through an isolated Windows directory junction. This validates
  linked-tree scanning; Linux symbolic-link behavior was tested separately above.
- Bash syntax, Python compilation, ZIP integrity, skill metadata validation, and
  the required frontend typecheck passed.
- Full dependency installation, startup, and discovery on a managed cloud executor
  remain unrun: this chat has no attached cloud executor.

Independent code audit record (numeric/persistence gate; cap 3 rounds):

1. Reviewer `environment_audit_r1` reviewed all new setup scripts/documentation,
   `.gitignore`/`.gitattributes`, and the shared skill bundle/README against
   trading-assistant base `aaa7102cfb163f5bc60ed2332daa96e5b9a45f12` and shared base
   `1d6f8719edcd8908cc8044cf2d8bb18ce4ec56f9`. Reviewed content-manifest SHA256:
   `0f278cc70230fb4a745b67609a24cdcb57e79b584fdb727f4b3730945b65a0a1`.
   One finding: default Git pull could overwrite ignored local files. Fixed both
   installer copies with explicit fetch and `merge --ff-only --no-overwrite-ignore`,
   plus a real-Git preservation regression test.
2. Fresh reviewer `environment_audit_r2` reviewed only the guarded update and its
   regression test, including both mirrored copies and their interactions. Installer
   SHA256: `81d404c2ceee094332a33ee4c2b59bbd2b953803a72b467a809e4c52dd603693`;
   test SHA256: `a6727a1359a3d0479b58d52d6c9db4fa30f3ba5c454268009338e175e67219e1`.
   The reviewer independently reproduced the regression and passed all seven Linux
   tests. Zero gate findings; no outstanding findings. Audit rounds: **2**;
   audit clean: **true**. No merge is authorized by these preparation checks.
