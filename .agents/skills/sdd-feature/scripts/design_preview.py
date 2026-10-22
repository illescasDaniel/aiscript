#!/usr/bin/env python3
"""Render a DESIGN.md (Markdown with Mermaid diagrams) as a review-only HTML page (standard library only).

Writes ``preview.html`` next to the design. The page embeds the Markdown and renders it in the browser with pinned
marked and Mermaid builds from jsDelivr, so viewing it needs network access; diagrams that fail to parse show the
Mermaid error in place. DESIGN.md stays the source of truth: regenerate the page after every edit.

``--check`` first validates every ```mermaid block headlessly with the pinned ``@mermaid-js/mermaid-cli`` (``mmdc``,
via ``npx``; needs Node, and the first run downloads packages and a Chromium build), printing ``PASS`` / ``FAIL`` per
diagram with its heading, line number and the parser error. It still writes the preview afterwards. Exit codes: 0 all
diagrams valid, 1 a diagram is invalid, 2 the check could not run (no ``npx``, network or Chromium problem): nothing
was validated in that case.

	python3 design_preview.py design/<feature>/DESIGN.md [--check] [-o <out.html>]
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MARKED_URL = "https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js"
MERMAID_URL = "https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.min.js"
# mermaid-cli depends on "mermaid": "^11.0.2", so the Mermaid build is pinned alongside it to match the preview.
CLI_PACKAGES = ("@mermaid-js/mermaid-cli@11.4.2", "mermaid@11.4.1")
CHECK_TIMEOUT_SECONDS = 600
MERMAID_BLOCK = re.compile(r"^```mermaid[ \t]*\n(.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
	:root {
		--bg: #ffffff; --fg: #1f2328; --muted: #59636e; --line: #d1d9e0; --code: #f6f8fa;
		--note-bg: #fff8c5; --note-line: #d4a72c; --err-bg: #ffebe9; --err-line: #cf222e;
	}
	@media (prefers-color-scheme: dark) {
		:root {
			--bg: #0d1117; --fg: #e6edf3; --muted: #9198a1; --line: #3d444d; --code: #151b23;
			--note-bg: #2e2a1a; --note-line: #9e6a03; --err-bg: #2d1416; --err-line: #f85149;
		}
	}
	body { margin: 0; background: var(--bg); color: var(--fg); font: 16px/1.55 system-ui, sans-serif; }
	main { max-width: 960px; margin: 0 auto; padding: 24px 16px 64px; }
	.note { border: 1px solid var(--note-line); background: var(--note-bg); border-radius: 6px; padding: 8px 12px; }
	.legend span { display: inline-block; margin-right: 12px; }
	.legend i { display: inline-block; width: 12px; height: 12px; border: 1px solid; border-radius: 2px;
		vertical-align: -1px; margin-right: 4px; }
	h1, h2 { border-bottom: 1px solid var(--line); padding-bottom: 4px; }
	a { color: inherit; }
	code { background: var(--code); border-radius: 4px; padding: 1px 4px; font-size: 0.9em; }
	pre { background: var(--code); border-radius: 6px; padding: 12px; overflow-x: auto; }
	pre code { background: none; padding: 0; }
	pre.mermaid { background: none; text-align: center; }
	pre.mermaid-error { background: var(--err-bg); border: 1px solid var(--err-line); white-space: pre-wrap; }
	table { border-collapse: collapse; display: block; overflow-x: auto; }
	th, td { border: 1px solid var(--line); padding: 6px 10px; text-align: left; vertical-align: top; }
</style>
</head>
<body>
<main>
	<p class="note"><strong>Review only.</strong> Generated from <code>__SOURCE_NAME__</code>, which is the source of
	truth. Components:
	<span class="legend"><span><i style="background:#dcfce7;border-color:#15803d"></i>added</span><span><i
	style="background:#fef9c3;border-color:#a16207"></i>changed</span><span><i
	style="background:#fee2e2;border-color:#b91c1c;border-style:dashed"></i>removed</span></span></p>
	<article id="doc"></article>
</main>
<script>const SOURCE = __SOURCE_JSON__;</script>
<script src="__MARKED_URL__"></script>
<script src="__MERMAID_URL__"></script>
<script>
(async function () {
	const doc = document.getElementById("doc");
	if (typeof marked === "undefined" || typeof mermaid === "undefined") {
		doc.innerHTML = '<p class="note">Could not load the renderers (offline?). Showing the raw Markdown.</p>';
		const pre = document.createElement("pre");
		pre.textContent = SOURCE;
		doc.appendChild(pre);
		return;
	}
	const renderer = new marked.Renderer();
	const plainCode = renderer.code.bind(renderer);
	renderer.code = function (code, lang) {
		const token = typeof code === "object" ? code : { text: code, lang: lang };
		if ((token.lang || "").trim() !== "mermaid") return plainCode.apply(null, arguments);
		const pre = document.createElement("pre");
		pre.className = "mermaid";
		pre.textContent = token.text;
		return pre.outerHTML;
	};
	doc.innerHTML = marked.parse(SOURCE, { renderer: renderer });

	const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
	mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: dark ? "dark" : "default" });
	const valid = [];
	for (const pre of doc.querySelectorAll("pre.mermaid")) {
		try {
			await mermaid.parse(pre.textContent);
			valid.push(pre);
		} catch (error) {
			pre.className = "mermaid-error";
			pre.textContent = "Mermaid syntax error:\\n" + (error && error.message ? error.message : error)
				+ "\\n\\n" + pre.textContent;
		}
	}
	if (valid.length) await mermaid.run({ nodes: valid });
	document.body.dataset.rendered = String(valid.length);
})();
</script>
</body>
</html>
"""


