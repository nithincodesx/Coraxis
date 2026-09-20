"""Command-line interface.

coraxis serve          run the API
coraxis init           apply migrations
coraxis create-user    provision an account without the HTTP API
coraxis check          verify configuration and dependencies
coraxis dev            run API and frontend together
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence

from coraxis import __version__


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="coraxis",
        description="Coraxis — autonomous multi-agent research platform.",
    )
    parser.add_argument("--version", action="version", version=f"coraxis {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="Run the API server.")
    serve.add_argument("--host", default=None, help="Bind address. Defaults to settings.")
    serve.add_argument("--port", type=int, default=None, help="Port. Defaults to settings.")
    serve.add_argument("--reload", action="store_true", help="Restart on code changes.")
    serve.add_argument("--workers", type=int, default=1, help="Worker processes.")

    subparsers.add_parser("init", help="Apply database migrations.")
    subparsers.add_parser("check", help="Verify configuration and dependencies.")
    subparsers.add_parser("dev", help="Run the API and the frontend together.")

    create_user = subparsers.add_parser("create-user", help="Create an account directly.")
    create_user.add_argument("email")
    create_user.add_argument("--password", default=None, help="Prompted for if omitted.")
    create_user.add_argument("--name", default="", help="Display name.")
    create_user.add_argument("--superuser", action="store_true", help="Grant administrator.")

    return parser


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from coraxis.core.config import get_settings

    settings = get_settings()
    host = args.host or settings.host
    port = args.port or settings.port

    # Publish the resolved bind address so the app's startup banner reports the
    # address it is actually listening on, rather than the configured default.
    # Both routes are needed: the assignment covers the in-process case, and the
    # environment variables cover `--workers N`, where uvicorn re-imports the
    # app in a fresh subprocess that never sees this mutation.
    settings.host = host
    settings.port = port
    os.environ["CORAXIS_HOST"] = host
    os.environ["CORAXIS_PORT"] = str(port)

    if args.reload and args.workers > 1:
        print("--reload and --workers are mutually exclusive.", file=sys.stderr)
        return 2

    if args.reload:
        uvicorn.run("coraxis.main:app", host=host, port=port, reload=True)
    else:
        uvicorn.run(
            "coraxis.main:app",
            host=host,
            port=port,
            workers=args.workers,
            # Let the app's own middleware emit access logs so they carry the
            # request id and response time.
            access_log=False,
        )
    return 0


def _cmd_init() -> int:
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    config_path = Path(__file__).resolve().parents[3] / "alembic.ini"
    if not config_path.exists():
        print(f"Could not find alembic.ini at {config_path}", file=sys.stderr)
        return 1

    command.upgrade(Config(str(config_path)), "head")
    print("Database is up to date.")
    return 0


async def _create_user(email: str, password: str, name: str, superuser: bool) -> int:
    from coraxis.core.security import hash_password, validate_password_strength
    from coraxis.db.session import dispose_engine, session_scope
    from coraxis.repositories import users as user_repo

    try:
        validate_password_strength(password)
    except Exception as exc:  # noqa: BLE001 - surfaced to the operator
        print(f"Password rejected: {exc}", file=sys.stderr)
        return 1

    try:
        async with session_scope() as session:
            if await user_repo.get_by_email(session, email) is not None:
                print(f"An account already exists for {email}.", file=sys.stderr)
                return 1
            user = await user_repo.create(
                session,
                email=email,
                password_hash=hash_password(password),
                display_name=name,
                is_superuser=superuser,
            )
            print(f"Created user {user.email} ({user.id})")
    finally:
        await dispose_engine()
    return 0


def _cmd_create_user(args: argparse.Namespace) -> int:
    import getpass

    password = args.password
    if not password:
        password = getpass.getpass("Password: ")
        confirmation = getpass.getpass("Confirm: ")
        if password != confirmation:
            print("Passwords did not match.", file=sys.stderr)
            return 1

    return asyncio.run(_create_user(args.email, password, args.name, args.superuser))


def _cmd_check() -> int:
    """Report configuration and dependency status without starting the server."""
    import importlib

    from coraxis.core.config import get_settings
    from coraxis.db.enums import PROVIDERS

    problems = 0

    try:
        settings = get_settings()
    except Exception as exc:  # noqa: BLE001 - this command exists to report exactly this
        print(f"[FAIL] Configuration is invalid:\n  {exc}", file=sys.stderr)
        return 1

    print(f"coraxis {__version__}  (env={settings.env})")
    print(f"  database        {settings.database_url}")
    print(f"  cors origins    {', '.join(settings.cors_origin_list)}")
    print(f"  memory          {'enabled' if settings.memory_enabled else 'disabled'}")

    secret = settings.secret_key.get_secret_value()
    if not secret:
        print("  [WARN] CORAXIS_SECRET_KEY is unset — development only.")
    elif len(secret) < 32:
        print("  [WARN] CORAXIS_SECRET_KEY is short. Use at least 32 characters.")
    else:
        print("  secret key      set")

    print("  provider keys   ", end="")
    available = [p for p in PROVIDERS if settings.providers.key_for(p)]
    print(", ".join(available) if available else "none (users must supply their own)")

    print("\nDependencies:")
    for module in (
        "fastapi",
        "uvicorn",
        "sqlalchemy",
        "alembic",
        "aiosqlite",
        "jwt",
        "argon2",
        "cryptography",
        "crewai",
        "litellm",
        "chromadb",
        "duckduckgo_search",
        "trafilatura",
    ):
        try:
            importlib.import_module(module)
            print(f"  [ok]   {module}")
        except Exception as exc:  # noqa: BLE001
            print(f"  [FAIL] {module}: {type(exc).__name__}")
            problems += 1

    print("\nResult:", "FAILED" if problems else "OK")
    return 1 if problems else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "serve":
        return _cmd_serve(args)
    if args.command == "init":
        return _cmd_init()
    if args.command == "check":
        return _cmd_check()
    if args.command == "create-user":
        return _cmd_create_user(args)
    if args.command == "dev":
        from coraxis.cli.dev import run_dev

        return run_dev()

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
