import importlib.util
import json
import subprocess
import sys
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



def test_check_module_ignores_shadowing_from_current_directory(tmp_path, monkeypatch):
    path = ROOT / "mcp" / "openai_server.py"
    spec = importlib.util.spec_from_file_location("openai_server_shadowed", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    (tmp_path / "json.py").write_text("raise RuntimeError('shadowed import')\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert module._check_module("json") is True


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


def test_narrate_chat_response_returns_packed_player(monkeypatch):
    path = ROOT / "mcp" / "openai_server.py"
    spec = importlib.util.spec_from_file_location("openai_server_chat_response", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    calls = {}

    def fake_narrate_text(text, title, label, model=None, model_id=None, mode=None):
        calls["narrate_text"] = {
            "text": text,
            "title": title,
            "label": label,
            "model": model,
            "model_id": model_id,
            "mode": mode,
        }
        return {
            "ok": True,
            "state": "ready",
            "narration_id": "abc123abc123abc1",
            "word_count": 5,
        }

    def fake_get_player(narration_id):
        calls["get_player"] = narration_id
        return {
            "ok": True,
            "narration_id": narration_id,
            "content_type": "text/html",
            "html": (
                '<main><div id="transcript"><div class="blk p"><div>'
                "Exact chat response."
                "</div></div></div></main><script>render()</script>"
            ),
        }

    monkeypatch.setattr(module, "narrate_text", fake_narrate_text)
    monkeypatch.setattr(module, "get_player", fake_get_player)

    result = module.narrate_chat_response(
        "Exact chat response.",
        title="Current response",
        model="gpt-test",
        model_id="model-id",
        mode="high",
    )

    assert calls["narrate_text"] == {
        "text": "Exact chat response.",
        "title": "Current response",
        "label": "Chat response",
        "model": "gpt-test",
        "model_id": "model-id",
        "mode": "high",
    }
    assert calls["get_player"] == "abc123abc123abc1"
    assert result["ok"] is True
    assert result["content_type"] == "text/html"
    assert "Exact chat response." in result["html"].split("<script>", 1)[0]
    assert "__STATIC_TRANSCRIPT_FALLBACK__" not in result["html"]


def test_packed_player_contains_static_transcript_fallback(tmp_path):
    mp3 = tmp_path / "turn.mp3"
    mp3.write_bytes(b"not a real mp3; packer only embeds bytes")
    timing = tmp_path / "turn.timing.json"
    text = "Hello chat response. This must be visible before JavaScript runs."
    timing.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "source_text": text,
                "duration": 1.0,
                "words": [
                    {"w": "Hello", "start": 0.0, "end": 0.2},
                    {"w": "chat", "start": 0.2, "end": 0.4},
                    {"w": "response.", "start": 0.4, "end": 0.6},
                ],
                "blocks": [
                    {
                        "type": "paragraph",
                        "level": 0,
                        "turn": 0,
                        "narrated": True,
                        "text": text,
                        "sentences": [
                            {
                                "i": 0,
                                "text": text,
                                "start": 0.0,
                                "end": 1.0,
                                "words": [
                                    {"w": "Hello", "start": 0.0, "end": 0.2},
                                    {"w": "chat", "start": 0.2, "end": 0.4},
                                    {"w": "response.", "start": 0.4, "end": 0.6},
                                ],
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "player.html"

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "skills" / "karaoke-narration" / "scripts" / "pack_standalone.py"),
            str(mp3),
            str(timing),
            "--artifact",
            "-o",
            str(out),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    html = out.read_text(encoding="utf-8")
    before_script = html.split("<script>", 1)[0]
    assert '<div id="transcript"><div class="blk p"><div>Hello chat response.' in html
    assert text in before_script
    assert "fallbackAudio" not in html
    assert "data:audio/mpeg" not in html
    assert "__STATIC_TRANSCRIPT_FALLBACK__" not in html


def test_codex_skill_states_surface_boundary():
    skill = (ROOT / "skills" / "karaoke-narration-codex" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "Never say a response was narrated unless" in skill
    assert "ChatGPT web/mobile" in skill
    assert "Stop" in skill


def test_codex_skill_prefers_one_call_chat_response_tool():
    skill = (ROOT / "skills" / "karaoke-narration-codex" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "call `narrate_chat_response` with the exact response text" in skill
    assert "Never open or share `player_embed_template.html`" in skill
