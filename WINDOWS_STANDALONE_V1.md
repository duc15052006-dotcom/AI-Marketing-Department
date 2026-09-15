# AI Marketing Department v1.0 — Windows Standalone Guide

This guide is for end users installing the standalone Windows build. You do **not** need to install Python, Node.js, npm, Git, Rust, or clone this repository to use the packaged v1.0 application.

## Install

Use one of the certified Windows installers produced by `Desktop Release Build V1`:

- **NSIS `.exe`** — recommended for normal Windows installation.
- **MSI `.msi`** — useful for environments that prefer Windows Installer packages.

Install the application, then launch **AI Marketing Department** from the installed location or Windows shortcut created by the installer.

The desktop application starts its packaged `ai-marketing-backend.exe` automatically. The end user does not need a local Python installation or a source checkout beside the app.

## First-run provider setup

The repository never ships a personal API key. Configure your own provider credential locally:

1. Open **Settings → AI Model & Provider Settings**.
2. Choose an existing provider or add a custom OpenAI-compatible provider.
3. Enter the provider's **model ID** and, when required, your **API key**.
4. Select **Test Connection**. A successful provider call must report `CONNECTED`.
5. Select **Save Provider**.
6. Under **Global Model Authority**, select the provider you want the department to use and enter the intended model ID.
7. Select **Save Settings**.

Saving a provider and selecting the global routing target are deliberately separate operations. This prevents adding or rotating a credential from silently changing which model new runs use.

Do not paste API keys into GitHub issues, commits, Actions logs, screenshots intended for public sharing, or repository files. Provider credentials are handled by local credential storage and are not returned as plaintext by the Settings API.

## Supported routing model

The canonical v1 architecture has exactly five permanent logical agents:

- CMO
- Intelligence
- Content
- Creative
- Performance

A full department run has six logical workflow stages and seven model requests:

1. CMO
2. Intelligence
3. Content
4. Creative
5. Performance (5A + 5B under one permanent Performance identity)
6. Final CMO

Final CMO reuses the permanent CMO identity; it is not a sixth agent.

## Custom OpenAI-compatible endpoints

Settings supports configurable OpenAI-compatible providers. HTTPS is required for remote endpoints. Plain HTTP is restricted to validated loopback endpoints such as `127.0.0.1`, `localhost`, or `::1`, which supports local runtimes such as Ollama/vLLM/LiteLLM-style OpenAI-compatible servers without weakening remote transport rules.

## What automated release certification proves

The Windows release pipeline verifies the packaged backend, frontend, Rust desktop shell, installer construction, and installed-app lifecycle. It also performs a deterministic packaged-backend model connection test against a local OpenAI-compatible mock, proving that the frozen backend can execute the same Settings connection-test path used by the desktop UI without requiring a real cloud credential.

The clean-install certification installs the NSIS package into an isolated directory, launches the installed desktop executable, verifies that the packaged backend becomes healthy, and verifies that closing the desktop tears the backend down through the Windows Job Object lifecycle.

## What still requires a real provider credential

Automated CI must not claim that a cloud provider account works for a user. Final live-provider verification requires a real user-supplied credential:

1. Install the standalone app.
2. Enter provider/model/API key in Settings.
3. Run **Test Connection** and confirm `CONNECTED`.
4. Save the provider and global model settings.
5. Execute a real department workflow through CMO → Intelligence → Content → Creative → Performance → Final CMO.

Only that credential-backed run can certify live provider/account/model interoperability for the selected provider.

## Developer setup

The source repository still supports development from source using Python, Node.js/npm, Rust/Tauri tooling, and the repository test suites. Those dependencies are developer requirements only and are not requirements for users of the standalone Windows installer.
