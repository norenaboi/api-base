"""Desktop launcher: runs the Waitress server in a background thread and opens
a native OS window via pywebview. Closing the window exits the process cleanly.
"""
from __future__ import annotations

import os
import socket
import threading
from pathlib import Path

import webview
from waitress import serve

from api_base.web import create_app


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main() -> None:
    port = _free_port()
    app = create_app()

    server_thread = threading.Thread(
        target=serve,
        args=(app,),
        kwargs={"host": "127.0.0.1", "port": port, "threads": 4},
        daemon=True,
    )
    server_thread.start()

    window = webview.create_window(
        "API Base",
        f"http://127.0.0.1:{port}/",
        width=1280,
        height=900,
        min_size=(900, 600),
    )

    def on_closed():
        # Allow the daemon server thread to die with the process.
        pass

    window.events.closing += on_closed
    webview.start()
    # webview.start() blocks until the window is closed; daemon thread dies with us.


if __name__ == "__main__":
    main()
