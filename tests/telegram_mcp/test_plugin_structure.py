"""Structural conformance tests for the telegram/ plugin bundle.

Validates the portable Agent Plugins 1.0.0 files (plugin.json, mcp.json)
against the vendored published schemas, checks the spec constraints that JSON
Schema cannot express, and keeps the Codex-native manifests
(.codex-plugin/plugin.json, .mcp.json) in sync with the portable ones.

Spec: https://agent-plugins.org/specification
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import jsonschema
import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "telegram"
SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"

PLUGIN_SCHEMA_ID = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
MCP_SCHEMA_ID = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def portable_manifest() -> dict:
    return _load(PLUGIN_ROOT / "plugin.json")


@pytest.fixture(scope="module")
def portable_mcp() -> dict:
    return _load(PLUGIN_ROOT / "mcp.json")


@pytest.fixture(scope="module")
def codex_manifest() -> dict:
    return _load(PLUGIN_ROOT / ".codex-plugin" / "plugin.json")


@pytest.fixture(scope="module")
def codex_mcp() -> dict:
    return _load(PLUGIN_ROOT / ".mcp.json")


class TestPortableManifest:
    def test_validates_against_published_schema(self, portable_manifest: dict) -> None:
        schema = _load(SCHEMA_DIR / "agent-plugins-1.0.0-plugin.schema.json")
        jsonschema.validate(portable_manifest, schema)

    def test_schema_identifier(self, portable_manifest: dict) -> None:
        assert portable_manifest["$schema"] == PLUGIN_SCHEMA_ID

    def test_name_constraints(self, portable_manifest: dict) -> None:
        name = portable_manifest["name"]
        assert 1 <= len(name) <= 64
        assert re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", name)
        assert "--" not in name and ".." not in name


class TestPortableMcp:
    def test_validates_against_published_schema(self, portable_mcp: dict) -> None:
        schema = _load(SCHEMA_DIR / "agent-plugins-1.0.0-mcp.schema.json")
        jsonschema.validate(portable_mcp, schema)

    def test_schema_identifier(self, portable_mcp: dict) -> None:
        assert portable_mcp["$schema"] == MCP_SCHEMA_ID

    def test_declares_telegram_personal_stdio_server(self, portable_mcp: dict) -> None:
        server = portable_mcp["mcpServers"]["telegram_personal"]
        assert server["type"] == "stdio"

    def test_command_is_single_token(self, portable_mcp: dict) -> None:
        """§7.2.1: command is one executable token, bare or ./-relative."""
        for name, server in portable_mcp["mcpServers"].items():
            if server["type"] != "stdio":
                continue
            command = server["command"]
            assert " " not in command, f"{name}: command must be one token"
            assert "${" not in command, f"{name}: no placeholder expansion in command"
            if "/" in command:
                assert command.startswith("./"), (
                    f"{name}: path commands must be plugin-relative (./...)"
                )

    def test_no_codex_only_fields(self, portable_mcp: dict) -> None:
        codex_only = {"env_vars", "startup_timeout_sec", "tool_timeout_sec"}
        for name, server in portable_mcp["mcpServers"].items():
            leaked = codex_only & set(server)
            assert not leaked, f"{name}: Codex-only fields in portable mcp.json: {leaked}"

    def test_env_has_no_secrets_or_reserved_names(self, portable_mcp: dict) -> None:
        secret_markers = ("KEY", "TOKEN", "SECRET", "HASH", "SESSION", "PASSWORD")
        for name, server in portable_mcp["mcpServers"].items():
            for env_name, env_value in server.get("env", {}).items():
                assert env_name not in {"PLUGIN_ROOT", "PLUGIN_DATA"}, (
                    f"{name}: env must not set reserved {env_name}"
                )
                looks_placeholder = env_value.startswith("${PLUGIN_")
                assert looks_placeholder or not any(
                    marker in env_name.upper() for marker in secret_markers
                ), f"{name}: suspicious secret-like env entry {env_name}"

    def test_placeholders_resolve_to_bundled_project(self, portable_mcp: dict) -> None:
        server = portable_mcp["mcpServers"]["telegram_personal"]
        expanded = [
            arg.replace("${PLUGIN_ROOT}", str(PLUGIN_ROOT)) for arg in server["args"]
        ]
        project_args = [arg for arg in expanded if arg.endswith("mcp_server")]
        assert project_args, "expected a --project arg pointing at mcp_server"
        for arg in project_args:
            resolved = Path(arg).resolve()
            assert resolved.is_dir()
            assert resolved.is_relative_to(PLUGIN_ROOT.resolve())

    def test_cwd_form(self, portable_mcp: dict) -> None:
        for name, server in portable_mcp["mcpServers"].items():
            cwd = server.get("cwd")
            if cwd is None:
                continue
            assert re.match(
                r"^(?:\./|\$\{PLUGIN_ROOT\}(?:/|$)|\$\{PLUGIN_DATA\}(?:/|$))", cwd
            ), f"{name}: invalid cwd form {cwd!r}"


class TestSkillsDiscovery:
    def test_skills_are_immediate_children_with_skill_md(self) -> None:
        skills_dir = PLUGIN_ROOT / "skills"
        skill_dirs = [p for p in skills_dir.iterdir() if p.is_dir()]
        assert skill_dirs
        for skill_dir in skill_dirs:
            assert (skill_dir / "SKILL.md").is_file(), f"{skill_dir.name}: missing SKILL.md"

    def test_frontmatter_name_matches_directory(self) -> None:
        skills_dir = PLUGIN_ROOT / "skills"
        for skill_dir in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
            text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
            match = re.search(r"^---\n(.*?)\n---", text, re.DOTALL)
            assert match, f"{skill_dir.name}: missing frontmatter"
            frontmatter = match.group(1)
            name_match = re.search(r"^name:\s*(\S+)\s*$", frontmatter, re.MULTILINE)
            assert name_match, f"{skill_dir.name}: frontmatter missing name"
            assert name_match.group(1) == skill_dir.name
            assert re.search(r"^description:\s*\S", frontmatter, re.MULTILINE), (
                f"{skill_dir.name}: frontmatter missing description"
            )


class TestDualLayoutSync:
    """The Codex-native manifests stay authoritative for Codex; keep the
    shared metadata identical so the two layouts never drift."""

    def test_versions_match(self, portable_manifest: dict, codex_manifest: dict) -> None:
        assert portable_manifest["version"] == codex_manifest["version"]

    def test_names_match(self, portable_manifest: dict, codex_manifest: dict) -> None:
        assert portable_manifest["name"] == codex_manifest["name"]

    def test_shared_metadata_matches(
        self, portable_manifest: dict, codex_manifest: dict
    ) -> None:
        for field in ("author", "homepage", "repository", "license", "keywords"):
            assert portable_manifest[field] == codex_manifest[field], field

    def test_same_server_launch_in_both_configs(
        self, portable_mcp: dict, codex_mcp: dict
    ) -> None:
        portable = portable_mcp["mcpServers"]["telegram_personal"]
        codex = codex_mcp["mcpServers"]["telegram_personal"]
        assert portable["command"] == codex["command"]

        def normalize(args: list[str]) -> list[str]:
            return [
                arg.replace("${PLUGIN_ROOT}/", "./").replace("${PLUGIN_ROOT}", ".")
                for arg in args
            ]

        assert normalize(portable["args"]) == normalize(codex["args"])
