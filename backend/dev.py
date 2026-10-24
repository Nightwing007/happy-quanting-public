"""Dev server: uvicorn under watchfiles, restarted when app/ changes.

Not `uvicorn --reload`: on Windows its reloader sends CTRL_C_EVENT to the whole console
process group, which also kills the Next.js server running beside it.
"""

import os
from pathlib import Path

import uvicorn
from watchfiles import run_process

HERE = Path(__file__).resolve().parent


def serve() -> None:
    uvicorn.run("app.main:app", host="127.0.0.1", port=int(os.environ.get("PORT", "8000")))


if __name__ == "__main__":
    run_process(HERE / "app", target=serve)
