#!/usr/bin/env python3
"""Structural checks for an SDD SPEC.md (standard library only, any project language).

Checks what an agent or reviewer would otherwise eyeball: Metadata exists and its
wireframe and system design links resolve, the design decisions are answered (a bare
``N/A`` needs a reason), every ``### Scenario:`` has Given/When/Then, every failure
branch ``F<n>`` in a linked DESIGN.md's Mermaid diagrams has a scenario, and Out of
scope exists. Whether the code satisfies the spec stays a judgement call for the grader.

Exit code 1 when any hard ``FAIL`` is found; ``WARN`` lines never change it.

	python3 spec_check.py specs/<feature>/SPEC.md [more specs…] [--root <repo>]
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

DESIGN_DECISION_KEYS = ("success criteria", "failure handling", "performance", "trust boundary")
# Added after the first four: missing is only a warning, so specs written before it keep passing.
OPTIONAL_DECISION_KEYS = ("compatibility",)
FAILURE_ID = re.compile(r"\bF\d+\b")
MERMAID_BLOCK = re.compile(r"^```mermaid\s*$(.*?)^```", re.MULTILINE | re.DOTALL)


@dataclass
class Report:
	"""Accumulates check results; ``fails`` decide the exit code."""

	lines: list[str] = field(default_factory=list)
	fails: int = 0

	def ok(self, message: str) -> None:
		self.lines.append(f"PASS  {message}")

	def fail(self, message: str) -> None:
		self.fails += 1
		self.lines.append(f"FAIL  {message}")

	def warn(self, message: str) -> None:
		self.lines.append(f"WARN  {message}")


def _section(text: str, heading: str) -> str | None:
	match = re.search(
		rf"^##\s+{re.escape(heading)}\b.*?$(.*?)(?=^##\s|\Z)", text, re.MULTILINE | re.DOTALL | re.IGNORECASE
	)
	return match.group(1) if match else None


def _decision_start(lines: list[str], key: str) -> int | None:
	"""Line where a decision starts: its heading if it has one, else its first mention."""
	mentions = [i for i, line in enumerate(lines) if key in line]
	return next((i for i in mentions if lines[i].lstrip().startswith("#")), mentions[0] if mentions else None)


def _design_decision_problems(section: str) -> tuple[list[str], list[str]]:
	"""Problems with the decisions, and optional decisions that are missing.

	Each decision present must carry real content; a bare ``N/A`` needs a reason.
	"""
	lines = section.lower().splitlines()
	keys = DESIGN_DECISION_KEYS + OPTIONAL_DECISION_KEYS
	starts = {key: _decision_start(lines, key) for key in keys}
	ordered = sorted(i for i in starts.values() if i is not None)
	problems, missing_optional = [], []
	for key, start in starts.items():
		if start is None:
			(missing_optional if key in OPTIONAL_DECISION_KEYS else problems).append(f"'{key}' missing")
			continue
		end = next((i for i in ordered if i > start), len(lines))
		chunk = " ".join(lines[start:end])
		content = re.sub(r"[^a-z0-9]+", "", chunk.split(key, 1)[1])
		if len(content) < 15 or ("n/a" in chunk and len(content.replace("na", "", 1)) < 12):
			problems.append(f"'{key}' empty or bare N/A")
	return problems, missing_optional


def _linked(root: Path, metadata: str, pattern: str) -> tuple[list[str], list[str]]:
	"""Repo-relative paths matching ``pattern`` in Metadata, and those that do not exist."""
	paths = list(dict.fromkeys(re.findall(pattern, metadata)))
	return paths, [p for p in paths if not (root / p).is_file()]


def check_failure_paths(root: Path, rel: Path, designs: list[str], scenario_blocks: list[str], report: Report) -> None:
	"""Every ``F<n>`` in a design's Mermaid diagrams needs a scenario that names it."""
	# The last scenario block runs to the end of the file: stop it at the next ## section.
	scenarios = [re.split(r"^##\s", block, maxsplit=1, flags=re.MULTILINE)[0] for block in scenario_blocks]
	covered = {fid for block in scenarios for fid in FAILURE_ID.findall(block)}
	for design in designs:
		diagrams = "\n".join(MERMAID_BLOCK.findall((root / design).read_text(encoding="utf-8")))
		ids = sorted(set(FAILURE_ID.findall(diagrams)), key=lambda fid: int(fid[1:]))
		if not ids:
			if re.search(r"^\s*(alt|break)\b", diagrams, re.MULTILINE):
				report.warn(f"{design}: diagram branches have no F1, F2, … labels, so failure paths cannot be traced")
			continue
		missing = [fid for fid in ids if fid not in covered]
		if missing:
			report.fail(f"{rel}: failure path(s) {', '.join(missing)} in {design} have no scenario")
		else:
			report.ok(f"{rel}: failure path(s) {', '.join(ids)} in {design} each have a scenario")


