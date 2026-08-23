// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::collections::HashMap;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::TcpStream;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::Manager;

#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;

pub struct BackendProcessState {
    pub child: Mutex<Option<Child>>,
    pub auth_token: Mutex<Option<String>>,
    pub api_host: Mutex<String>,
    pub api_port: Mutex<u16>,
}

impl std::fmt::Debug for BackendProcessState {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("BackendProcessState")
            .field("child", &"<Child Process>")
            .field("auth_token", &"[REDACTED]")
            .field("api_host", &self.api_host)
            .field("api_port", &self.api_port)
            .finish()
    }
}

#[derive(serde::Serialize, serde::Deserialize, Debug)]
pub struct ApiRequestArgs {
    pub method: String,
    pub path: String,
    pub body: Option<String>,
    pub headers: Option<HashMap<String, String>>,
}

#[derive(serde::Serialize, serde::Deserialize, Debug)]
pub struct ReviewApprovalArgs {
    pub pending_id: String,
}

#[derive(serde::Serialize, serde::Deserialize, Debug)]
pub struct ApiResponse {
    pub status: u16,
    pub headers: HashMap<String, String>,
    pub body: String,
}

const MAX_REQUEST_BODY_BYTES: usize = 10 * 1024 * 1024; // 10MB
const MAX_RESPONSE_BODY_BYTES: usize = 50 * 1024 * 1024; // 50MB

fn is_backend_healthy(host: &str, port: u16) -> bool {
    let addr = format!("{}:{}", host, port);
    if let Ok(_stream) = TcpStream::connect_timeout(
        &addr.parse().unwrap_or_else(|_| "127.0.0.1:8765".parse().unwrap()),
        Duration::from_millis(200),
    ) {
        true
    } else {
        false
    }
}

fn find_project_root() -> PathBuf {
    // 1. Check fixed primary workspace directory
    let primary = PathBuf::from(r"C:\AI-Marketing-Department");
    if primary.join("app_api").join("server.py").is_file() {
        return primary;
    }

    // 2. Check current working directory
    if let Ok(cwd) = std::env::current_dir() {
        if cwd.join("app_api").join("server.py").is_file() {
            return cwd;
        }
        if let Some(parent) = cwd.parent() {
            if parent.join("app_api").join("server.py").is_file() {
                return parent.to_path_buf();
            }
        }
    }

    // 3. Check exe directory and walk up
    if let Ok(exe) = std::env::current_exe() {
        let mut cur = exe.parent();
        while let Some(dir) = cur {
            if dir.join("app_api").join("server.py").is_file() {
                return dir.to_path_buf();
            }
            cur = dir.parent();
        }
    }

    primary
}

