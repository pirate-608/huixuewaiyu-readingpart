# Install & configuration guide (for the agent)

> **Audience: the execution agent** (installs / configures this tool). Developers
> see `CLAUDE.md`. Step 0 decides which host you are in (DSH / Codex / Claude Code).

You are helping the user install and configure **huixuewaiyu-readingpart**, an
automation tool for ZJU 慧学外语 reading exercises.

**Supported scope: Windows 10/11 (64-bit).** Other platforms are out of scope —
tell the user instead of attempting a port.

**Run the steps in order and verify each one before moving on.** On failure,
report the **raw error** to the user. Do not skip a step and do not pretend it
succeeded.

---

## Background: what this is

Three separate artifacts with clear boundaries:

| Artifact | Installed by | Responsibility |
|---|---|---|
| **tool** | `uv tool install` | MCP server + solver. Isolated env, provides the `elang` command |
| **skill** | `elang install-skill` | Docs and the contract telling an agent what to run |
| **this repo** | `git clone` | Holds both; used for development |

The tool's dependencies live inside uv's own environment and **never touch the
user's system Python**.

**Your role**: run deterministic commands, judge the environment, handle retries,
ask the user for preferences. **Do not** hand-write config files — use
`elang setup-mcp`, which backs up, edits, verifies and rolls back on failure.

---

## Step 0: identify the host agent

Needed later for MCP registration. Three possibilities:

| agent | MCP registration location | Format |
|---|---|---|
| **Claude Code** | `<project>/.mcp.json` | JSON |
| **DSH** | `~/.dsh/profiles/<profile>/cordis.patch.yml` | YAML |
| **Codex** | `~/.codex/config.toml` | TOML |

**If unsure, ask the user.** Do not guess: guessing writes to the wrong file.

---

## Step 1: install the tool

Confirm `uv` exists. On Windows it can be installed with winget:

```powershell
winget install --id=astral-sh.uv -e
```

Then install the tool:

```bash
uv tool install git+https://github.com/pirate-608/huixuewaiyu-readingpart.git
```

If GitHub is unreliable, use the Gitee mirror — same content:

```bash
uv tool install git+https://gitee.com/pirate-608/huixuewaiyu-readingpart.git
```

### Version policy

Without an `@` suffix you get the **latest commit on the default branch**, which
is fine for tracking development. For a reproducible install, pin a tag:

```bash
uv tool install "git+https://github.com/pirate-608/huixuewaiyu-readingpart.git@v0.1.1"
uv tool upgrade elang-reading                 # move to the default branch head
uv tool install --force "git+...@v0.1.1"      # switch to a specific version
```

The version must agree in four places; CI enforces this at release time:

| Location | Example |
|---|---|
| `pyproject.toml` `version` | `0.1.1` |
| git tag (with a `v` prefix) | `v0.1.1` |
| wheel filename | `elang_reading-0.1.1-py3-none-any.whl` |
| bundle `VERSION` and `/latest.json` `version` | `0.1.1` |

Check the running version:

```bash
elang --version        # same value appears on the first line of elang doctor
```

**Verify:**

```bash
elang list
```

It should list `doctor` `init-env` `install-browser` `setup-mcp` `install-skill`
`run` `mcp`, plus the answering verbs `pending` `answer` `skip` `continue` `stop`.

### No uv available: offline bundle

If `uv` cannot be installed, use the offline bundle. It contains a Python runtime
and every dependency; **installing requires no network access**.

Download `elang-bundle-win64.zip` from the repository's Releases page, unzip it
anywhere, then run from that directory:

```powershell
.\install.cmd                    # installs to %LOCALAPPDATA%\elang
```

Common options:

| Option | Effect |
|---|---|
| `-Target D:\elang` | install somewhere else |
| `-Check` | report state only, change nothing |
| `-Uninstall` | remove it (only the PATH entry it added; browser profile and user data are kept) |
| `-NoPath` | do not touch PATH, call by absolute path |
| `-NoDoctor` | skip the post-install self check |

It prints the launcher path, by default `%LOCALAPPDATA%\elang\bin\elang.cmd`.
**Open a new terminal** before `elang` appears on PATH.

The two install paths do not interfere: the bundle lives in
`%LOCALAPPDATA%\elang`, the uv copy in `%APPDATA%\uv\tools`, and `-Uninstall`
never touches the uv one.

### Optional: captcha OCR (off by default)

`ddddocr` is an **optional dependency**; `uv tool install` does not install it.
That is intentional: it drags in onnxruntime + opencv and is large, so
`elang doctor` reporting `ddddocr MISSING` is normal.

Install it to get automatic recognition:

```bash
uv tool install --with ddddocr --with Pillow git+https://github.com/pirate-608/huixuewaiyu-readingpart.git
```

Without it the tool still works; a captcha is handed to a vision model or solved
by hand (see stage 3 of `SKILL.md`). **Key precondition**: the hand-off requires
an agent that can actually read images. If yours cannot, set
`ELANG_CAPTCHA_MANUAL=1` so the user types the code, otherwise that article waits
the full 600 seconds for nothing.

