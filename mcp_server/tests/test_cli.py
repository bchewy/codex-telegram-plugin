from __future__ import annotations

from codex_telegram.__main__ import build_parser


def test_cli_accepts_login_flags():
    parser = build_parser()
    args = parser.parse_args(
        [
            "login",
            "--api-id",
            "12345",
            "--api-hash",
            "secret",
            "--phone",
            "+15555555555",
            "--master-key",
            "abc",
        ]
    )

    assert args.command == "login"
    assert args.api_id == 12345
    assert args.api_hash == "secret"
    assert args.phone == "+15555555555"
    assert args.master_key == "abc"


def test_cli_accepts_serve_command():
    parser = build_parser()
    args = parser.parse_args(["serve"])
    assert args.command == "serve"
