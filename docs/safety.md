# Safety review

Every generated script goes through a review **before it is saved**. Approved scripts are cached
and not reviewed again until rebuilt. The generator is also prompted to prefer non-destructive
actions (for example, move files to the trash instead of deleting them recursively).

This is a best-effort safety net, not a sandbox. Read what you approve.

## 1. Static scan (always on)

A regex scan of the code lines (comments are ignored; plain `echo`/`printf` lines are skipped),
using Bash patterns on Linux/macOS and PowerShell patterns on Windows. It reports at most one
reason per category per line. Categories:

| Category | Examples |
|---|---|
| Privilege escalation | `sudo`, `doas`, `pkexec`, `su`; `Start-Process -Verb RunAs`, `runas`, `Set-ExecutionPolicy` |
| Filesystem | recursive deletes, deletes of `/` or `~`, writes to system directories, recursive `chmod`/`chown`, disk/format tools, `dd of=`, `find -delete`, `crontab`, `systemctl enable/disable/stop/mask`; on Windows recursive `Remove-Item`, writes under `Windows`/`Program Files`, registry edits, service and scheduled-task changes |
| Networking | firewall tools (`iptables`, `ufw`, ...), `ip`/`ifconfig`/`nmcli`/`route` changes, edits to `/etc/hosts` or `resolv.conf`; on Windows `netsh`, `*-NetFirewall*`, `Set-DnsClientServerAddress`, hosts file edits |
| Remote code execution | `curl`/`wget` piped to a shell, a shell running a download, `eval $(curl ...)`; `Invoke-Expression`, `iex` |

## 2. Decision model (optional)

Set `reviewer_provider` in `config.yaml` to add a second opinion. Its findings are combined with
the static scan.

### Jev and Ollaya

Jev (hosted by [TypeSafe AI](https://docs.typesafe.ai); key from
<https://console.typesafe.ai/keys>) and Ollaya (local) are classifiers: aiscript sends the
script and shell and asks one yes/no question per category, and the model answers with a
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
- Regexes cannot understand shell semantics. Treat the static scan as a tripwire, not a proof.

## Privacy

- **Generation**: your command name, your plain-English description, and your OS name and version
  are sent to the `default_provider` (OpenAI by default). Do not put secrets in a description.
- **Review**: with Jev (hosted), the generated script and shell name are sent to TypeSafe AI.
  Use `reviewer_provider: ollaya` (local) or leave it unset to keep scripts on your machine.
- Nothing is sent when you run an already-cached command.
- API keys live in `config.yaml` (mode 600) or environment variables, and are never logged.
  A provider with a plain `http://` non-local `base_url` triggers a warning, since the key
  and script would travel unencrypted.

## Known limitations

- Cached scripts are not re-reviewed or integrity-checked on each run: anyone who can write to
  `~/.config/aiscript/functions/` can change what a command does.
- On Windows scripts run with `-ExecutionPolicy Bypass` (they are unsigned by design).
