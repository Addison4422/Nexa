"""WSGI entry point.

Lets the Flask CLI find the application without extra configuration:

    python -m flask run
    python -m flask init-db
    python -m flask seed-demo
"""

from __future__ import annotations

import os

from nexacart import create_app

app = create_app(os.environ.get("NEXACART_ENV", "default"))

if __name__ == "__main__":  # pragma: no cover
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=True)
