"""The rules uploaded strategy code must follow. `docs/algo-rules.md` lists the same values and a
test compares them, so the page an author reads and the check the site runs cannot drift apart.

Nothing here runs code; `validate.py` reads these, and the sandbox (step 25b) enforces the limits.
"""

from app.algos.api import MAX_LOG_CHARS, MAX_LOG_LINES

MAX_SOURCE_BYTES = 50 * 1024
INTERVALS = ("1m", "5m", "15m", "1h", "1d", "1wk")
# Upper bound for the class-level `warmup_bars` literal (the backtester and the sim preload that many bars).
MAX_WARMUP_BARS = 1000

# The only modules uploaded code may import. `hq` is the strategy API (`algos/hq.py`).
ALLOWED_IMPORTS = ("hq", "math", "statistics", "decimal")

# Names that may not appear anywhere, with the reason shown to the author. Each one is a way to
# reach files, the interpreter or other code; `type` would let code build classes that skip the checks.
FORBIDDEN_NAMES = {
    "open": "strategies can't read or write files.",
    "eval": "strategies can't run code built from text.",
    "exec": "strategies can't run code built from text.",
    "compile": "strategies can't run code built from text.",
    "__import__": "strategies can't load modules by name.",
    "globals": "strategies can't look at the interpreter's variables.",
    "locals": "strategies can't look at the interpreter's variables.",
    "vars": "strategies can't look at the interpreter's variables.",
    "getattr": "strategies can't look up attributes by a name held in a string.",
    "setattr": "strategies can't set attributes by a name held in a string.",
    "delattr": "strategies can't delete attributes by a name held in a string.",
    "input": "strategies can't ask for input.",
    "breakpoint": "strategies can't start a debugger.",
    "memoryview": "strategies can't reach raw memory.",
    "type": "strategies can't build or inspect classes this way.",
    "BaseException": "catching it would hide the run being stopped (use `Exception`).",
}

# `str.format` can walk attributes from inside a string ("{0.__class__}"), which skips the
# underscore rule, so the methods that read such strings are out.
FORBIDDEN_ATTRIBUTES = ("format", "format_map")

# Decorators a strategy may use.
ALLOWED_DECORATORS = ("classmethod", "staticmethod")

# Limits the sandbox enforces while a strategy runs (step 25b).
CPU_SECONDS_PER_HOOK = 2
WALL_SECONDS_PER_RUN = 30
MEMORY_MB = 256
# The log limits (MAX_LOG_LINES, MAX_LOG_CHARS) are the API's own, imported above so there is one value.

# What the doc must list, by name, for the drift test.
DOCUMENTED_LIMITS = {
    "MAX_SOURCE_BYTES": MAX_SOURCE_BYTES,
    "CPU_SECONDS_PER_HOOK": CPU_SECONDS_PER_HOOK,
    "WALL_SECONDS_PER_RUN": WALL_SECONDS_PER_RUN,
    "MEMORY_MB": MEMORY_MB,
    "MAX_WARMUP_BARS": MAX_WARMUP_BARS,
    "MAX_LOG_LINES": MAX_LOG_LINES,
    "MAX_LOG_CHARS": MAX_LOG_CHARS,
}