fn spawn_backend_and_bootstrap() -> (Option<Child>, Option<String>, String, u16) {
    let root_dir = find_project_root();
    let server_script = root_dir.join("app_api").join("server.py");

    let mut default_host = "127.0.0.1".to_string();
    let mut default_port = 8765u16;

    if is_backend_healthy(&default_host, default_port) {
        println!("Backend already running and healthy on {}:{}", default_host, default_port);
        let existing_token = std::env::var("APP_BACKEND_BEARER_DEV").ok();
        return (None, existing_token, default_host, default_port);
    }

    println!("Starting backend process from: {:?}", root_dir);

    let mut cmd = Command::new("python");
    cmd.arg(&server_script)
        .arg("--emit-bootstrap")
        .current_dir(&root_dir)
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit());

    #[cfg(target_os = "windows")]
    {
        const CREATE_NO_WINDOW: u32 = 0x08000000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    match cmd.spawn() {
        Ok(mut child) => {
            println!("Spawned backend process with PID: {}", child.id());

            let mut token: Option<String> = None;

            // Read the single framed bootstrap message from child stdout pipe
            if let Some(stdout) = child.stdout.take() {
                let mut reader = BufReader::new(stdout);
                let mut line = String::new();
                if let Ok(bytes_read) = reader.read_line(&mut line) {
                    if bytes_read > 0 && bytes_read <= 4096 {
                        let trimmed = line.trim();
                        if let Some(payload) = trimmed.strip_prefix("UIAUTH_BOOTSTRAP_V1:") {
                            if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(payload) {
                                if let Some(tok) = parsed.get("token").and_then(|v| v.as_str()) {
                                    if tok.len() >= 32 && tok.len() <= 256 && tok.chars().all(|c| c.is_ascii_graphic()) {
                                        token = Some(tok.to_string());
                                    }
                                }
                                if let Some(h) = parsed.get("host").and_then(|v| v.as_str()) {
                                    if h == "127.0.0.1" || h == "localhost" || h == "::1" {
                                        default_host = h.to_string();
                                    }
                                }
                                if let Some(p) = parsed.get("port").and_then(|v| v.as_u64()) {
                                    if p >= 1 && p <= 65535 {
                                        default_port = p as u16;
                                    }
                                }
                            }
                        }
                    }
                }
                // Spawn a drain thread for remaining stdout so child is not blocked (PROD-LIFECYCLE-PIPE-DRAIN)
                std::thread::spawn(move || {
                    let mut drain_line = String::new();
                    while let Ok(n) = reader.read_line(&mut drain_line) {
                        if n == 0 {
                            break;
                        }
                        drain_line.clear();
                    }
                });
            }

            // Wait up to 6 seconds for backend to become responsive
            let start = Instant::now();
            while start.elapsed() < Duration::from_secs(6) {
                if is_backend_healthy(&default_host, default_port) {
                    println!("Backend is ready and listening on {}:{}", default_host, default_port);
                    break;
                }
                std::thread::sleep(Duration::from_millis(100));
            }

            (Some(child), token, default_host, default_port)
        }
        Err(e) => {
            eprintln!("Failed to spawn backend python process: {}", e);
            (None, None, default_host, default_port)
        }
    }
}

fn perform_loopback_http_request(
    host: &str,
    port: u16,
    method: &str,
    path: &str,
    token: &str,
    body: Option<String>,
    custom_headers: Option<HashMap<String, String>>,
) -> Result<ApiResponse, String> {
    let addr = format!("{}:{}", host, port);
    let mut stream = TcpStream::connect_timeout(
        &addr.parse().map_err(|e| format!("INVALID_ADDRESS: {}", e))?,
        Duration::from_secs(5),
    )
    .map_err(|e| format!("CONNECTION_FAILED: {}", e))?;

    stream
        .set_read_timeout(Some(Duration::from_secs(30)))
        .map_err(|e| format!("TIMEOUT_SET_FAILED: {}", e))?;
    stream
        .set_write_timeout(Some(Duration::from_secs(10)))
        .map_err(|e| format!("TIMEOUT_SET_FAILED: {}", e))?;

    let body_bytes = body.as_deref().unwrap_or("").as_bytes();
    let content_length = body_bytes.len();

    let mut request_raw = format!(
        "{} {} HTTP/1.1\r\nHost: {}:{}\r\nAuthorization: Bearer {}\r\nConnection: close\r\nContent-Length: {}\r\n",
        method, path, host, port, token, content_length
    );

    let mut has_content_type = false;
    if let Some(headers) = custom_headers {
        for (k, v) in headers {
            let k_lower = k.to_lowercase();
            // Disallow caller from tampering with sensitive transport headers
            if k_lower == "authorization" || k_lower == "host" || k_lower == "content-length" || k_lower == "connection" || k_lower == "transfer-encoding" {
                continue;
            }
            if k_lower == "content-type" {
                has_content_type = true;
            }
            request_raw.push_str(&format!("{}: {}\r\n", k, v));
        }
    }

    if !has_content_type && (method == "POST" || method == "PUT" || method == "PATCH") {
        request_raw.push_str("Content-Type: application/json\r\n");
    }

    request_raw.push_str("\r\n");

    stream
        .write_all(request_raw.as_bytes())
        .map_err(|e| format!("WRITE_FAILED: {}", e))?;

    if !body_bytes.is_empty() {
        stream
            .write_all(body_bytes)
            .map_err(|e| format!("BODY_WRITE_FAILED: {}", e))?;
    }

    stream.flush().map_err(|e| format!("FLUSH_FAILED: {}", e))?;

    // Read response with bound
    let mut response_bytes = Vec::new();
    let mut buffer = [0u8; 8192];
    loop {
        match stream.read(&mut buffer) {
            Ok(0) => break,
            Ok(n) => {
                response_bytes.extend_from_slice(&buffer[..n]);
                if response_bytes.len() > MAX_RESPONSE_BODY_BYTES {
                    return Err("RESPONSE_TOO_LARGE: Response body exceeded maximum allowed limit".to_string());
                }
            }
            Err(e) => {
                if response_bytes.is_empty() {
                    return Err(format!("READ_FAILED: {}", e));
                }
                break;
            }
        }
    }

    let response_str = String::from_utf8_lossy(&response_bytes);
    let (header_part, body_part) = match response_str.find("\r\n\r\n") {
        Some(idx) => (&response_str[..idx], &response_str[idx + 4..]),
        None => match response_str.find("\n\n") {
            Some(idx) => (&response_str[..idx], &response_str[idx + 2..]),
            None => return Err("MALFORMED_HTTP_RESPONSE".to_string()),
        },
    };

    let mut lines = header_part.lines();
    let status_line = lines.next().ok_or_else(|| "EMPTY_STATUS_LINE".to_string())?;
    let status_parts: Vec<&str> = status_line.split_whitespace().collect();
    if status_parts.len() < 2 {
        return Err(format!("INVALID_STATUS_LINE: {}", status_line));
    }
    let status_code: u16 = status_parts[1]
        .parse()
        .map_err(|_| format!("INVALID_STATUS_CODE: {}", status_parts[1]))?;

    let mut response_headers = HashMap::new();
    for line in lines {
        if let Some((k, v)) = line.split_once(':') {
            response_headers.insert(k.trim().to_lowercase(), v.trim().to_string());
        }
    }

    Ok(ApiResponse {
        status: status_code,
        headers: response_headers,
        body: body_part.to_string(),
    })
}

