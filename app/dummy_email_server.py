from __future__ import annotations

import argparse

import uvicorn


def main() -> None:
    """runs the FastAPI app as a standalone local email receiver."""
    parser = argparse.ArgumentParser(description="Run the local dummy email receiver.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind.")
    parser.add_argument("--port", default=8025, type=int, help="Port to listen on.")
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Reload the server when application files change.",
    )
    args = parser.parse_args()

    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
