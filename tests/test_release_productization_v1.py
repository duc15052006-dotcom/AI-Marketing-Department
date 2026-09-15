from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_AGENTS = ("CMO", "INTELLIGENCE", "CONTENT", "CREATIVE", "PERFORMANCE")


class ReleaseProductizationV1Tests(unittest.TestCase):
    def test_tauri_bundles_generated_backend_resource(self) -> None:
        cfg = json.loads((ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
        resources = cfg.get("bundle", {}).get("resources", [])
        self.assertTrue(
            any("resources/backend" in str(item).replace("\\", "/") for item in resources),
            "Tauri bundle must include the generated standalone backend resource directory.",
        )

    def test_desktop_runtime_prefers_packaged_backend_when_available(self) -> None:
        src = (ROOT / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
        self.assertIn("find_packaged_backend_executable", src)
        self.assertIn("ai-marketing-backend.exe", src)
        self.assertIn("PYTHON_PATH", src)

    def test_release_build_script_builds_and_smoke_tests_sidecar(self) -> None:
        script = (ROOT / "scripts" / "build_windows_release.ps1").read_text(encoding="utf-8")
        self.assertIn("PyInstaller", script)
        self.assertIn("--emit-bootstrap", script)
        self.assertIn("@tauri-apps/cli@2.11.4", script)
        self.assertIn("cargo test", script)

    def test_model_settings_fallback_identity_is_canonical(self) -> None:
        ui = (ROOT / "frontend" / "src" / "components" / "ModelSettingsView.tsx").read_text(encoding="utf-8")
        self.assertIn("['CMO', 'INTELLIGENCE', 'CONTENT', 'CREATIVE', 'PERFORMANCE']", ui)
        self.assertNotIn("all 5 agents (CMO, Intelligence, Strategist, Creative, Performance)", ui)

    def test_readme_current_agent_list_is_canonical(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("CMO, Intelligence, Content, Creative, and Performance", readme)
        self.assertIn("**Content**", readme)
        self.assertNotIn("**Strategist** — positioning", readme)

    def test_release_version_is_consistent(self) -> None:
        frontend = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
        tauri = json.loads((ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
        cargo = (ROOT / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")
        self.assertEqual(frontend.get("version"), "1.0.0")
        self.assertEqual(tauri.get("version"), "1.0.0")
        self.assertIn('version = "1.0.0"', cargo)


if __name__ == "__main__":
    unittest.main()