#[cfg(target_os = "windows")]
fn show_native_confirmation_dialog(title: &str, message: &str) -> bool {
    use std::ffi::OsStr;
    use std::os::windows::ffi::OsStrExt;

    let wide_title: Vec<u16> = OsStr::new(title).encode_wide().chain(std::iter::once(0)).collect();
    let wide_msg: Vec<u16> = OsStr::new(message).encode_wide().chain(std::iter::once(0)).collect();

    extern "system" {
        fn MessageBoxW(hwnd: *mut std::ffi::c_void, text: *const u16, caption: *const u16, utype: u32) -> i32;
    }

    const MB_YESNO: u32 = 0x00000004;
    const MB_ICONWARNING: u32 = 0x00000030;
    const MB_DEFBUTTON2: u32 = 0x00000100;
    const IDYES: i32 = 6;

    let result = unsafe {
        MessageBoxW(
            std::ptr::null_mut(),
            wide_msg.as_ptr(),
            wide_title.as_ptr(),
            MB_YESNO | MB_ICONWARNING | MB_DEFBUTTON2,
        )
    };

    result == IDYES
}

#[cfg(not(target_os = "windows"))]
fn show_native_confirmation_dialog(_title: &str, _message: &str) -> bool {
    false
}

fn is_allowed_generic_route(method: &str, path: &str) -> bool {
    // Approval decision routes are strictly forbidden on generic proxy
    if path.contains("/approve") || path.contains("/reject") || path == "/api/approvals/create" {
        return false;
    }

    match (method, path) {
        ("GET", "/api/health") => true,
        ("GET", "/api/system/status") => true,
        ("GET", "/api/system/diagnostics") => true,
        ("GET", "/api/system/health") => true,
        ("GET", "/api/chat/sessions") => true,
        ("POST", "/api/chat/sessions/first_turn") => true,
        ("GET", "/api/projects") => true,
        ("POST", "/api/projects") => true,
        ("GET", "/api/workspaces") => true,
        ("POST", "/api/workspaces") => true,
        ("GET", "/api/approvals") => true,
        ("GET", "/api/activity/receipts") => true,
        ("GET", "/api/connections") => true,
        ("POST", "/api/analytics/import") => true,
        _ => {
            // Prefix-based UI operations
            if method == "GET" && path.starts_with("/api/chat/sessions/") {
                return true;
            }
            if (method == "PATCH" || method == "DELETE") && path.starts_with("/api/chat/sessions/") {
                return true;
            }
            if method == "POST" && path.starts_with("/api/chat/sessions/") {
                return path.ends_with("/messages")
                    || (path.contains("/messages/") && (path.ends_with("/edit") || path.ends_with("/regenerate")))
                    || path.ends_with("/regenerate")
                    || path.ends_with("/retry");
            }
            if (method == "GET" || method == "PUT" || method == "DELETE") && path.starts_with("/api/projects/") {
                return true;
            }
            if method == "GET" && path.starts_with("/api/workspaces/") {
                return true;
            }
            if method == "GET" && path.starts_with("/api/approvals/pending_appr_") {
                return true;
            }
            if method == "GET" && path.starts_with("/api/activity/receipts/") {
                return true;
            }
            false
        }
    }
}

