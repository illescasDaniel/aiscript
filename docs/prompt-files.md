# Executable prompt files

On Linux and macOS, save a plain-English description as `biggest` in a folder such as `~/Documents`:

```text
#!/usr/bin/env aiscript

List the 10 largest immediate subfolders of the directory given as the first argument. Show their sizes in human-readable form, largest first. Do not modify any files.
```

In that folder, make it executable and run it with the directory you want to inspect:

```sh
chmod +x biggest
./biggest ~/Downloads
```

On the first run, aiscript generates and reviews a program from the description. If it asks for
approval, inspect the code before accepting. Later runs reuse the cached program; editing the
description triggers a rebuild and review.

`/usr/bin/env` finds `aiscript` on `PATH`. Alternatively, use its absolute path in the shebang,
for example `#!/home/alex/.local/bin/aiscript`. The operating system does not expand `$HOME` or
`~` in a shebang.

You can also run a prompt file directly with `aiscript ./biggest ~/Downloads`; a shebang is
optional in this form. On Windows, use direct invocation with an explicit path, for example
`aiscript .\biggest Downloads`; Unix shebang execution is not supported there. The path must
include a path separator: a bare name such as `biggest` selects the existing named-command
workflow, even when a file with that name exists. Quote paths or arguments containing spaces.
Arguments after the path, including flags, are passed through unchanged, as are the program's
standard input, output and exit status.

The first run generates and reviews a script using the same safety checks as named commands.
Risky builds require approval and are refused when standard input is non-interactive. Later
runs reuse a matching reviewed build without calling a model; changing the prompt rebuilds and
reviews it. A changed shebang alone does not trigger a rebuild. If rebuilding fails or is
rejected, aiscript keeps the old build but does not execute it for the changed prompt.
File builds are stored separately from named commands under `~/.config/aiscript/file-cache/`
(or `$XDG_CONFIG_HOME/aiscript/file-cache/`, or `$AISCRIPT_HOME/file-cache/`). Paths resolving
to the same file share a cache; moving the file creates a new entry. Historical versions are
retained. To reclaim their space, remove the file-cache directory only when no prompt-file
invocation is using it; the next run will rebuild and review its script. Named-command
management options such as `--remove` do not manage this cache.
