"""Write the app's OpenAPI schema to a file, for the frontend's type generation.

Usage: python scripts/export_openapi.py [output path]   (default: backend/openapi.json)
Importing the app only builds the FastAPI object; the lifespan (migrations, background
loop) runs only when a server starts, so this is safe to run anywhere.
"""

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.main import app  # noqa: E402


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else BACKEND_DIR / "openapi.json"
    target.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {target}")


if __name__ == "__main__":
    main()
