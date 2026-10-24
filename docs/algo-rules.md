# Rules for algorithm code

What the site checks before it accepts a strategy you wrote. The checker is `backend/app/algos/validate.py`;
the numbers below live in `backend/app/algos/rules.py` and a test keeps this page in step with them.

## The file

- One `.py` file, at most **50 KB**.
- Exactly one class that subclasses `hq.Strategy`. Other helper classes and functions are fine.
- The class sets these in its body, written as plain values (no calculations, no variables):
  `name`, `description`, `markets`, `interval`, `PARAMETERS`.
  - `interval` is one of `1m` `5m` `15m` `1h` `1d` `1wk`.
  - `markets` lists segments or market codes, e.g. `("india", "crypto")`.
  - `PARAMETERS` is a dict of `hq.Param(...)`; `Decimal("1.5")` counts as a plain value.
- Top-level code is limited to imports, constants (plain values), functions and classes.

## Imports

Only `hq`, `math`, `statistics` and `decimal`. Write `import hq` or `from hq import Strategy, Param`.

## Not allowed

- These names, anywhere: `open` `eval` `exec` `compile` `__import__` `globals` `locals` `vars` `getattr`
  `setattr` `delattr` `input` `breakpoint` `memoryview` `type` `BaseException`.
- Any name or attribute that starts with `_` (private and dunder names such as `__class__`).
  A lone `_` is fine (`for _ in range(3)`).
- `.format(...)` and `.format_map(...)`: use f-strings.
- `global`, `nonlocal`, `async`, `await`, `yield`, `with`, `del`, `match`, a bare `except:`.
- Decorators other than `classmethod` and `staticmethod` (written `@classmethod`).
- Randomness and the clock: no `random`, `time` or `datetime`. Read the time with `ctx.now`.

`lambda` and `while` are fine. A `while` loop must end on its own; the CPU limit below stops one that doesn't.

## Limits (enforced while the strategy runs)

```
MAX_SOURCE_BYTES = 51200
CPU_SECONDS_PER_HOOK = 2
WALL_SECONDS_PER_RUN = 30
MEMORY_MB = 256
MAX_LOG_LINES = 500
MAX_LOG_CHARS = 200
```

CPU time is per call of `on_start`, `on_bar` or `on_trade_closed`. Wall time is for the whole run.
Anything logged past the line limit is dropped, and each line is cut at the character limit.

## Dry run

After the checks pass, the site plays your strategy over made-up prices. It fails if any hook raises;
you get the line that raised. Placing no orders is fine.

## Smallest valid strategy

```python
import hq


class BuyAndWait(hq.Strategy):
    name = "Buy and wait"
    description = "Buys once with a tenth of the cash and holds."
    markets = ("india", "international", "crypto")
    interval = "1d"
    PARAMETERS = {
        "percent_of_cash": hq.Param("int", 10, min=1, max=100, label="Cash to spend (%)"),
    }

    def on_bar(self, ctx):
        for symbol in ctx.symbols:
            if ctx.position(symbol).quantity == 0:
                ctx.buy(symbol, percent_of_cash=ctx.params["percent_of_cash"])
```
