# Safety review

Every generated script goes through a review **before it is saved**. Approved scripts are cached
and not reviewed again until rebuilt. The generator is also prompted to prefer non-destructive
actions (for example, move files to the trash instead of deleting them recursively).

This is a best-effort safety net, not a sandbox. Read what you approve.

## 1. Static scan (always on)

A regex scan of the code lines (comments are ignored; plain `echo`/`printf` lines are skipped),
using Bash patterns for Bash scripts and PowerShell patterns for PowerShell scripts. Python
scripts are scanned through their syntax tree instead (see below). It reports at most one
reason per category per line. Categories:

| Category | Examples |
|---|---|
| Privilege escalation | `sudo`, `doas`, `pkexec`, `su`; `Start-Process -Verb RunAs`, `runas`, `Set-ExecutionPolicy` |
| Filesystem | recursive deletes, deletes of `/` or `~`, writes to system directories, recursive `chmod`/`chown`, disk/format tools, `dd of=`, `find -delete`, `crontab`, `systemctl enable/disable/stop/mask`; on Windows recursive `Remove-Item`, writes under `Windows`/`Program Files`, registry edits, service and scheduled-task changes |
| Networking | firewall tools (`iptables`, `ufw`, ...), `ip`/`ifconfig`/`nmcli`/`route` changes, edits to `/etc/hosts` or `resolv.conf`; on Windows `netsh`, `*-NetFirewall*`, `Set-DnsClientServerAddress`, hosts file edits |
| Remote code execution | `curl`/`wget` piped to a shell, a shell running a download, `eval $(curl ...)`; `Invoke-Expression`, `iex` |

### Python scripts

Python is parsed with `ast` (code that does not parse is risky). Import aliases are resolved, so
`from shutil import rmtree as r` is still `shutil.rmtree`. Same categories:

| Category | Examples |
|---|---|
| Privilege escalation | `os.setuid`/`setgid`/..., `os.chroot`, `ShellExecute` with `runas`, `sudo`/`su` in an embedded command |
| Filesystem | `shutil.rmtree`; deletes in a loop or of system paths; `chown`; recursive or world-writable `chmod`; writes, moves and links into system directories; `winreg` writes |
| Networking | writes to `/etc/hosts`, `resolv.conf` or the Windows hosts file; firewall/`ip`/`nmcli`/`netsh` in an embedded command |
| Remote code execution | `eval`/`exec`/`compile`, dynamic imports, `pickle`/`marshal` loads, `runpy`, `os.system`/`os.popen`, `shell=True`, commands built at run time, downloading plus executing, `ctypes`/`cffi` |

Embedded commands: literal command strings or lists passed to `subprocess`, `os.system`,
`os.exec*`/`os.spawn*` are also checked with the Bash (and, for PowerShell/`cmd`/`netsh`/...,
PowerShell) patterns, so `subprocess.run(["sudo", ...])` is caught.

### Dependencies

A Python script that declares third-party packages (PEP 723 `dependencies`) is **always** risky:
installing from PyPI runs code you have not seen. The confirmation lists the packages so you can
spot typos or typosquats. Entries must be plain PyPI requirements (name, extras, version, markers);
URLs, `@` direct references and paths are refused at generation time. Packages are installed only
after you approve, into the command's own `.venv`.

## 2. Decision model (optional)

Set `reviewer_provider` in `config.yaml` to add a second opinion. Its findings are combined with
the static scan.

### Jev and Ollaya

