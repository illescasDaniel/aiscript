# Executable prompt scripts

## Metadata

- **Feature:** Execute a natural-language prompt file using aiscript directly or through a Unix shebang.
- **System design:** [DESIGN.md](../../design/shebang-scripts/DESIGN.md), approved 2026-11-09 in chat. Both Mermaid diagrams validated.
- **Design decisions approved:** 2026-11-09 in chat.
- **Spec approved:** 2026-11-09 in chat.

## Design decisions

### Success criteria

- On Unix-like systems `./biggest folder` runs a file beginning `#!/usr/bin/env aiscript`. `aiscript ./biggest folder` also runs a prompt file without a shebang.
- Generate and review on first use, then execute with unchanged arguments and inherited streams. Reuse a matching reviewed build without regeneration or review.
- Rebuild when prompt content changes, even if its timestamp does not. Changes only to the shebang do not change the prompt.

### Failure handling

- Missing, unreadable, non-regular, invalid UTF-8 or empty prompt files fail with a diagnostic on stderr and nonzero status.
- Generation, dependency setup, review, rejected approval or cache failure must not run a stale or partial build. Preserve the prior approved cache on failed rebuild.
- Report process launch failures and return nonzero. Propagate the status of a launched program. Risky builds requiring approval fail when stdin is non-interactive.

### Performance & resource budget

- A cache hit makes no model call, loads no generation or review configuration and performs no dependency installation.
- First builds retain existing provider and dependency behavior. No new timeout or prompt-size limit is imposed.
- File cache entries persist until manually removed. Concurrent invocations must never run a partial artifact or one that does not match their prompt snapshot.

### Trust boundary

- Paths, prompt contents and arguments are untrusted. Treat paths as filesystem paths, derive safe cache keys, and do not interpolate arguments into shell command strings.
- Cache file builds separately from named commands. The reviewed artifact must match the exact prompt snapshot used for generation.
- Reuse existing static and configured model review and interactive approval rules. Review does not sandbox generated programs.

### Compatibility & rollout

- A first argument containing a path separator selects file mode, including missing paths and names such as `./-file`. Bare arguments retain existing named-command behavior even if a matching file exists. Existing options and caches remain unchanged.
- Canonical resolved paths identify cache entries: symlink aliases share an entry; moving a file creates a new one. Cache content matching excludes the shebang.
- Document `command -v aiscript`, installer-specific PATH guidance after verification, and absolute shebang paths. Do not modify shell profiles at install time or rely on post-install messages.
- Unix shebang execution requires executable permission and a discoverable interpreter. Explicit file invocation is also supported on Windows; Unix-style shebang execution is not promised there.
- No migration or feature flag is required. Rolling back leaves the separate file cache unused by older versions.

## Triggers & routing

- **Entry:** `aiscript PATH [args...]`, or execution of an executable prompt file with an aiscript shebang.
- **Exit:** A matching reviewed generated program runs with inherited stdin, stdout and stderr, and its exit status is returned. Errors are reported on stderr with a nonzero status.
- Bare script names passed to aiscript are named commands, so shebang use is guaranteed for explicit paths such as `./biggest` or absolute paths.

## Interfaces & contracts

- A UTF-8 file supplies the prompt. If the first line begins with `#!`, exclude that line. Reject a whitespace-only remaining prompt.
- Pass each argument following the file path unchanged to the generated program, including flags, whitespace, and empty arguments.
- For a cache hit, compare the exact prompt content to the reviewed build's content identity. Publish a complete build and corresponding identity together; do not run a stale build on any failed rebuild.
- If the file changes while building, never run a build that mismatches the prompt snapshot requested by that invocation. Synchronize concurrent publication and execution so partial or mismatched artifacts cannot run.

## Data & migration

- Store generated file builds and their content identities in a separate cache namespace, using safe keys derived from canonical source paths. Existing named command prompts and builds are untouched.
- No existing data is migrated. File cache entries may be manually removed and are rebuilt on next use.

