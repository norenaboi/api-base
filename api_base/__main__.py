from __future__ import annotations

import os

from waitress import serve

from api_base.web import create_app


def main() -> None:
    host = os.environ.get("API_BASE_HOST", "127.0.0.1").strip()
    if not host:
        raise SystemExit("API_BASE_HOST must not be empty.")

    port_text = os.environ.get("API_BASE_PORT", "8765")
    try:
        port = int(port_text)
    except ValueError as error:
        raise SystemExit("API_BASE_PORT must be an integer.") from error
    if not 1 <= port <= 65535:
        raise SystemExit("API_BASE_PORT must be between 1 and 65535.")

    app = create_app()
    print(f"API Base is running at http://{host}:{port}", flush=True)
    serve(app, host=host, port=port, threads=4)


if __name__ == "__main__":
    main()