Jev (hosted by [TypeSafe AI](https://docs.typesafe.ai); key from
<https://console.typesafe.ai/keys>) and Ollaya (local) are classifiers: aiscript sends the
script, its language and its declared dependencies, and asks one yes/no question per category, and the model answers with a
probability. A category with probability **>= 0.5** is flagged.

The questions are:

- **Privilege escalation**: does the script escalate privileges (sudo, su, doas, pkexec, RunAs)?
- **Filesystem**: does it modify or delete files outside the working directory and home folder,
  delete data recursively or in bulk, or change system configuration?
- **Networking**: does it change network, firewall, routing, DNS or hosts configuration?
- **Remote code execution**: does it download code from the internet and execute it?

Requests have a 30 second timeout.

### OpenAI Decisions

Select an OpenAI provider with explicit `api: decisions` to use
[OpenAI Decisions](https://developers.openai.com/api/docs/guides/decisions) instead of Jev.
See the [configuration example](configuration.md#openai-decisions). It defaults to `gpt-6-luna`
and accepts a configured model name for future supported models. It is reviewer-only and
uses the official OpenAI endpoint; custom endpoints are rejected.

One request sends the generated script, its language and its dependencies as data, with one
fixed predicate for each hazard listed above. The instructions tell the model to treat script
content as untrusted data. The reviewer does not execute code or fetch URLs from that input.
It does not add local files, environment dumps or runtime arguments to the payload.

All four named answers must be present exactly once and be predicates with finite numeric
probabilities in [0, 1]. Booleans, strings, duplicate/missing/unknown names and refusals
invalidate the entire model assessment. Validation uses raw JSON values to avoid SDK numeric
coercion. Categories at **>= 0.5** are flagged, using the unrounded probability. A safe model
answer never clears static findings or dependency warnings.

The client uses a 30-second transport timeout and zero retries, with no provider fallback or
truncation. This timeout is not a strict end-to-end deadline. Errors, input-limit rejection,
refusals and invalid responses mark the script risky with a concise diagnostic; raw provider
payloads and credentials are excluded from diagnostics. Explicit interactive approval still
permits continuation after reviewer failure. Noninteractive risky builds are refused.

There is no review cache or application billing cap. Rebuilding can make another request;
already-cached execution continues without review. The common 0.5 threshold is a policy choice,
not a claim that different model families have equivalent calibration or safety.

### Ollaya (local)

[Ollaya](https://ollaya.dev) runs the same kind of decision model on your machine, with no key and
no network use. Run `ollaya serve`, then:

```yaml
reviewer_provider: ollaya
providers:
  ollaya:
    model: "jevk5:4b"   # optional; this is the default
```

Defaults: model `jevk5:4b`, address `http://localhost:11435` (override with `base_url` or
`$OLLAYA_HOST`). A key is only needed if the server sets `OLLAYA_API_KEY`. If the server is
unreachable, the review fails closed and the message asks whether `ollaya serve` is running.

### QSIV (local GPU)

QSIV is a small decision model that runs on your own GPU through the optional `qsiv-runtime`
package. It asks the same four yes/no questions as Jev (privilege escalation, filesystem,
networking, remote code execution) and gets four probabilities back. A category is flagged when
its probability is at least 0.5, compared on the unrounded value (a reason reads
`QSIV review: Filesystem (p=0.93)`). A safe answer never clears a static finding or the
dependency warning. aiscript re-checks every answer: the wrong count, or a value that is not a
number between 0 and 1, rejects the whole answer.

Requirements: Linux x86_64 and an NVIDIA GPU with compute capability 8.9 or higher. Install with
`uv tool install "aiscript[qsiv]"` and run `uvx qsiv-runtime setup` once (or `uv tool install qsiv-runtime`, which puts the command
on your PATH); `uvx qsiv-runtime doctor` checks
the machine (see [configuration](configuration.md#qsiv-local-gpu-reviewer)).

Failure handling is fail-closed: if the package is not installed, the GPU or model is missing,
the service does not answer, the script is over the model's input limit (65,536 tokens over the
rendered request; it is never truncated and is rejected as `too_large` before inference), the GPU
runs out of memory (on 8 GB GPUs, states above about 49K tokens fail below the limit and report as a
service failure) or the answer is invalid, the result is risky with `Reviewer unavailable: <cause>`, plus the command to
run when one fixes it. Interactively you can still approve the script; non-interactively it is
refused.

One model stays resident machine-wide (the service exits after 300 s idle), so aiscript and other
tools using `qsiv-runtime` share it; a different model configuration is refused while another is
loaded. The runtime runs in a local virtualenv that aiscript does not sandbox: trust it as you
trust any tool you install. It is started without variables whose names contain `API_KEY`, `APIKEY`, `TOKEN`, `SECRET`,
`PASSWORD`, `PASSWD`, `CREDENTIAL`, `PRIVATE_KEY` or `ACCESS_KEY`, or have a whole segment `AUTH`
(`SSH_AUTH_SOCK`; `AUTHOR` stays), and never downloads anything while reviewing.

Very long scripts dilute the QSIV signal (remote-code probability
0.95 at about 300 tokens, 0.13 at about 47K), so the static scan still runs and a safe QSIV answer
never clears static findings.

### OpenAI-compatible reviewer

A provider of kind `openai` using `responses` or `chat` can also be the reviewer. It is asked for a strict JSON verdict
(`{"risky": ..., "reasons": [...]}`) using the same API settings as a generator.

## AI use and secrets

- **Secret scans**: your prompt is scanned for API keys before the generator sees it, and the
  generated code before any reviewer sees it. Both refuse the build with no override, naming the
  line but never the value. The scan covers configured keys and `sk-` style provider key patterns in
  raw, joined, reversed, ROT13, base64/hex/percent-decoded, folded Python string and shell-escape
  forms. Out-of-order fragments under 12 characters and computed transforms cannot be caught.
  `aiscript --check-secrets` runs the scan over existing builds.
- **AI-use confirmation**: a script that calls the model needs an interactive yes. When AI use is
  the only finding, aiscript shows a short note ("this script sends data to your AI provider"),
  naming the provider and the lines that send data, instead of a risk warning; any other finding
  keeps the full warning. Non-interactive builds are refused either way.
- **Credential access** (reading `*_API_KEY`/`*_TOKEN`, setting `OPENAI_BASE_URL` or `AISCRIPT_*`,
  opening the aiscript config, calling an LLM host directly) is reported and can be overridden
  interactively. Running `aiscript NAME`, `aiscript ./file` or `--rebuild` from a script is
  reported as remote code execution; only `--ask` is exempt.
- **Call cap**: the per-run limit uses a counter file the runner creates, so a script can tamper
  with it. It guards against bugs and loops, not malicious shell scripts. A script runs as you
  and could read `config.yaml` itself; aiscript is not a sandbox.
- Model output is untrusted. Rolling back: rebuild or remove AI scripts before downgrading
  (1.3.0 exits 2 on `--ask`).

## ACP agents

Built-in ACP selections (`codex-acp`, `claude-acp`, `gemini-acp`, `opencode-go-acp`, `glm-acp`) run
a local agent executable that you installed and signed in to.

- **Trusted local executable**: the agent runs with your own operating-system privileges,
  environment and its own configuration, hooks, network access and tools. aiscript only speaks the
  protocol to it; it does not install, update or sandbox it.
- **Your current directory**: the agent starts in the directory where you ran aiscript, not in an
  empty one.
- **Permission denial is not a sandbox**: aiscript refuses the agent's permission, file and terminal
  requests, but the agent can still act on its own and already completed actions persist.
- **Limits, not guarantees**: the deadline and size limits (`acp.*`) stop a request; they do not
  cap model tokens, charges or what the agent does internally. Instructions are sent as prompt text
  (no system role) and JSON output is validated locally, not by the provider.
- The agent's stderr is never shown or logged by aiscript. Requests may be billed by the agent's
  own provider.

## Fail closed

If the reviewer errors, times out, is unreachable or returns an unparsable answer, the script is
treated as risky with a "Reviewer unavailable" reason. Nothing is saved without your approval.

## Confirmation

For a risky script, aiscript prints the reasons and the numbered script to stderr, then asks
`Run this script? [y/N]`. Only `y` or `yes` approves; anything else, EOF or Ctrl-C declines, and
nothing is saved. If stdin is not a terminal, risky scripts are refused outright.

## Hardening notes

- The static scan joins `\`-continued (Bash) and backtick-continued (PowerShell) lines before
  matching, and also flags `eval`, decoded payloads piped to a shell, downloads piped to an
  interpreter, `xargs rm`, `find -exec rm`, interpreter one-liners that delete files or spawn
  commands, and commands whose name comes from a variable (`$cmd ...`).
- Everything shown at the confirmation prompt (reasons and the script) has control characters
  escaped (`\x1b`, `\x0d`, ...), so a script cannot hide code with ANSI sequences or carriage
  returns.
- Regexes cannot understand shell semantics, and the Python scan only sees literal values.
  Treat the static scan as a tripwire, not a proof.

## Privacy

- **Generation**: your command name, your plain-English description, and your OS name and version
  are sent to the `default_provider` (OpenAI by default). Do not put secrets in a description.
- **Generation** also sends your OS architecture, native shell, Python version and whether uv is
  installed.
- **Review**: with Jev (hosted), the generated script, its language and its dependency list are
  sent to TypeSafe AI.
  Use `reviewer_provider: ollaya` or `qsiv` (both local) or leave it unset to keep scripts on
  your machine.
- **QSIV review**: the script stays on your machine; it goes only to the local QSIV service over a
  private socket (directory mode 0700), and nothing is sent to any network.
- **OpenAI Decisions review** sends that same script, language and dependency list to
  `https://api.openai.com/v1/decisions`, using the selected reviewer's dedicated key. No retention
  guarantee is implied by this integration.
- **AI calls inside scripts**: a script that uses `aiscript.ask` / `aiscript --ask` sends its task,
  data description and input data to the `default_provider` on every run, so such cached scripts
  are no longer offline. Use a local provider (for example Ollama) to keep that data on your
  machine. Nothing else leaves the machine; there is no response cache or billing cap.
- Otherwise nothing is sent when you run an already-cached command.
- The API key is never given to a script: scripts call aiscript, and only that process reads the
  key. aiscript is not a sandbox, though: a script can still set `HTTPS_PROXY` / `SSL_CERT_FILE`
  (which the SDK honours) to intercept its own `--ask` call, so the reviewer flags scripts that
  set those variables (Credential access) and you should read what you approve.
- A background `aiscript --ask &` that outlives the script run fails closed with exit 9 (the
  call counter is gone), so it cannot keep spending after the run ends.
- API keys live in `config.yaml` (mode 600) or environment variables, and are never logged.
  A provider with a plain `http://` non-local `base_url` triggers a warning, since the key
  and script would travel unencrypted.

## Known limitations

- Cached scripts are not re-reviewed or integrity-checked on each run: anyone who can write to
  `~/.config/aiscript/functions/` can change what a command does.
- On Windows scripts run with `-ExecutionPolicy Bypass` (they are unsigned by design).
- Approved dependencies are not pinned by hash; a later `--rebuild` with changed dependencies
  installs whatever PyPI serves then.
