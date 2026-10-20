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

### OpenAI-compatible reviewer

A provider of kind `openai` can also be the reviewer. It is asked for a strict JSON verdict
(`{"risky": ..., "reasons": [...]}`) using the same API settings as a generator.

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
  Use `reviewer_provider: ollaya` (local) or leave it unset to keep scripts on your machine.
- Nothing is sent when you run an already-cached command.
- API keys live in `config.yaml` (mode 600) or environment variables, and are never logged.
  A provider with a plain `http://` non-local `base_url` triggers a warning, since the key
  and script would travel unencrypted.

## Known limitations

- Cached scripts are not re-reviewed or integrity-checked on each run: anyone who can write to
  `~/.config/aiscript/functions/` can change what a command does.
- On Windows scripts run with `-ExecutionPolicy Bypass` (they are unsigned by design).
- Approved dependencies are not pinned by hash; a later `--rebuild` with changed dependencies
  installs whatever PyPI serves then.
