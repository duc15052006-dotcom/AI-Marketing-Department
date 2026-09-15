from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_required(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"PRODUCTIZATION_PATCH_FAILED: expected {label} anchor was not found")
    return text.replace(old, new)


def patch_rust_desktop() -> None:
    path = ROOT / "src-tauri" / "src" / "main.rs"
    text = path.read_text(encoding="utf-8")

    if "find_packaged_backend_executable" not in text:
        anchor = """    primary\n}\n\npub fn parse_bootstrap_line"""
        helper = r'''    primary
}

/// Resolve the release-packaged Python backend sidecar before falling back to
/// a developer source checkout. Tauri resources preserve the configured
/// `resources/backend` path on Windows, while the extra candidates keep local
/// release smoke builds and future resource remaps compatible.
pub fn find_packaged_backend_executable() -> Option<PathBuf> {
    if let Ok(explicit) = std::env::var("AI_MARKETING_BACKEND_EXE") {
        let candidate = PathBuf::from(explicit);
        if candidate.is_file() {
            return Some(candidate);
        }
    }

    let exe = std::env::current_exe().ok()?;
    let exe_dir = exe.parent()?;
    let candidates = [
        exe_dir.join("resources").join("backend").join("ai-marketing-backend.exe"),
        exe_dir.join("backend").join("ai-marketing-backend.exe"),
        exe_dir.join("ai-marketing-backend.exe"),
    ];
    candidates.into_iter().find(|candidate| candidate.is_file())
}

pub fn parse_bootstrap_line'''
        text = replace_required(text, anchor, helper, "Rust packaged-backend helper")

    old_spawn = '''fn spawn_backend_and_bootstrap() -> (Option<u32>, Option<usize>, Option<job_object::JobObjectHandle>, Option<String>, String, u16) {
    let root_dir = find_project_root();
    let server_script = root_dir.join("app_api").join("server.py");

    let mut default_host = "127.0.0.1".to_string();'''
    new_spawn = '''fn spawn_backend_and_bootstrap() -> (Option<u32>, Option<usize>, Option<job_object::JobObjectHandle>, Option<String>, String, u16) {
    let packaged_backend = find_packaged_backend_executable();
    let root_dir = if let Some(ref backend_exe) = packaged_backend {
        // The packaged PyInstaller executable is self-contained. Its parent is
        // guaranteed to exist and is a safe current directory for CreateProcess.
        backend_exe
            .parent()
            .map(|p| p.to_path_buf())
            .unwrap_or_else(find_project_root)
    } else {
        find_project_root()
    };
    let server_script = root_dir.join("app_api").join("server.py");

    if let Some(ref backend_exe) = packaged_backend {
        // Reuse the hardened Windows Job Object/bootstrap path without adding a
        // second process-launch implementation. The frozen backend ignores the
        // legacy source-script positional argument and honors --emit-bootstrap.
        std::env::set_var("PYTHON_PATH", backend_exe);
        println!("Using packaged backend sidecar: {:?}", backend_exe);
    }

    let mut default_host = "127.0.0.1".to_string();'''
    if old_spawn in text:
        text = text.replace(old_spawn, new_spawn, 1)
    elif "let packaged_backend = find_packaged_backend_executable();" not in text:
        raise SystemExit("PRODUCTIZATION_PATCH_FAILED: Rust spawn anchor was not found")

    path.write_text(text, encoding="utf-8")


def patch_model_settings_ui() -> None:
    path = ROOT / "frontend" / "src" / "components" / "ModelSettingsView.tsx"
    text = path.read_text(encoding="utf-8")
    text = replace_required(
        text,
        "['CMO', 'INTELLIGENCE', 'STRATEGIST', 'CREATIVE', 'PERFORMANCE']",
        "['CMO', 'INTELLIGENCE', 'CONTENT', 'CREATIVE', 'PERFORMANCE']",
        "Model Settings fallback agent list",
    )
    text = replace_required(
        text,
        "all 5 agents (CMO, Intelligence, Strategist, Creative, Performance)",
        "all 5 agents (CMO, Intelligence, Content, Creative, Performance)",
        "Model Settings current-agent copy",
    )
    path.write_text(text, encoding="utf-8")


def patch_readme() -> None:
    path = ROOT / "README.md"
    text = path.read_text(encoding="utf-8")

    replacements = [
        (
            "CMO, Intelligence, Strategist, Creative, and Performance",
            "CMO, Intelligence, Content, Creative, and Performance",
            "README agent summary",
        ),
        (
            "- **Strategist** — định vị, chiến lược, GTM và thiết kế thử nghiệm.",
            "- **Content** — kiến trúc thông điệp, copy, kịch bản, editorial/SEO, content experiments và thích ứng theo kênh.",
            "README Vietnamese Content role",
        ),
        (
            "- **Creative** — concept, copy, kịch bản, storyboard và định hướng sản xuất nội dung.",
            "- **Creative** — concept hình ảnh/multimedia, storyboard, shotlist, media specification và định hướng sản xuất asset.",
            "README Vietnamese Creative role",
        ),
        (
            "3. **Strategist** — positioning, go-to-market strategy, growth planning, and experiments.",
            "3. **Content** — evidence-grounded messaging, copy/scripts, editorial/SEO planning, content experiments, and channel adaptation.",
            "README English Content role",
        ),
        (
            "4. **Creative** — concepts, copy, scripts, storyboards, and creative production planning.",
            "4. **Creative** — visual/multimedia concepts, storyboards, shotlists, media specifications, and asset-production planning.",
            "README English Creative role",
        ),
        ("│   STRATEGIST   │", "│    CONTENT     │", "README architecture Content label"),
        ("│ Strategy / GTM │", "│ Messaging/Copy │", "README architecture Content responsibility"),
        ("│ Content / Idea │", "│ Visual / Media │", "README architecture Creative responsibility"),
    ]
    for old, new, label in replacements:
        text = replace_required(text, old, new, label)

    if "Strategist" in text or "STRATEGIST" in text:
        raise SystemExit("PRODUCTIZATION_PATCH_FAILED: README still contains current Strategist identity text")

    path.write_text(text, encoding="utf-8")


def main() -> None:
    patch_rust_desktop()
    patch_model_settings_ui()
    patch_readme()
    print("PRODUCTIZATION_PATCH_OK")


if __name__ == "__main__":
    main()
