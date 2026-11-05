"""styri users: manage accounts from the terminal, the same ones the Users screen does.

    styri users list
    styri users add m.lind --role operator
    styri users role m.lind viewer
    styri users password m.lind
    styri users remove m.lind

Passwords are asked for, or read from stdin with --password-stdin. A running panel
picks changes up by itself.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

from .auth import OPERATOR, ROLES, AccountError, Accounts


def _password(stdin: bool) -> str:
    if stdin:
        return sys.stdin.readline().rstrip("\n")
    first = getpass.getpass("Password: ")
    if first != getpass.getpass("Again: "):
        raise AccountError("the passwords don't match")
    return first


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="styri users", description=__doc__.split("\n\n")[0])
    default = Path(os.environ.get("STYRI_AUDIT_DB", "/var/lib/styri/audit.db")).parent / "users.json"
    parser.add_argument("--file", default=str(default), help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    add = sub.add_parser("add")
    add.add_argument("name")
    add.add_argument("--role", choices=ROLES, default=OPERATOR)
    add.add_argument("--password-stdin", action="store_true")
    role = sub.add_parser("role")
    role.add_argument("name")
    role.add_argument("role", choices=ROLES)
    password = sub.add_parser("password")
    password.add_argument("name")
    password.add_argument("--password-stdin", action="store_true")
    remove = sub.add_parser("remove")
    remove.add_argument("name")
    args = parser.parse_args(argv)
    accounts = Accounts(args.file, env={})
    try:
        if args.command == "list":
            for user in accounts.list():
                print(f"{user['name']:<24} {user['role']}")
        elif args.command == "add":
            accounts.add(args.name, _password(args.password_stdin), args.role)
            print(f"Added {args.name} as {args.role}.")
        elif args.command == "role":
            accounts.set_role(args.name, args.role)
            print(f"{args.name} is now {args.role}.")
        elif args.command == "password":
            accounts.set_password(args.name, _password(args.password_stdin))
            print(f"Password changed for {args.name}. Their sessions have ended.")
        elif args.command == "remove":
            accounts.remove(args.name)
            print(f"Removed {args.name}. Their past commands stay in the log.")
    except AccountError as exc:
        print(f"{str(exc).capitalize()}.", file=sys.stderr)
        return 1
    return 0