**If `uv` is missing**: say so and **do not install it yourself** (that is a
system-level decision). Alternative: `git clone`, then create a venv
(`python -m venv .venv`, `pip install -r requirements.txt` inside it) and run
`scripts/elang_reader.py` from the checkout.

---

## Step 2: install a browser

```bash
elang install-browser
```

**Verify:**

```bash
elang doctor
```

The `browser` section should show `launch: ok`.

**Notes:**

- Reuse first, download second: an existing Chromium build means nothing to do;
  otherwise an installed Chrome / Edge is reused with **no network and no
  download**; only when neither exists does it download ~680 MB
- `--bundled` forces the bundled build; `--shared` installs into Playwright's
  shared cache
- When a download is needed, a **network/TLS error** is usually transient →
  **just retry** (it resumes)

---

## Step 3: configure credentials (needs the user)

```bash
elang init-env          # writes a .env template in the workspace root
```

Then ask **the user** to fill their student ID and password into that `.env`.

> **Never read, echo, log or relay the password**, and do not ask the user to
> paste it into the conversation.

**Verify:**

```bash
elang doctor
```

The `credentials` section should show `username: set` and `password: set`.

**Credential resolution order** (for troubleshooting):

```
1. $ELANG_ENV_FILE                     explicit
2. <working dir>/.env                  workspace root  <- the convention
3. ~/.elang/.env                       fallback

Both key spellings are accepted (the ELANG_ prefixed one wins):
    ELANG_CAS_USERNAME  /  CAS_USERNAME
    ELANG_CAS_PASSWORD  /  CAS_PASSWORD
Real environment variables override every file above, for both spellings.
```

`doctor` shows **which file was actually read** and where each value came from. If
it says `fallback` instead of `workspace`, the user did not start in the project
root.

---

## Step 4: register the skill

**Ask the user first**: global (all projects) or this project only?

```bash
elang install-skill --agent <agent from step 0> --scope <global|project>
```

**Verify:**

```bash
elang install-skill --agent <agent> --scope <scope> --check
```

It should report `present`.

**Notes:**

- **DSH and Codex share `~/.agents/skills`**, so installing for both writes one
  directory
- `project` installs inside the project, **takes precedence over global**, and can
  be committed so collaborators get it

---

## Step 5: register MCP

```bash
elang setup-mcp --host <agent from step 0>
```

**Preview the change first** (optional, recommended the first time):

```bash
elang setup-mcp --host <agent> --dry-run
```

**Safety guarantee**: the script backs up, edits structurally with a parser,
re-parses to verify, and rolls back on failure. It **prints only the lines it
adds** and never echoes the whole file (`~/.codex/config.toml` may hold plaintext
API keys).

**Verify**: the script verifies itself. Afterwards the agent must be restarted:

| agent | What is needed |
|---|---|
| Claude Code | restart, or reload the project |
| DSH | **restart DSH** (the profile is recomposed) |
| Codex | restart Codex |

---

## Step 6: report back

Tell the user:

1. the tool version and path
2. browser status
3. credential status (only `set` / `missing`, **never the value**)
4. where the skill was installed
5. whether MCP registration succeeded
6. **what the user still has to do** (usually: restart the agent)

---

## Important: the MCP server must run outside the file sandbox

Measured: **Playwright cannot start a browser inside a restricted file sandbox.**

- its driver goes through `asyncio.create_subprocess_exec`, which needs a
  **named** pipe on Windows
- the sandbox refuses `CreateFile("\\.\pipe\...")` with `WinError 5`
- the sync API behaves the same, because it is asyncio underneath

**DSH's `failOnStartupError: true` exists so this kind of failure is visible**,
instead of a silently missing tool.

If `elang_status` errors right after registration → the server never connected
(check the path / config format). If `elang_status` works but `elang_start` fails
→ the browser could not start (usually the sandbox).

---

## Troubleshooting

| Symptom | Cause | Action |
|---|---|---|
| `elang: command not found` | not installed, or not on PATH | rerun `uv tool install`; tell the user to reopen the terminal |
| `elang doctor` reports `EPERM`/`mkdtemp` | temp directory not writable | point `TEMP`/`TMP` at a writable directory |
| `browser launch: FAILED` | no usable browser | `elang install-browser` (reuses installed Chrome/Edge first; retry on network errors) |
| `credentials ... (missing)` | no `.env` | `elang init-env`, let the user fill it |
| `WARNING: ... OUTSIDE this interpreter's tree` | borrowed dependencies | rebuild the isolated env (`uv tool install`) |
| MCP tools missing after registration | agent not restarted | restart it |
| `elang_status` errors | server not connected | check the `command` path and config format |
| `elang_start` fails, `status` is fine | browser / sandbox problem | see the sandbox note above |
| login page unreachable or login fails | proxy/TUN conflicts with the site's network restrictions | turn off TUN and the global proxy, or let `elang.zju.edu.cn` and `zjuam.zju.edu.cn` connect directly |

---

## Do not

- **Do not** hand-write or hand-edit an agent's config file (use `elang setup-mcp`)
- **Do not** read or relay the user's password
- **Do not** install `uv` on your own (ask first)
- **Do not** guess the scope (ask the user)
- **Do not** swallow an error to look successful