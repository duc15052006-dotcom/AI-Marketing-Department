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

pub fn parse_bootstrap_line(line: &str) -> Result<(String, String, u16), &'static str> {
    let trimmed = line.trim();
    if !trimmed.starts_with("UIAUTH_BOOTSTRAP_V1:") {
        return Err("NOT_A_BOOTSTRAP_FRAME");
    }
    let payload = &trimmed["UIAUTH_BOOTSTRAP_V1:".len()..];
    let parsed: serde_json::Value = serde_json::from_str(payload).map_err(|_| "MALFORMED_BOOTSTRAP_JSON")?;

    let tok = parsed.get("token").and_then(|v| v.as_str()).ok_or("MISSING_TOKEN")?;
    if tok.len() < 32 || tok.len() > 256 || !tok.chars().all(|c| c.is_ascii_graphic()) {
        return Err("INVALID_TOKEN_FORMAT");
    }

    let h = parsed.get("host").and_then(|v| v.as_str()).ok_or("MISSING_HOST")?;
    if h != "127.0.0.1" && h != "localhost" && h != "::1" {
        return Err("FORBIDDEN_HOST");
    }

    let p = parsed.get("port").and_then(|v| v.as_u64()).ok_or("MISSING_PORT")?;
    if p < 1 || p > 65535 {
        return Err("PORT_OUT_OF_RANGE");
    }

    Ok((tok.to_string(), h.to_string(), p as u16))
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
            let mut bootstrap_frames_count = 0usize;

            // Read the single framed bootstrap message from child stdout pipe
            if let Some(stdout) = child.stdout.take() {
                let mut reader = BufReader::new(stdout);
                let mut line = String::new();

                while let Ok(bytes_read) = reader.read_line(&mut line) {
                    if bytes_read == 0 {
                        break;
                    }
                    if bytes_read <= 4096 {
                        let trimmed = line.trim();
                        if trimmed.starts_with("UIAUTH_BOOTSTRAP_V1:") {
                            bootstrap_frames_count += 1;
                            if bootstrap_frames_count == 1 {
                                match parse_bootstrap_line(trimmed) {
                                    Ok((tok, h, p)) => {
                                        token = Some(tok);
                                        default_host = h;
                                        default_port = p;
                                    }
                                    Err(err) => {
                                        eprintln!("Failed to parse bootstrap frame: {}", err);
                                    }
                                }
                            } else {
                                eprintln!("CRITICAL: Duplicate bootstrap frame received. Failing closed.");
                                token = None;
                                break;
                            }
                        }
                    }
                    line.clear();
                    if token.is_some() {
                        break;
                    }
                }

                // Spawn a drain thread for remaining stdout so child is not blocked (PROD-LIFECYCLE-PIPE-DRAIN)
                std::thread::spawn(move || {
                    let mut drain_line = String::new();
                    while let Ok(n) = reader.read_line(&mut drain_line) {
                        if n == 0 {
                            break;
                        }
                        if drain_line.trim().starts_with("UIAUTH_BOOTSTRAP_V1:") {
                            eprintln!("WARNING: Unexpected late bootstrap frame observed on stdout.");
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

pub fn is_allowed_generic_route(method: &str, path: &str) -> bool {
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

pub fn sanitize_material_parameters(params: &serde_json::Value) -> String {
    if let serde_json::Value::Object(map) = params {
        let mut lines = Vec::new();
        for (k, v) in map {
            let k_lower = k.to_lowercase();
            // Redact credentials/secrets
            if k_lower.contains("secret") || k_lower.contains("token") || k_lower.contains("key") || k_lower.contains("password") || k_lower.contains("auth") {
                lines.push(format!("  • {}: [REDACTED SECRET]", k));
                continue;
            }
            let val_str = match v {
                serde_json::Value::String(s) => {
                    if s.len() > 120 {
                        format!("{}...", &s[..120])
                    } else {
                        s.clone()
                    }
                }
                serde_json::Value::Number(n) => n.to_string(),
                serde_json::Value::Bool(b) => b.to_string(),
                serde_json::Value::Null => "null".to_string(),
                _ => {
                    let compact = v.to_string();
                    if compact.len() > 120 {
                        format!("{}...", &compact[..120])
                    } else {
                        compact
                    }
                }
            };
            lines.push(format!("  • {}: {}", k, val_str));
        }
        if lines.is_empty() {
            "  (None)".to_string()
        } else {
            lines.join("\n")
        }
    } else {
        let s = params.to_string();
        if s.len() > 200 {
            format!("{}...", &s[..200])
        } else {
            s
        }
    }
}

pub fn format_approval_confirmation_message(proposal: &serde_json::Value, pending_id: &str) -> String {
    let capability = proposal.get("capability_id").and_then(|v| v.as_str()).unwrap_or("unknown_capability");
    let run_id = proposal.get("run_id").and_then(|v| v.as_str()).unwrap_or("unknown_run");
    let business_id = proposal.get("business_id").and_then(|v| v.as_str()).unwrap_or("default");
    let risk_level = proposal.get("risk_level").and_then(|v| v.as_str()).unwrap_or("HIGH");
    let fingerprint = proposal.get("request_fingerprint").and_then(|v| v.as_str()).unwrap_or("N/A");
    let short_fp = if fingerprint.len() > 16 { &fingerprint[..16] } else { fingerprint };
    let empty_params = serde_json::Value::Object(serde_json::Map::new());
    let params_val = proposal.get("parameters").unwrap_or(&empty_params);
    let params_summary = sanitize_material_parameters(params_val);

    format!(
        "AI Marketing Department — Consequential Action Authorization\n\n\
        A high-risk action requires your explicit human review:\n\n\
        • Proposal ID: {}\n\
        • Capability: {}\n\
        • Risk Level: {}\n\
        • Business Scope: {}\n\
        • Run ID: {}\n\
        • Fingerprint: {}...\n\n\
        Material Action Parameters:\n\
        {}\n\n\
        Do you explicitly authorize this exact consequential action to execute?",
        pending_id, capability, risk_level, business_id, run_id, short_fp, params_summary
    )
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

    // Verify proposal status is PENDING before displaying dialog
    let proposal_status = parsed_proposal.get("status").and_then(|v| v.as_str()).unwrap_or("");
    if proposal_status != "PENDING" {
        return Err(format!("PROPOSAL_NOT_PENDING: Cannot review action with status {}", proposal_status));
    }

    // 3. Format and show native confirmation dialog
    let title = "AI Marketing Department — Consequential Action Approval";
    let message = format_approval_confirmation_message(&parsed_proposal, pending_id);

    let user_confirmed = show_native_confirmation_dialog(title, &message);
    if !user_confirmed {
        return Err("USER_REJECTED_NATIVE_CONFIRMATION".to_string());
    }

    // 4. Submit approval decision to backend
    let approve_path = format!("/api/approvals/{}/approve", pending_id);
    perform_loopback_http_request(&host, port, "POST", &approve_path, &token, Some("{}".to_string()), None)
}

pub fn is_safe_api_path(path: &str) -> bool {
    let clean = path.trim();
    if !clean.starts_with("/api/") {
        return false;
    }
    if clean.contains("://")
        || clean.contains('\\')
        || clean.contains("..")
        || clean.contains('\0')
        || clean.contains('\r')
        || clean.contains('\n')
        || clean.contains(' ')
        || clean.contains("%0d")
        || clean.contains("%0D")
        || clean.contains("%0a")
        || clean.contains("%0A")
        || clean.contains("%5c")
        || clean.contains("%5C")
        || clean.contains("%2e%2e")
        || clean.contains("%2E%2E")
    {
        return false;
    }
    true
}

pub fn parse_bootstrap_stream<R: std::io::BufRead>(reader: &mut R) -> Result<(String, String, u16), &'static str> {
    let mut token: Option<String> = None;
    let mut host = String::new();
    let mut port = 0u16;
    let mut frames_count = 0usize;
    let mut line = String::new();

    while let Ok(bytes_read) = reader.read_line(&mut line) {
        if bytes_read == 0 {
            break;
        }
        if bytes_read <= 4096 {
            let trimmed = line.trim();
            if trimmed.starts_with("UIAUTH_BOOTSTRAP_V1:") {
                frames_count += 1;
                if frames_count > 1 {
                    return Err("DUPLICATE_BOOTSTRAP_FRAME");
                }
                let (tok, h, p) = parse_bootstrap_line(trimmed)?;
                token = Some(tok);
                host = h;
                port = p;
            }
        }
        line.clear();
    }

    if frames_count == 0 {
        return Err("NO_BOOTSTRAP_FRAME");
    }

    if let Some(tok) = token {
        Ok((tok, host, port))
    } else {
        Err("BOOTSTRAP_FAILED")
    }
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
    if !is_safe_api_path(path) {
        return Err("INVALID_PATH: Path traversal, schemes, encoded controls, whitespace, or invalid prefixes are forbidden".to_string());
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_allowed_generic_routes() {
        assert!(is_allowed_generic_route("GET", "/api/health"));
        assert!(is_allowed_generic_route("GET", "/api/system/status"));
        assert!(is_allowed_generic_route("GET", "/api/system/diagnostics"));
        assert!(is_allowed_generic_route("GET", "/api/system/health"));
        assert!(is_allowed_generic_route("GET", "/api/chat/sessions"));
        assert!(is_allowed_generic_route("POST", "/api/chat/sessions/first_turn"));
        assert!(is_allowed_generic_route("POST", "/api/chat/sessions/chat_123/messages"));
        assert!(is_allowed_generic_route("PATCH", "/api/chat/sessions/chat_123"));
        assert!(is_allowed_generic_route("DELETE", "/api/chat/sessions/chat_123"));
        assert!(is_allowed_generic_route("POST", "/api/chat/sessions/chat_123/messages/msg_1/edit"));
        assert!(is_allowed_generic_route("POST", "/api/chat/sessions/chat_123/messages/msg_1/regenerate"));
        assert!(is_allowed_generic_route("POST", "/api/chat/sessions/chat_123/regenerate"));
        assert!(is_allowed_generic_route("POST", "/api/chat/sessions/chat_123/retry"));
        assert!(is_allowed_generic_route("GET", "/api/projects"));
        assert!(is_allowed_generic_route("POST", "/api/projects"));
        assert!(is_allowed_generic_route("PUT", "/api/projects/p1"));
        assert!(is_allowed_generic_route("DELETE", "/api/projects/p1"));
        assert!(is_allowed_generic_route("GET", "/api/workspaces"));
        assert!(is_allowed_generic_route("POST", "/api/workspaces"));
        assert!(is_allowed_generic_route("GET", "/api/approvals"));
        assert!(is_allowed_generic_route("GET", "/api/approvals/pending_appr_xyz"));
        assert!(is_allowed_generic_route("GET", "/api/activity/receipts"));
        assert!(is_allowed_generic_route("GET", "/api/connections"));
        assert!(is_allowed_generic_route("POST", "/api/analytics/import"));
    }

    #[test]
    fn test_denied_unknown_api_routes() {
        assert!(!is_allowed_generic_route("GET", "/api/internal/debug"));
        assert!(!is_allowed_generic_route("POST", "/api/admin/eval"));
        assert!(!is_allowed_generic_route("DELETE", "/api/database/drop"));
        assert!(!is_allowed_generic_route("POST", "/api/system/shutdown"));
        assert!(!is_allowed_generic_route("GET", "/api/v2/unreviewed"));
        assert!(!is_allowed_generic_route("POST", "/api/users/delete_all"));
    }

    #[test]
    fn test_denied_approval_approve_route() {
        assert!(!is_allowed_generic_route("POST", "/api/approvals/pending_appr_123/approve"));
        assert!(!is_allowed_generic_route("GET", "/api/approvals/pending_appr_123/approve"));
    }

    #[test]
    fn test_denied_approval_reject_route() {
        assert!(!is_allowed_generic_route("POST", "/api/approvals/pending_appr_123/reject"));
        assert!(!is_allowed_generic_route("GET", "/api/approvals/pending_appr_123/reject"));
    }

    #[test]
    fn test_denied_approval_create_route() {
        assert!(!is_allowed_generic_route("POST", "/api/approvals/create"));
    }

    #[test]
    fn test_is_safe_api_path_schemes_and_traversal() {
        assert!(is_safe_api_path("/api/chat/sessions"));
        assert!(is_safe_api_path("/api/projects/p123"));
        assert!(!is_safe_api_path("http://evil.com/api/test"));
        assert!(!is_safe_api_path("https://evil.com/api/test"));
        assert!(!is_safe_api_path("//evil.com/api/test"));
        assert!(!is_safe_api_path("/api/../admin"));
        assert!(!is_safe_api_path("/api/..\\admin"));
        assert!(!is_safe_api_path("\\\\server\\share"));
        assert!(!is_safe_api_path("/api/test\0hidden"));
    }

    #[test]
    fn test_is_safe_api_path_raw_and_encoded_crlf() {
        assert!(!is_safe_api_path("/api/chat\r\nHost: evil"));
        assert!(!is_safe_api_path("/api/chat\nInjected: 1"));
        assert!(!is_safe_api_path("/api/chat%0d%0aInjected:1"));
        assert!(!is_safe_api_path("/api/chat%0D%0AInjected:1"));
        assert!(!is_safe_api_path("/api/chat%2e%2e/admin"));
        assert!(!is_safe_api_path("/api/chat%2E%2E/admin"));
        assert!(!is_safe_api_path("/api/chat%5cadmin"));
        assert!(!is_safe_api_path("/api/chat%5Cadmin"));
    }

    #[test]
    fn test_parse_valid_bootstrap_frame() {
        let valid = "UIAUTH_BOOTSTRAP_V1:{\"token\":\"abcdefghijklmnopqrstuvwxyz1234567890\",\"host\":\"127.0.0.1\",\"port\":8765}";
        let res = parse_bootstrap_line(valid);
        assert!(res.is_ok());
        let (tok, host, port) = res.unwrap();
        assert_eq!(tok, "abcdefghijklmnopqrstuvwxyz1234567890");
        assert_eq!(host, "127.0.0.1");
        assert_eq!(port, 8765);
    }

    #[test]
    fn test_parse_malformed_bootstrap_frames() {
        assert_eq!(parse_bootstrap_line("NOT_A_FRAME"), Err("NOT_A_BOOTSTRAP_FRAME"));
        assert_eq!(parse_bootstrap_line("UIAUTH_BOOTSTRAP_V1:{not_json}"), Err("MALFORMED_BOOTSTRAP_JSON"));
        assert_eq!(
            parse_bootstrap_line("UIAUTH_BOOTSTRAP_V1:{\"token\":\"short\",\"host\":\"127.0.0.1\",\"port\":8765}"),
            Err("INVALID_TOKEN_FORMAT")
        );
        assert_eq!(
            parse_bootstrap_line("UIAUTH_BOOTSTRAP_V1:{\"token\":\"abcdefghijklmnopqrstuvwxyz1234567890\",\"host\":\"attacker.com\",\"port\":8765}"),
            Err("FORBIDDEN_HOST")
        );
        assert_eq!(
            parse_bootstrap_line("UIAUTH_BOOTSTRAP_V1:{\"token\":\"abcdefghijklmnopqrstuvwxyz1234567890\",\"host\":\"127.0.0.1\",\"port\":0}"),
            Err("PORT_OUT_OF_RANGE")
        );
        assert_eq!(
            parse_bootstrap_line("UIAUTH_BOOTSTRAP_V1:{\"token\":\"abcdefghijklmnopqrstuvwxyz1234567890\",\"host\":\"127.0.0.1\",\"port\":70000}"),
            Err("PORT_OUT_OF_RANGE")
        );
    }

    #[test]
    fn test_duplicate_bootstrap_stream_rejected() {
        let frame1 = "UIAUTH_BOOTSTRAP_V1:{\"token\":\"abcdefghijklmnopqrstuvwxyz1234567890\",\"host\":\"127.0.0.1\",\"port\":8765}\n";
        let frame2 = "UIAUTH_BOOTSTRAP_V1:{\"token\":\"another_secret_token_1234567890123456\",\"host\":\"127.0.0.1\",\"port\":8765}\n";
        let combined = format!("{}{}", frame1, frame2);
        let mut cursor = std::io::Cursor::new(combined.as_bytes());
        let res = parse_bootstrap_stream(&mut cursor);
        assert_eq!(res, Err("DUPLICATE_BOOTSTRAP_FRAME"));
    }

    #[test]
    fn test_single_bootstrap_stream_accepted() {
        let frame1 = "UIAUTH_BOOTSTRAP_V1:{\"token\":\"abcdefghijklmnopqrstuvwxyz1234567890\",\"host\":\"127.0.0.1\",\"port\":8765}\n";
        let normal_log = "INFO: Server started listening on 127.0.0.1:8765\n";
        let combined = format!("{}{}", frame1, normal_log);
        let mut cursor = std::io::Cursor::new(combined.as_bytes());
        let res = parse_bootstrap_stream(&mut cursor);
        assert!(res.is_ok());
        let (tok, host, port) = res.unwrap();
        assert_eq!(tok, "abcdefghijklmnopqrstuvwxyz1234567890");
        assert_eq!(host, "127.0.0.1");
        assert_eq!(port, 8765);
    }

    #[test]
    fn test_backend_process_state_debug_redaction() {
        let state = BackendProcessState {
            child: Mutex::new(None),
            auth_token: Mutex::new(Some("SUPER_SECRET_TOKEN_1234567890".to_string())),
            api_host: Mutex::new("127.0.0.1".to_string()),
            api_port: Mutex::new(8765),
        };
        let debug_str = format!("{:?}", state);
        assert!(debug_str.contains("[REDACTED]"));
        assert!(!debug_str.contains("SUPER_SECRET_TOKEN_1234567890"));
    }

    #[test]
    fn test_sanitize_material_parameters_redacts_secrets() {
        let mut map = serde_json::Map::new();
        map.insert("platform".to_string(), serde_json::Value::String("facebook".to_string()));
        map.insert("content".to_string(), serde_json::Value::String("Launch post text".to_string()));
        map.insert("api_key".to_string(), serde_json::Value::String("secret_key_12345".to_string()));
        map.insert("auth_token".to_string(), serde_json::Value::String("bearer_xyz".to_string()));
        map.insert("password".to_string(), serde_json::Value::String("p@ss123".to_string()));

        let rendered = sanitize_material_parameters(&serde_json::Value::Object(map));
        assert!(rendered.contains("platform: facebook"));
        assert!(rendered.contains("content: Launch post text"));
        assert!(rendered.contains("[REDACTED SECRET]"));
        assert!(!rendered.contains("secret_key_12345"));
        assert!(!rendered.contains("bearer_xyz"));
        assert!(!rendered.contains("p@ss123"));
    }

    #[test]
    fn test_format_approval_confirmation_message_contains_server_fields() {
        let mut proposal = serde_json::Map::new();
        proposal.insert("capability_id".to_string(), serde_json::Value::String("social_publishing".to_string()));
        proposal.insert("run_id".to_string(), serde_json::Value::String("RUN-123".to_string()));
        proposal.insert("business_id".to_string(), serde_json::Value::String("BIZ-01".to_string()));
        proposal.insert("risk_level".to_string(), serde_json::Value::String("HIGH".to_string()));
        proposal.insert("request_fingerprint".to_string(), serde_json::Value::String("abc123def45678901234".to_string()));

        let mut params = serde_json::Map::new();
        params.insert("platform".to_string(), serde_json::Value::String("linkedin".to_string()));
        params.insert("summary".to_string(), serde_json::Value::String("Q3 Report Post".to_string()));
        proposal.insert("parameters".to_string(), serde_json::Value::Object(params));

        let msg = format_approval_confirmation_message(&serde_json::Value::Object(proposal), "pending_appr_999");
        assert!(msg.contains("Proposal ID: pending_appr_999"));
        assert!(msg.contains("Capability: social_publishing"));
        assert!(msg.contains("Run ID: RUN-123"));
        assert!(msg.contains("Business Scope: BIZ-01"));
        assert!(msg.contains("platform: linkedin"));
        assert!(msg.contains("summary: Q3 Report Post"));
        assert!(msg.contains("Do you explicitly authorize this exact consequential action to execute?"));
    }
}
