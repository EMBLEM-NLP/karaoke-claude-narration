import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_json(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_codex_manifest_is_valid_shape():
    manifest = load_json(".codex-plugin/plugin.json")
    assert manifest["name"] == "karaoke-narration"
    assert manifest["version"] == (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert manifest["skills"] == "./skills/"
    assert manifest["mcpServers"] == "./.mcp.json"
    assert "hooks" not in manifest
    assert manifest["interface"]["displayName"] == "Karaoke Narration"


def test_mcp_config_points_to_openai_adapter():
    config = load_json(".mcp.json")
    server = config["mcpServers"]["karaoke-narration"]
    assert server["command"] == "python3"
    assert server["args"] == ["${PLUGIN_ROOT}/mcp/openai_server.py"]
    assert server["env"]["KARAOKE_PLUGIN_ROOT"] == "${PLUGIN_ROOT}"


def test_stop_hook_uses_json_safe_entrypoint():
    hooks = load_json("hooks/hooks.json")
    stop_hooks = hooks["hooks"]["Stop"][0]["hooks"]
    assert stop_hooks[0]["args"] == ["${CLAUDE_PLUGIN_ROOT}/scripts/stop_hook_entry.py"]
    assert stop_hooks[0]["async"] is True


def test_openai_adapter_imports_without_mcp_dependency():
    path = ROOT / "mcp" / "openai_server.py"
    spec = importlib.util.spec_from_file_location("openai_server", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.compare_texts("Use [this](https://example.com).", "Use this.")["matches"]
    assert not module.compare_texts("alpha beta", "alpha gamma")["matches"]


def test_narrate_text_fails_before_writing_when_preflight_fails(tmp_path, monkeypatch):
    path = ROOT / "mcp" / "openai_server.py"
    spec = importlib.util.spec_from_file_location("openai_server_preflight", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    missing = {"ok": False, "missing": ["piper_binary"], "checks": {}, "fix": None}
    monkeypatch.setattr(module, "DATA", tmp_path)
    monkeypatch.setattr(module, "preflight", lambda: missing)

    result = module.narrate_text("hello world")

    assert result == {
        "ok": False,
        "error": "preflight_failed",
        "preflight": missing,
    }
    assert not (tmp_path / "narrations").exists()


def test_codex_skill_states_surface_boundary():
    skill = (ROOT / "skills" / "karaoke-narration-codex" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "Never say a response was narrated unless" in skill
    assert "ChatGPT web/mobile" in skill
    assert "Stop" in skill
