# Jupyter Notebook Format

## Overview

This skill describes the format of Jupyter Notebook (.ipynb) files, which combine Markdown documentation with executable Python (or other language) code cells.

All terminology follows **American English**.

## Structure

A Jupyter notebook consists of:

1. **Metadata** – Optional top-level keys (e.g., `nbformat`, `kernelspec`).
2. **Cells** – An ordered list of cell objects. Each cell has:
   - `cell_type`: `"code"`, `"markdown"`, `"question"`, etc.
   - `source`: An **array of strings**. Each string is a line of code/Markdown. Newlines are literal line breaks within the array, not escaped `\n`.
   - `metadata`: Key-value pairs attached to the cell.
   - `outputs`: Results of executed code (if applicable).
3. **Catalog** – Top-level `catalog` array describing the notebook's metadata (name, version, etc.).

## Code Cell Source Array

The critical detail for correct rendering is the `source` field:

```json
{
  "cell_type": "code",
  "source": [
    "import pandas as pd",
    "df = pd.read_csv('data.csv')",
    "print(df.head())"
  ],
  ...
}
```

- **`source` is an array**, not a single string. Each line is a separate element.
- **Newlines are actual line breaks** within the array elements (standard JSON array syntax).
- Literal `\n` escape sequences **are not** used in the source array; they appear only when the notebook is rendered in a viewer that interprets them as escape sequences.
- For Markdown cells, `source` contains strings of Markdown text (e.g., `# Title` or `**bold**`).

## Common Pitfalls

| Issue | Cause | Fix |
|-------|-------|------|
| Newlines showing as `\n` in rendered notebook | Using double backslashes in the source array | Remove the backslashes; write actual newlines in the array elements |
| Syntax errors when running cells | Escaped newlines in source | Ensure each line is a separate array element without `\n` |
| Missing code execution | Cell marked as `code` but not executed | Run the notebook with `%run` magic or ensure the kernel executes cells sequentially |

## Example: Valid Python Code Cell

```json
{
  "cell_type": "code",
  "execution_count": null,
  "source": [
    "import pandas as pd",
    "df = pd.read_csv('https://raw.githubusercontent.com/example/data.csv')",
    "print(df.shape)"
  ],
  "metadata": {},
  "outputs": []
}
```

## Example: Valid Markdown Cell

```json
{
  "cell_type": "markdown",
  "source": [
    "# Color–Magnitude Diagram",
    ""
  ],
  "metadata": {},
  "outputs": []
}
```

## Matplotlib Magics

Always use `%matplotlib widget` (not `%matplotlib inline`) in notebooks that produce plots. The widget backend enables interactive exploration (zoom, pan, hover) directly in the notebook, whereas inline renders a static image.

Place the magic at the top of the first code cell, after imports:

```json
{
  "cell_type": "code",
  "source": [
    "import pandas as pd",
    "import matplotlib.pyplot as plt",
    "%matplotlib widget",
    ""
  ],
  ...
}
```

Other useful magics:
- `%%time` — time a cell's execution
- `%time expr` — time a single expression
- `%load_ext autoreload` — auto-reload modules between cells

## Spelling: American English

All text in the notebook (Markdown cells, plot labels, comments) should use American English spelling. For this notebook, always write **Color** (not *Colour*), **magnitude** (not *magnitude* with British variants), and use American conventions for words like **catalog** (not *catalogue*), **behavior**, **center**, etc. The plot title and axis labels must read "Color–Magnitude Diagram" and "B–V color index".

## Notes for Developers

- The notebook format is JSON (or JSON Lines when streamed).
- The `source` array must be syntactically valid JSON; each element is a string.
- For multi-line strings in Python (e.g., docstrings), use triple-quoted strings within the cell body—this does **not** require escaping newlines in the source array.
- When sharing notebooks externally, ensure the `source` arrays preserve line breaks correctly.
- Use `%matplotlib widget` for interactive plots; prefer it over `%matplotlib inline`.