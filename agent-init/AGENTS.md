* favor ripgrep (rg) fd and eza over grep, find, and ls  
* keep original spacing/whitespace  
* blank lines contain no whitespace  
* NEVER commit/push without a request  
* NEVER embed API keys/secrets in prompts or code  
* use pythonic, vectorized idioms (Python ≥3.11)  
* type hints: intrinsic `list`, `dict`, etc. (Python ≥3.9)  
* code should be elegant, optimized, and simple (no duplication)  

### Skills
- Scaffold: `pi skill create <name>` → `<name>/` with `SKILL.md`, `index.py`, `tests/`, `README.md`  
- `run()` must return JSON‑compatible output (or explicit `return`)  
- Import heavy modules inside `run()` (lazy)  
- Read `PI_*` env vars early; fail fast if missing  

### Pitfalls
- Missing `return` → no output  
- `print()` instead of `stdout` → hidden from harness  
- Top‑level heavy imports → slow cold start  
- Ignoring `PI_*` env vars → unexpected behavior  

### Tags (for discovery)
| Category | Tags |
|---|---|
| Language | `python`, `bash`, `javascript` |
| Domain | `data-analysis`, `file-transform`, `web-scraping`, `ml-inference` |
| Output | `json`, `text`, `image`, `html` |
| UI mode | `cli`, `tui`, `web` |

### Health check
- Emit `{"status":"ok"}` on startup so the harness can report agent status  

### Optional CI gate (if you add workflows)
- Warn if AGENTS.md has fewer than 10 principle bullets
