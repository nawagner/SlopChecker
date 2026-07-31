# Lens prompt packs

A **lens** is one LLM pass over a submission, defined entirely in a
markdown file in this directory. Prompts are data, not code: teammates
add or edit lenses without touching Python, and every lens gets format
validation from the shared tests for free.

The Python here (`loader.py`) only parses markdown into a `Lens` object.
Prompt assembly, the LLM client, retries, and per-document caching are
the pipeline engine's job (#37) — nothing in this directory calls a
model.

## File format

One lens per file, `<lens-id>.md`:

```markdown
---
id: my-lens          # must match the filename stem
issue: 42            # tracking issue number
version: 0.1
output: json
---

# Human-readable lens title

## Purpose

One paragraph: what this lens extracts/judges and who consumes it.

## System prompt

The full system prompt sent to the model. Hard constraints go here,
numbered.

## Output format

The JSON shape the model must emit, in a ```json fence, plus how the
pipeline maps it onto the shared `Finding` model (#3).

## Example

### Input

One fenced block: a fabricated document excerpt, with `[[page N]]`
markers.

### Output

One fenced block: the exact JSON the model should produce for that
input.
```

Frontmatter is flat `key: value` lines only. `System prompt`,
`Output format`, and `Example` (with Input/Output fences) are required —
the loader refuses files without them. Extra sections are fine and are
preserved.

## Rules every lens must honor

These come from the repo-wide design decisions in `CLAUDE.md`:

- **Quote-anchored.** Any `quote` the model emits must be a verbatim,
  contiguous substring of the input. `tests/test_lenses.py` checks this
  mechanically for every lens's example — if your few-shot paraphrases,
  the suite fails.
- **No free text in the evidence layer.** Model output is structured
  JSON; check results downstream are strictly `bool | float`. Reader
  prose belongs to the renderer.
- **Evidence, not verdicts.** A lens extracts or measures; it does not
  recommend rejection.
- **Fabricated examples only.** Few-shot inputs are invented documents —
  never real applicant material.

## Adding a lens

1. Copy the skeleton above into `<lens-id>.md`.
2. Write the few-shot with a fabricated input; make sure every quote in
   the Output is copy-pasted from the Input.
3. Run `pytest tests/test_lenses.py` — the generic tests pick up the new
   file automatically.
4. Open an issue comment describing the lens's output contract if it
   introduces new check names (see #3 before extending the `Finding`
   shape).

## Using a lens

```python
from slopchecker.lenses import list_lenses, load_lens

lens = load_lens("claims")
lens.meta  # frontmatter dict
lens.system_prompt  # section text
lens.output_format
lens.example_input  # fenced block contents
lens.example_output
```