def render(source: str, source_name: str) -> str:
	"""The preview page for one DESIGN.md."""
	heading = re.search(r"^#\s+(.+?)\s*$", source, re.MULTILINE)
	title = heading.group(1) if heading else source_name
	# Escaping every "<" keeps "</script>" in the Markdown from closing the script tag.
	source_json = json.dumps(source).replace("<", "\\u003c")
	return (
		PAGE.replace("__TITLE__", html.escape(title))
		.replace("__SOURCE_NAME__", html.escape(source_name))
		.replace("__MARKED_URL__", MARKED_URL)
		.replace("__MERMAID_URL__", MERMAID_URL)
		.replace("__SOURCE_JSON__", source_json)
	)


def mermaid_blocks(source: str) -> list[tuple[str, int, str]]:
	"""Each Mermaid block as (nearest preceding ``##`` heading, 1-based line of the opening fence, code)."""
	blocks = []
	for match in MERMAID_BLOCK.finditer(source):
		before = source[: match.start()]
		headings = re.findall(r"^##\s+(.+?)\s*$", before, re.MULTILINE)
		blocks.append((headings[-1] if headings else "(top)", before.count("\n") + 1, match.group(1)))
	return blocks


def _error_message(output: str) -> str:
	"""The parser error from mmdc's output: the lines from ``Error:`` up to the stack trace."""
	lines = [line.rstrip() for line in output.splitlines()]
	start = next((i for i, line in enumerate(lines) if line.startswith("Error:")), None)
	if start is None:
		return " | ".join(line for line in lines if line.strip())[:500] or "unknown error"
	message = []
	for line in lines[start:]:
		if re.match(r"\s+at .+\(.+\)|^Parser3?\.", line) or line.startswith(("Parse error", "Parser")) and message:
			break
		if line.strip():
			message.append(line.strip())
	return "\n        ".join(message)[:600]


def check_diagrams(source: str, design: Path) -> int:
	"""Validate every Mermaid block with mmdc; 0 all valid, 1 some invalid, 2 could not check."""
	blocks = mermaid_blocks(source)
	if not blocks:
		print(f"PASS  {design}: no mermaid blocks to check")
		return 0
	npx = shutil.which("npx")
	if npx is None:
		print("CANNOT CHECK  npx not found on PATH (install Node.js); no diagram was validated")
		return 2
	failures = 0
	with tempfile.TemporaryDirectory() as tmp:
		config = Path(tmp) / "puppeteer.json"
		config.write_text(json.dumps({"args": ["--no-sandbox"]}), encoding="utf-8")
		for index, (heading, line, code) in enumerate(blocks, 1):
			source_file, svg = Path(tmp) / f"d{index}.mmd", Path(tmp) / f"d{index}.svg"
			source_file.write_text(code, encoding="utf-8")
			command = [npx, "-y", *(arg for package in CLI_PACKAGES for arg in ("-p", package)), "mmdc",
				"-p", str(config), "-i", str(source_file), "-o", str(svg), "-q"]
			try:
				result = subprocess.run(command, capture_output=True, text=True, timeout=CHECK_TIMEOUT_SECONDS, check=False)
			except (OSError, subprocess.TimeoutExpired) as error:
				print(f"CANNOT CHECK  mmdc did not run ({type(error).__name__}: {error}); no diagram was fully validated")
				return 2
			output = result.stdout + result.stderr
			label = f"{design}:{line}: diagram {index} under '## {heading}'"
			if result.returncode == 0 and svg.is_file():
				print(f"PASS  {label}")
			elif re.search(r"Parse error|Lexical error|Error: .*(Syntax|syntax)|UnknownDiagramError|No diagram type detected", output):
				failures += 1
				print(f"FAIL  {label}\n        {_error_message(output)}")
			else:
				detail = " | ".join(part.strip() for part in output.splitlines() if part.strip())[:300]
				print(f"CANNOT CHECK  mmdc failed to run (exit {result.returncode}): {detail}; no diagram was fully validated")
				return 2
	print(f"\n{'FAILED' if failures else 'OK'}: {failures} invalid diagram(s) of {len(blocks)}")
	return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
	parser = argparse.ArgumentParser(description="Render a DESIGN.md with Mermaid diagrams as a review-only HTML page")
	parser.add_argument("design", type=Path, help="DESIGN.md to render")
	parser.add_argument("-o", "--output", type=Path, help="output file (default: preview.html next to the design)")
	parser.add_argument("--check", action="store_true", help="validate the Mermaid blocks with mmdc first (needs npx)")
	args = parser.parse_args(argv)

	if not args.design.is_file():
		print(f"{args.design}: file not found", file=sys.stderr)
		return 1
	source = args.design.read_text(encoding="utf-8")
	status = check_diagrams(source, args.design) if args.check else 0
	output = args.output or args.design.with_name("preview.html")
	output.write_text(render(source, args.design.name), encoding="utf-8")
	print(output)
	return status


if __name__ == "__main__":
	sys.exit(main())