#[tauri::command]
async fn review_pending_approval(
    state: tauri::State<'_, BackendProcessState>,
    args: ReviewApprovalArgs,
) -> Result<ApiResponse, String> {
    let pending_id = args.pending_id.trim();

    // 1. Validate pending_id format
    if !pending_id.starts_with("pending_appr_") || pending_id.len() > 80 {
        return Err("INVALID_PENDING_APPROVAL_ID: Format must be pending_appr_<id>".to_string());
    }
    for ch in pending_id.chars() {
        if !ch.is_ascii_alphanumeric() && ch != '_' && ch != '-' {
            return Err("INVALID_PENDING_APPROVAL_ID: Contains illegal characters".to_string());
        }
    }

    let (token, host, port) = {
        let guard_tok = state.auth_token.lock().map_err(|_| "MUTEX_POISONED")?;
        let tok = guard_tok.clone().ok_or_else(|| "BACKEND_UNAUTHENTICATED".to_string())?;
        let guard_h = state.api_host.lock().map_err(|_| "MUTEX_POISONED")?;
        let guard_p = state.api_port.lock().map_err(|_| "MUTEX_POISONED")?;
        (tok, guard_h.clone(), *guard_p)
    };

    // 2. Fetch authoritative proposal from backend using native bearer
    let fetch_path = format!("/api/approvals/{}", pending_id);
    let proposal_res = perform_loopback_http_request(&host, port, "GET", &fetch_path, &token, None, None)?;

    if proposal_res.status != 200 {
        return Err(format!("PROPOSAL_NOT_FOUND: Backend returned status {}", proposal_res.status));
    }

    let parsed_proposal: serde_json::Value = serde_json::from_str(&proposal_res.body)
        .map_err(|e| format!("MALFORMED_PROPOSAL_JSON: {}", e))?;

    let capability = parsed_proposal.get("capability_id").and_then(|v| v.as_str()).unwrap_or("unknown_capability");
    let summary = parsed_proposal.get("action_summary").and_then(|v| v.as_str())
        .or_else(|| parsed_proposal.get("parameters").and_then(|p| p.get("content").and_then(|c| c.as_str())))
        .unwrap_or("(No description)");
    let run_id = parsed_proposal.get("run_id").and_then(|v| v.as_str()).unwrap_or("unknown_run");

    // 3. Show native confirmation dialog
    let title = "AI Marketing Department — Consequential Action Approval";
    let message = format!(
        "A high-risk action requires your explicit human authorization:\n\n\
        Capability: {}\n\
        Summary: {}\n\
        Run ID: {}\n\
        Proposal ID: {}\n\n\
        Do you explicitly authorize this action to proceed?",
        capability, summary, run_id, pending_id
    );

    let user_confirmed = show_native_confirmation_dialog(title, &message);
    if !user_confirmed {
        return Err("USER_REJECTED_NATIVE_CONFIRMATION".to_string());
    }

    // 4. Submit approval decision to backend
    let approve_path = format!("/api/approvals/{}/approve", pending_id);
    perform_loopback_http_request(&host, port, "POST", &approve_path, &token, Some("{}".to_string()), None)
}