## Acceptance criteria

### Scenario: Execute a shebang prompt file

**Given** an executable UTF-8 prompt file with an aiscript shebang and no cached build **When** it is run as `./biggest` with arguments **Then** aiscript reads the prompt without the shebang, generates and reviews a build, and runs it with the same arguments.

### Scenario: Invoke a prompt file explicitly

**Given** a UTF-8 prompt file without a shebang **When** `aiscript ./file` is invoked **Then** the whole file supplies the prompt and the resulting reviewed program runs.

### Scenario: Reuse an unchanged build

**Given** a reviewed build matching the file prompt **When** the file is run again **Then** the build is reused without a model call, review configuration load or dependency installation.

### Scenario: Rebuild changed content

**Given** a reviewed build **When** the prompt content changes without a timestamp change **Then** the new content is generated and reviewed before execution.

### Scenario: Change only the shebang

**Given** a reviewed build **When** only the shebang changes **Then** the matching build is reused.

### Scenario: Reject invalid prompt file (F1)

**Given** an explicit path to a missing, inaccessible, non-regular, invalid UTF-8 or whitespace-only file **When** it is invoked **Then** aiscript reports an error and exits nonzero without generating or running a program.

### Scenario: Generation or dependency setup fails (F2)

**Given** a previously approved build and a changed prompt **When** generation or dependency setup fails **Then** aiscript reports failure, preserves the previous cache and executes nothing.

### Scenario: Review or approval fails (F2)

**Given** a generated program requiring review **When** review fails or approval is declined **Then** no new build is published or executed.

### Scenario: Risky build with non-interactive stdin (F2)

**Given** redirected stdin and a generated program requiring interactive approval **When** the build is reviewed **Then** aiscript refuses the build without consuming the program's stdin.

### Scenario: Cache cannot be used (F3)

**Given** a cache that cannot be read, written or safely published **When** the file is invoked **Then** aiscript reports an error and executes neither a stale nor a partial build.

### Scenario: Program cannot launch (F4)

**Given** a reviewed build whose interpreter cannot be launched **When** aiscript attempts to execute it **Then** it reports the failure on stderr and exits nonzero.

### Scenario: Preserve streams and status

**Given** a generated program reading stdin, writing stdout and stderr and returning a nonzero status **When** it runs **Then** the streams are inherited and its exit status is returned.

### Scenario: Preserve named commands

**Given** an existing named command and a same-named file in the current directory **When** the bare name is invoked **Then** the existing named-command workflow is used.

### Scenario: Preserve path and argument characters

**Given** an explicit path with spaces or a leading-dash filename and arguments with spaces, empty strings or shell metacharacters **When** it is invoked **Then** the exact file is read and the arguments reach the program unchanged, without shell interpretation.

### Scenario: Resolve aliases and moves

**Given** symlink aliases to a prompt file and a separately moved file **When** they are invoked **Then** aliases resolving to the same path share a cache and the moved file has a distinct cache identity.

### Scenario: Concurrent builds and source edits

**Given** concurrent invocations and a prompt that may change during a build **When** builds are generated or published **Then** no invocation executes a partial artifact or a build mismatched to its requested prompt snapshot.

### Scenario: PATH setup guidance

**Given** a user installing aiscript with a documented installer **When** they consult the setup instructions **Then** they can check command availability, find guidance for exposing the installer binary directory on PATH, and see the absolute-path alternative.

### Scenario: Installation leaves profiles alone

**Given** a supported package installation **When** it completes **Then** aiscript does not modify the user's shell profiles.

## Out of scope

- Expanding `$HOME` or `~` in a shebang, and Unix-style shebang execution on Windows.
- Automatic shell-profile edits, guaranteed post-install output, cache eviction, or named-command management of file builds.
- Sandboxing generated code or changing existing named-command behavior.
