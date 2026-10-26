"""Development entry point:  python run.py"""

from __future__ import annotations

import os

from nexacart import create_app

app = create_app(os.environ.get("NEXACART_ENV", "default"))

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=True)