#[tauri::command]
async fn api_request(
    state: tauri::State<'_, BackendProcessState>,
    args: ApiRequestArgs,
) -> Result<ApiResponse, String> {
    let method = args.method.trim().to_uppercase();
    let path = args.path.trim();

    // 1. Strict Method Whitelist
    if !matches!(method.as_str(), "GET" | "POST" | "PUT" | "DELETE" | "PATCH" | "OPTIONS") {
        return Err("INVALID_HTTP_METHOD: Allowed methods are GET, POST, PUT, DELETE, PATCH, OPTIONS".to_string());
    }

    // 2. Strict Path & Scheme Validation (Prevents SSRF, arbitrary URLs, CRLF, and path traversal)
    if !path.starts_with("/api/") {
        return Err("FORBIDDEN_PATH: Request path must strictly begin with '/api/'".to_string());
    }
    if path.contains("://") || path.contains('\\') || path.contains("..") || path.contains('\0')
        || path.contains('\r') || path.contains('\n') || path.contains(' ')
        || path.contains("%0d") || path.contains("%0D") || path.contains("%0a") || path.contains("%0A")
        || path.contains("%5c") || path.contains("%5C") || path.contains("%2e%2e") || path.contains("%2E%2E") {
        return Err("INVALID_PATH_CHARACTERS: Path traversal, schemes, encoded controls, and backslashes are forbidden".to_string());
    }

    // 3. Approval route protection
    if path.contains("/approve") || path.contains("/reject") || path == "/api/approvals/create" {
        return Err("NATIVE_APPROVAL_ROUTE_REQUIRES_HUMAN_GESTURE: Approval decisions cannot be submitted via generic proxy. Use review_pending_approval.".to_string());
    }

    // 4. Route Allowlist Policy
    if !is_allowed_generic_route(&method, path) {
        return Err(format!("ROUTE_NOT_PERMITTED_ON_GENERIC_PROXY: Method {} on path {} is not permitted", method, path));
    }

    // 5. Body length bound (max 10MB)
    if let Some(ref b) = args.body {
        if b.len() > MAX_REQUEST_BODY_BYTES {
            return Err("REQUEST_TOO_LARGE: Request payload exceeds 10MB limit".to_string());
        }
    }

    // 6. Header sanitization (reject CRLF injection in headers)
    if let Some(ref headers) = args.headers {
        for (k, v) in headers {
            if k.contains('\r') || k.contains('\n') || v.contains('\r') || v.contains('\n') {
                return Err("INVALID_HEADER_CHARACTERS: CRLF injection detected in headers".to_string());
            }
        }
    }

    // 7. Acquire Token & Endpoint from State
    let token = {
        let guard = state.auth_token.lock().map_err(|_| "MUTEX_POISONED")?;
        guard.clone().ok_or_else(|| "BACKEND_UNAUTHENTICATED: No active session token available".to_string())?
    };
    let host = {
        let guard = state.api_host.lock().map_err(|_| "MUTEX_POISONED")?;
        guard.clone()
    };
    let port = {
        let guard = state.api_port.lock().map_err(|_| "MUTEX_POISONED")?;
        *guard
    };

    // 8. Perform Loopback HTTP/1.1 Request with native Authorization header
    perform_loopback_http_request(&host, port, &method, path, &token, args.body, args.headers)
}

fn main() {
    let (child_process, auth_token, api_host, api_port) = spawn_backend_and_bootstrap();

    let app = tauri::Builder::default()
        .manage(BackendProcessState {
            child: Mutex::new(child_process),
            auth_token: Mutex::new(auth_token),
            api_host: Mutex::new(api_host),
            api_port: Mutex::new(api_port),
        })
        .invoke_handler(tauri::generate_handler![api_request, review_pending_approval])
        .build(tauri::generate_context!())
        .expect("error while building AI Marketing Department desktop application");

    app.run(|app_handle, event| {
        if let tauri::RunEvent::Exit = event {
            // Clean up spawned backend on exit
            if let Some(state) = app_handle.try_state::<BackendProcessState>() {
                if let Ok(mut lock) = state.child.lock() {
                    if let Some(mut child) = lock.take() {
                        println!("Terminating child backend process PID: {}", child.id());
                        let _ = child.kill();
                        let _ = child.wait();
                    }
                }
            }
        }
    });
}