def check_spec(root: Path, spec: Path, report: Report) -> None:
	"""Structure of one SPEC.md."""
	text = spec.read_text(encoding="utf-8")
	rel = spec.resolve().relative_to(root) if spec.resolve().is_relative_to(root) else spec

	designs: list[str] = []
	metadata = _section(text, "Metadata")
	if metadata is None:
		report.fail(f"{rel}: missing ## Metadata")
	else:
		wireframes, missing_wireframes = _linked(root, metadata, r"wireframes/[\w./#-]+?\.html")
		designs, missing_designs = _linked(root, metadata, r"design/[\w./-]+?\.md")
		if not wireframes and not designs:
			report.warn(f"{rel}: Metadata links no wireframes/*.html or design/*/DESIGN.md")
		for kind, linked, missing in (("wireframe", wireframes, missing_wireframes), ("design", designs, missing_designs)):
			if missing:
				report.fail(f"{rel}: linked {kind}(s) not found: {', '.join(missing)}")
			elif linked:
				report.ok(f"{rel}: linked {kind}(s) exist")
		designs = [d for d in designs if d not in missing_designs]

	decisions = _section(text, "Design decisions")
	if decisions is None:
		report.fail(
			f"{rel}: missing ## Design decisions (success criteria, failure handling, performance, trust boundary,"
			" compatibility & rollout)"
		)
	else:
		problems, missing_optional = _design_decision_problems(decisions)
		if problems:
			report.fail(f"{rel}: Design decisions incomplete: {'; '.join(problems)}")
		else:
			report.ok(f"{rel}: required design decisions answered")
		if missing_optional:
			report.warn(f"{rel}: Design decisions: {'; '.join(missing_optional)} (add it, or `N/A — <reason>`)")

	if _section(text, "Out of scope") is None:
		report.warn(f"{rel}: missing ## Out of scope")

	scenarios = re.findall(r"^###\s+Scenario:\s*(.+?)\s*$", text, re.MULTILINE)
	if not scenarios:
		report.fail(f"{rel}: no '### Scenario:' headings found")
		return
	blocks = re.split(r"^###\s+Scenario:", text, flags=re.MULTILINE)[1:]
	incomplete = []
	for block in blocks:
		title = block.splitlines()[0].strip()
		if not all(re.search(rf"\*\*{kw}\*\*", block) for kw in ("Given", "When", "Then")):
			incomplete.append(title)
	if incomplete:
		report.fail(f"{rel}: {len(incomplete)} scenario(s) lack **Given** / **When** / **Then**")
		report.lines.extend(f"        {t}" for t in incomplete)
	else:
		report.ok(f"{rel}: {len(scenarios)} scenario(s), each with Given/When/Then")
	check_failure_paths(root, rel, designs, blocks, report)


def _default_root() -> Path:
	try:
		result = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False)
	except OSError:
		return Path.cwd()
	return Path(result.stdout.strip()) if result.returncode == 0 else Path.cwd()


def main(argv: list[str] | None = None) -> int:
	parser = argparse.ArgumentParser(description="Structural checks for SDD SPEC.md files")
	parser.add_argument("specs", nargs="+", type=Path, help="SPEC.md file(s) to check")
	parser.add_argument("--root", type=Path, help="repo root for wireframe and design links (default: git toplevel or cwd)")
	args = parser.parse_args(argv)

	root = (args.root or _default_root()).resolve()
	report = Report()
	for spec in args.specs:
		if not spec.is_file():
			report.fail(f"{spec}: file not found")
			continue
		check_spec(root, spec, report)
	print("\n".join(report.lines))
	print(f"\n{'FAILED' if report.fails else 'OK'}: {report.fails} hard failure(s)")
	return 1 if report.fails else 0


if __name__ == "__main__":
	sys.exit(main())
