// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::collections::HashMap;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::TcpStream;
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::Manager;

pub struct BackendProcessState {
    pub child_pid: Mutex<Option<u32>>,
    #[cfg(target_os = "windows")]
    pub process_handle: Mutex<Option<usize>>,
    pub job: Mutex<Option<job_object::JobObjectHandle>>,
    pub auth_token: Mutex<Option<String>>,
    pub api_host: Mutex<String>,
    pub api_port: Mutex<u16>,
}

#[cfg(target_os = "windows")]
pub mod job_object {
    use std::ffi::{c_void, OsStr};
    use std::fs::File;
    use std::os::windows::ffi::OsStrExt;
    use std::os::windows::io::{AsRawHandle, FromRawHandle, RawHandle};
    use std::path::Path;
    use std::process::Child;

    pub type HANDLE = *mut c_void;
    pub type BOOL = i32;
    pub type DWORD = u32;

    pub const JOB_OBJECT_EXTENDED_LIMIT_INFORMATION: u32 = 9;
    pub const JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: DWORD = 0x00002000;
    pub const CREATE_SUSPENDED: DWORD = 0x00000004;
    pub const CREATE_NO_WINDOW: DWORD = 0x08000000;
    pub const STARTF_USESTDHANDLES: DWORD = 0x00000100;
    pub const HANDLE_FLAG_INHERIT: DWORD = 0x00000001;

    #[repr(C)]
    pub struct SECURITY_ATTRIBUTES {
        pub n_length: DWORD,
        pub lp_security_descriptor: *mut c_void,
        pub b_inherit_handle: BOOL,
    }

    #[repr(C)]
    pub struct STARTUPINFOW {
        pub cb: DWORD,
        pub lp_reserved: *mut u16,
        pub lp_desktop: *mut u16,
        pub lp_title: *mut u16,
        pub dw_x: DWORD,
        pub dw_y: DWORD,
        pub dw_x_size: DWORD,
        pub dw_y_size: DWORD,
        pub dw_x_count_chars: DWORD,
        pub dw_y_count_chars: DWORD,
        pub dw_fill_attribute: DWORD,
        pub dw_flags: DWORD,
        pub w_show_window: u16,
        pub cb_reserved2: u16,
        pub lp_reserved2: *mut u8,
        pub h_std_input: HANDLE,
        pub h_std_output: HANDLE,
        pub h_std_error: HANDLE,
    }

    #[repr(C)]
    pub struct PROCESS_INFORMATION {
        pub h_process: HANDLE,
        pub h_thread: HANDLE,
        pub dw_process_id: DWORD,
        pub dw_thread_id: DWORD,
    }

    #[repr(C)]
    pub struct IO_COUNTERS {
        pub read_operation_count: u64,
        pub write_operation_count: u64,
        pub other_operation_count: u64,
        pub read_transfer_count: u64,
        pub write_transfer_count: u64,
        pub other_transfer_count: u64,
    }

    #[repr(C)]
    pub struct JOBOBJECT_BASIC_LIMIT_INFORMATION {
        pub per_process_user_time_limit: i64,
        pub per_job_user_time_limit: i64,
        pub limit_flags: DWORD,
        pub minimum_working_set_size: usize,
        pub maximum_working_set_size: usize,
        pub active_process_limit: DWORD,
        pub affinity: usize,
        pub priority_class: DWORD,
        pub scheduling_class: DWORD,
    }

    #[repr(C)]
    pub struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION {
        pub basic_limit_information: JOBOBJECT_BASIC_LIMIT_INFORMATION,
        pub io_info: IO_COUNTERS,
        pub process_memory_limit: usize,
        pub job_memory_limit: usize,
        pub peak_process_memory_limit: usize,
        pub peak_job_memory_limit: usize,
    }

    extern "system" {
        pub fn CreateJobObjectW(lp_job_attributes: *mut c_void, lp_name: *const u16) -> HANDLE;
        pub fn SetInformationJobObject(
            h_job: HANDLE,
            job_object_information_class: u32,
            lp_job_object_information: *const c_void,
            cb_job_object_information_length: DWORD,
        ) -> BOOL;
        pub fn AssignProcessToJobObject(h_job: HANDLE, h_process: HANDLE) -> BOOL;
        pub fn TerminateJobObject(h_job: HANDLE, u_exit_code: u32) -> BOOL;
        pub fn TerminateProcess(h_process: HANDLE, u_exit_code: u32) -> BOOL;
        pub fn ResumeThread(h_thread: HANDLE) -> DWORD;
        pub fn CloseHandle(h_object: HANDLE) -> BOOL;
        pub fn CreatePipe(h_read_pipe: *mut HANDLE, h_write_pipe: *mut HANDLE, lp_pipe_attributes: *mut SECURITY_ATTRIBUTES, n_size: DWORD) -> BOOL;
        pub fn SetHandleInformation(h_object: HANDLE, dw_mask: DWORD, dw_flags: DWORD) -> BOOL;
        pub fn CreateProcessW(
            lp_application_name: *const u16,
            lp_command_line: *mut u16,
            lp_process_attributes: *mut SECURITY_ATTRIBUTES,
            lp_thread_attributes: *mut SECURITY_ATTRIBUTES,
            b_inherit_handles: BOOL,
            dw_creation_flags: DWORD,
            lp_environment: *mut c_void,
            lp_current_directory: *const u16,
            lp_startup_info: *mut STARTUPINFOW,
            lp_process_information: *mut PROCESS_INFORMATION,
        ) -> BOOL;
    }

    pub struct JobObjectHandle {
        pub handle: HANDLE,
    }

    unsafe impl Send for JobObjectHandle {}
    unsafe impl Sync for JobObjectHandle {}

    impl JobObjectHandle {
        pub fn new() -> Option<Self> {
            unsafe {
                let handle = CreateJobObjectW(std::ptr::null_mut(), std::ptr::null());
                if handle.is_null() {
                    return None;
                }

                let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
                info.basic_limit_information.limit_flags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;

                let ok = SetInformationJobObject(
                    handle,
                    JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                    &info as *const _ as *const c_void,
                    std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as DWORD,
                );

                if ok == 0 {
                    CloseHandle(handle);
                    return None;
                }

                Some(JobObjectHandle { handle })
            }
        }

        pub fn assign_raw_process(&self, process_handle: HANDLE) -> bool {
            unsafe {
                AssignProcessToJobObject(self.handle, process_handle) != 0
            }
        }

        pub fn assign_child(&self, child: &Child) -> bool {
            unsafe {
                let process_handle = child.as_raw_handle() as HANDLE;
                AssignProcessToJobObject(self.handle, process_handle) != 0
            }
        }

        pub fn terminate(&self, exit_code: u32) -> bool {
            unsafe {
                if !self.handle.is_null() {
                    TerminateJobObject(self.handle, exit_code) != 0
                } else {
                    false
                }
            }
        }
    }

    impl Drop for JobObjectHandle {
        fn drop(&mut self) {
            unsafe {
                if !self.handle.is_null() {
                    CloseHandle(self.handle);
                }
            }
        }
    }

    pub struct SuspendedSpawnResult {
        pub child_pid: u32,
        pub stdout_file: File,
        pub stderr_file: File,
        pub process_handle: HANDLE,
    }

    pub fn resolve_python_executable() -> String {
        if let Ok(p) = std::env::var("PYTHON_PATH") {
            if Path::new(&p).exists() {
                return p;
            }
        }
        if let Ok(local_app_data) = std::env::var("LOCALAPPDATA") {
            let py_core = Path::new(&local_app_data).join("Python").join("pythoncore-3.14-64").join("python.exe");
            if py_core.exists() {
                return py_core.to_string_lossy().to_string();
            }
            let py_programs = Path::new(&local_app_data).join("Programs").join("Python");
            if py_programs.exists() {
                if let Ok(entries) = std::fs::read_dir(py_programs) {
                    for entry in entries.flatten() {
                        let exe = entry.path().join("python.exe");
                        if exe.exists() {
                            return exe.to_string_lossy().to_string();
                        }
                    }
                }
            }
        }
        if let Ok(path_var) = std::env::var("PATH") {
            for dir in std::env::split_paths(&path_var) {
                if dir.to_string_lossy().to_lowercase().contains("windowsapps") {
                    continue;
                }
                let candidate = dir.join("python.exe");
                if candidate.exists() {
                    return candidate.to_string_lossy().to_string();
                }
            }
        }
        "python".to_string()
    }

    /// Spawns python process suspended, assigns it to Job Object BEFORE execution begins, and resumes thread.
    /// Eliminates PROD-LIFECYCLE-JOB-ASSIGNMENT-RACE-01 completely.
    pub fn spawn_in_job_suspended(
        job: &JobObjectHandle,
        script_path: &Path,
        work_dir: &Path,
    ) -> Result<SuspendedSpawnResult, &'static str> {
        let py_exe = resolve_python_executable();
        let cmd_str = format!("\"{}\" \"{}\" --emit-bootstrap", py_exe, script_path.display());
        spawn_raw_cmd_in_job_suspended(job, &cmd_str, work_dir)
    }

    pub fn spawn_raw_cmd_in_job_suspended(
        job: &JobObjectHandle,
        cmd_str: &str,
        work_dir: &Path,
    ) -> Result<SuspendedSpawnResult, &'static str> {
        unsafe {
            // 1. Create Pipes with Inheritable Write Ends
            let mut sa: SECURITY_ATTRIBUTES = std::mem::zeroed();
            sa.n_length = std::mem::size_of::<SECURITY_ATTRIBUTES>() as DWORD;
            sa.b_inherit_handle = 1;

            let mut stdout_read: HANDLE = std::ptr::null_mut();
            let mut stdout_write: HANDLE = std::ptr::null_mut();
            if CreatePipe(&mut stdout_read, &mut stdout_write, &mut sa, 0) == 0 {
                return Err("FAILED_CREATE_STDOUT_PIPE");
            }
            SetHandleInformation(stdout_read, HANDLE_FLAG_INHERIT, 0);

            let mut stderr_read: HANDLE = std::ptr::null_mut();
            let mut stderr_write: HANDLE = std::ptr::null_mut();
            if CreatePipe(&mut stderr_read, &mut stderr_write, &mut sa, 0) == 0 {
                CloseHandle(stdout_read);
                CloseHandle(stdout_write);
                return Err("FAILED_CREATE_STDERR_PIPE");
            }
            SetHandleInformation(stderr_read, HANDLE_FLAG_INHERIT, 0);

            // 2. Prepare Command Line with structured argument quoting
            let mut cmd_wide: Vec<u16> = OsStr::new(cmd_str).encode_wide().chain(std::iter::once(0)).collect();
            let work_dir_wide: Vec<u16> = OsStr::new(work_dir.as_os_str()).encode_wide().chain(std::iter::once(0)).collect();

            let mut si: STARTUPINFOW = std::mem::zeroed();
            si.cb = std::mem::size_of::<STARTUPINFOW>() as DWORD;
            si.dw_flags = STARTF_USESTDHANDLES;
            si.h_std_input = std::ptr::null_mut();
            si.h_std_output = stdout_write;
            si.h_std_error = stderr_write;

            let mut pi: PROCESS_INFORMATION = std::mem::zeroed();

            // 3. Create Process SUSPENDED
            let created = CreateProcessW(
                std::ptr::null(),
                cmd_wide.as_mut_ptr(),
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                1, // Inherit handles
                CREATE_SUSPENDED | CREATE_NO_WINDOW,
                std::ptr::null_mut(),
                work_dir_wide.as_ptr(),
                &mut si,
                &mut pi,
            );

            // Close write handles in parent so EOF is triggered on child exit
            CloseHandle(stdout_write);
            CloseHandle(stderr_write);

            if created == 0 {
                CloseHandle(stdout_read);
                CloseHandle(stderr_read);
                return Err("CREATE_PROCESS_FAILED");
            }

            // 4. Assign to Job Object BEFORE thread executes any user instructions
            let assigned = job.assign_raw_process(pi.h_process);
            if !assigned {
                eprintln!("CRITICAL: AssignProcessToJobObject failed. Terminating unmanaged child immediately.");
                TerminateProcess(pi.h_process, 1);
                CloseHandle(pi.h_thread);
                CloseHandle(pi.h_process);
                CloseHandle(stdout_read);
                CloseHandle(stderr_read);
                return Err("ASSIGN_JOB_FAILED");
            }

            // 5. Resume main thread now that process is strictly within Job Object boundary
            ResumeThread(pi.h_thread);
            CloseHandle(pi.h_thread);

            let stdout_file = File::from_raw_handle(stdout_read as RawHandle);
            let stderr_file = File::from_raw_handle(stderr_read as RawHandle);

            Ok(SuspendedSpawnResult {
                child_pid: pi.dw_process_id,
                stdout_file,
                stderr_file,
                process_handle: pi.h_process,
            })
        }
    }
}

#[cfg(not(target_os = "windows"))]
pub mod job_object {
    use std::process::Child;
    pub struct JobObjectHandle;
    impl JobObjectHandle {
        pub fn new() -> Option<Self> { Some(JobObjectHandle) }
        pub fn assign_child(&self, _child: &Child) -> bool { true }
        pub fn terminate(&self, _exit_code: u32) -> bool { true }
    }
}

impl std::fmt::Debug for BackendProcessState {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("BackendProcessState")
            .field("child_pid", &self.child_pid)
            .field("job", &"<Job Object>")
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

#[derive(serde::Deserialize, serde::Serialize, Debug, Clone, PartialEq)]
pub struct BackendStateFile {
    pub pid: u32,
    #[serde(rename = "host")]
    pub bound_host: Option<String>,
    #[serde(rename = "port")]
    pub bound_port: Option<u16>,
    pub service: Option<String>,
    pub root_dir: Option<String>,
}

fn get_backend_state_dir() -> Option<std::path::PathBuf> {
    if let Ok(app_data) = std::env::var("APPDATA") {
        Some(std::path::PathBuf::from(app_data).join("AI-Marketing-Department").join("runtime"))
    } else if let Ok(app_data) = std::env::var("LOCALAPPDATA") {
        Some(std::path::PathBuf::from(app_data).join("AI-Marketing-Department").join("runtime"))
    } else if let Ok(home) = std::env::var("USERPROFILE").or_else(|_| std::env::var("HOME")) {
        Some(std::path::PathBuf::from(home).join(".ai-marketing-department").join("runtime"))
    } else {
        None
    }
}

pub fn read_backend_state(_root: &std::path::Path) -> Option<BackendStateFile> {
    let state_dir = get_backend_state_dir()?;
    let state_path = state_dir.join("backend_instance.json");
    if state_path.is_file() {
        if let Ok(content) = std::fs::read_to_string(&state_path) {
            if let Ok(state) = serde_json::from_str::<BackendStateFile>(&content) {
                return Some(state);
            }
        }
    }
    None
}

pub fn clear_backend_state_file(_root: &std::path::Path) {
    if let Some(state_dir) = get_backend_state_dir() {
        let state_path = state_dir.join("backend_instance.json");
        if state_path.is_file() {
            let _ = std::fs::remove_file(state_path);
        }
    }
}

pub fn is_port_in_use(host: &str, port: u16) -> bool {
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

pub fn is_backend_healthy(host: &str, port: u16) -> bool {
    let addr = format!("{}:{}", host, port);
    let parse_addr = match addr.parse() {
        Ok(a) => a,
        Err(_) => return false,
    };
    let mut stream = match TcpStream::connect_timeout(&parse_addr, Duration::from_millis(500)) {
        Ok(s) => s,
        Err(_) => return false,
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(1500)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(1000)));
    let req = format!("GET /api/health HTTP/1.1\r\nHost: {}:{}\r\nConnection: close\r\n\r\n", host, port);
    if stream.write_all(req.as_bytes()).is_err() {
        return false;
    }
    let mut buf = Vec::new();
    let mut tmp = [0u8; 1024];
    loop {
        match stream.read(&mut tmp) {
            Ok(0) => break,
            Ok(n) => {
                buf.extend_from_slice(&tmp[..n]);
                if buf.len() > 8192 { break; }
            }
            Err(_) => break,
        }
    }
    let resp_str = String::from_utf8_lossy(&buf);
    if (resp_str.starts_with("HTTP/1.1 200") || resp_str.starts_with("HTTP/1.0 200"))
        && resp_str.contains("\"status\"")
        && resp_str.contains("\"ok\"")
    {
        return true;
    }
    false
}

#[cfg(target_os = "windows")]
pub fn terminate_owned_process(pid: u32) -> bool {
    unsafe {
        extern "system" {
            fn OpenProcess(dwDesiredAccess: u32, bInheritHandle: i32, dwProcessId: u32) -> *mut std::ffi::c_void;
            fn TerminateProcess(hProcess: *mut std::ffi::c_void, uExitCode: u32) -> i32;
            fn CloseHandle(hObject: *mut std::ffi::c_void) -> i32;
            fn WaitForSingleObject(hHandle: *mut std::ffi::c_void, dwMilliseconds: u32) -> u32;
        }
        const PROCESS_TERMINATE: u32 = 0x0001;
        const SYNCHRONIZE: u32 = 0x00100000;
        let h_proc = OpenProcess(PROCESS_TERMINATE | SYNCHRONIZE, 0, pid);
        if h_proc.is_null() {
            return false;
        }
        let ok = TerminateProcess(h_proc, 1) != 0;
        WaitForSingleObject(h_proc, 2000);
        CloseHandle(h_proc);
        ok
    }
}

#[cfg(not(target_os = "windows"))]
pub fn terminate_owned_process(_pid: u32) -> bool {
    true
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

fn spawn_backend_and_bootstrap() -> (Option<u32>, Option<usize>, Option<job_object::JobObjectHandle>, Option<String>, String, u16) {
    let root_dir = find_project_root();
    let server_script = root_dir.join("app_api").join("server.py");

    let mut default_host = "127.0.0.1".to_string();
    let mut default_port = 8765u16;

    // Check if port is currently occupied
    if is_port_in_use(&default_host, default_port) {
        println!("Port {}:{} is already in use. Checking backend ownership...", default_host, default_port);
        let owned_state = read_backend_state(&root_dir);

        if let Some(state) = owned_state {
            if state.service.as_deref() == Some("AI Marketing Department API") && state.pid > 0 {
                let existing_token = std::env::var("APP_BACKEND_BEARER_DEV").ok();
                if is_backend_healthy(&default_host, default_port) && existing_token.is_some() {
                    println!("Reusing healthy owned dev backend on {}:{}", default_host, default_port);
                    return (None, None, None, existing_token, default_host, default_port);
                } else {
                    println!("Stale or unauthenticated owned backend detected (PID {}). Safely recycling...", state.pid);
                    terminate_owned_process(state.pid);
                    clear_backend_state_file(&root_dir);

                    // Wait up to 3 seconds for port to release
                    let start_wait = Instant::now();
                    while start_wait.elapsed() < Duration::from_secs(3) {
                        if !is_port_in_use(&default_host, default_port) {
                            break;
                        }
                        std::thread::sleep(Duration::from_millis(50));
                    }
                }
            } else {
                eprintln!("CRITICAL: Port {}:{} occupied by an unknown process. Refusing to terminate arbitrary processes. Failing closed.", default_host, default_port);
                return (None, None, None, None, default_host, default_port);
            }
        } else {
            // Port in use without valid state file -> UNKNOWN PROCESS
            eprintln!("CRITICAL: Port {}:{} occupied by an unknown process without backend state record. Failing closed.", default_host, default_port);
            return (None, None, None, None, default_host, default_port);
        }
    } else {
        // Clean up any stale state file if port is not in use
        clear_backend_state_file(&root_dir);
    }

    println!("Starting backend process from: {:?}", root_dir);

    let job = match job_object::JobObjectHandle::new() {
        Some(j) => j,
        None => {
            eprintln!("CRITICAL: Failed to create Windows Job Object. Failing closed.");
            return (None, None, None, None, default_host, default_port);
        }
    };

    #[cfg(target_os = "windows")]
    {
        match job_object::spawn_in_job_suspended(&job, &server_script, &root_dir) {
            Ok(spawn_res) => {
                println!("Spawned backend process in Job Object with PID: {}", spawn_res.child_pid);

                // Continuous stderr drain worker to prevent buffer saturation (PROD-LIFECYCLE-PIPE-DRAIN)
                let stderr_file = spawn_res.stderr_file;
                std::thread::spawn(move || {
                    let mut reader = BufReader::new(stderr_file);
                    let mut buf = [0u8; 4096];
                    while let Ok(n) = reader.read(&mut buf) {
                        if n == 0 { break; }
                    }
                });

                let mut token: Option<String> = None;
                let mut bootstrap_frames_count = 0usize;
                let stdout_file = spawn_res.stdout_file;
                let mut reader = BufReader::new(stdout_file);
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

                // If bootstrap handshake failed or was rejected, terminate process tree immediately
                if token.is_none() {
                    eprintln!("Bootstrap failed or was rejected. Terminating spawned child process tree...");
                    job.terminate(1);
                    return (None, None, None, None, default_host, default_port);
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

                // Wait up to 10 seconds for backend to become responsive on /api/health
                let start = Instant::now();
                let mut backend_ready = false;
                while start.elapsed() < Duration::from_secs(10) {
                    if is_backend_healthy(&default_host, default_port) {
                        println!("Backend is ready and listening on {}:{}", default_host, default_port);
                        backend_ready = true;
                        break;
                    }
                    std::thread::sleep(Duration::from_millis(100));
                }

                if !backend_ready {
                    eprintln!("Backend failed to become healthy within timeout. Terminating spawned child process tree...");
                    job.terminate(1);
                    return (None, None, None, None, default_host, default_port);
                }

                (Some(spawn_res.child_pid), Some(spawn_res.process_handle as usize), Some(job), token, default_host, default_port)
            }
            Err(e) => {
                eprintln!("Failed to spawn backend python process suspended in job: {}", e);
                job.terminate(1);
                (None, None, None, None, default_host, default_port)
            }
        }
    }

    #[cfg(not(target_os = "windows"))]
    {
        (None, None, None, None, default_host, default_port)
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

    // 1. Check if backend child process has exited
    #[cfg(target_os = "windows")]
    {
        if let Ok(guard_handle) = state.process_handle.lock() {
            if let Some(handle_val) = *guard_handle {
                unsafe {
                    extern "system" {
                        fn GetExitCodeProcess(h_process: *mut std::ffi::c_void, lp_exit_code: *mut u32) -> i32;
                    }
                    let mut exit_code: u32 = 0;
                    if GetExitCodeProcess(handle_val as *mut std::ffi::c_void, &mut exit_code) != 0 {
                        if exit_code != 259 {
                            let _ = state.auth_token.lock().map(|mut t| *t = None);
                            return Err(format!("BACKEND_PROCESS_TERMINATED: Backend process exited with status {}", exit_code));
                        }
                    }
                }
            }
        }
    }

    // 2. Validate pending_id format
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

    // 3. Fetch authoritative proposal from backend using native bearer
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

    // 4. Format and show native confirmation dialog
    let title = "AI Marketing Department — Consequential Action Approval";
    let message = format_approval_confirmation_message(&parsed_proposal, pending_id);

    let user_confirmed = show_native_confirmation_dialog(title, &message);
    if !user_confirmed {
        return Err("USER_REJECTED_NATIVE_CONFIRMATION".to_string());
    }

    // 5. Submit approval decision to backend
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

    // 0. Check if backend child process has exited
    #[cfg(target_os = "windows")]
    {
        if let Ok(guard_handle) = state.process_handle.lock() {
            if let Some(handle_val) = *guard_handle {
                unsafe {
                    extern "system" {
                        fn GetExitCodeProcess(h_process: *mut std::ffi::c_void, lp_exit_code: *mut u32) -> i32;
                    }
                    let mut exit_code: u32 = 0;
                    if GetExitCodeProcess(handle_val as *mut std::ffi::c_void, &mut exit_code) != 0 {
                        if exit_code != 259 {
                            let _ = state.auth_token.lock().map(|mut t| *t = None);
                            return Err(format!("BACKEND_PROCESS_TERMINATED: Backend process exited with status {}", exit_code));
                        }
                    }
                }
            }
        }
    }

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

#[derive(serde::Serialize, serde::Deserialize, Debug, Clone, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum StreamEventType {
    Progress,
    Delta,
    Complete,
    Error,
}

#[derive(serde::Serialize, serde::Deserialize, Debug, Clone, PartialEq)]
pub struct StreamMessage {
    pub event: StreamEventType,
    pub data: serde_json::Value,
}

#[derive(serde::Serialize, serde::Deserialize, Debug)]
pub struct ApiStreamArgs {
    pub path: String,
    pub body: Option<String>,
}

pub fn is_allowed_stream_route(path: &str) -> bool {
    let clean = path.trim();
    if !is_safe_api_path(clean) {
        return false;
    }
    if clean == "/api/chat/stream" {
        return true;
    }
    if let Some(rest) = clean.strip_prefix("/api/chat/sessions/") {
        if let Some(session_id) = rest.strip_suffix("/stream") {
            if !session_id.is_empty()
                && !session_id.contains('/')
                && session_id.chars().all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-')
            {
                return true;
            }
        }
    }
    false
}

pub const MAX_SSE_FRAME_BYTES: usize = 10 * 1024 * 1024; // 10MB per incomplete logical SSE frame

pub struct SseParser {
    buffer: Vec<u8>,
    saw_terminal: bool,
    max_frame_bytes: usize,
}

impl SseParser {
    pub fn new() -> Self {
        Self::with_max_frame_bytes(MAX_SSE_FRAME_BYTES)
    }

    pub fn with_max_frame_bytes(max_frame_bytes: usize) -> Self {
        Self {
            buffer: Vec::new(),
            saw_terminal: false,
            max_frame_bytes,
        }
    }

    pub fn push_chunk(&mut self, chunk: &[u8]) -> Result<(), String> {
        self.buffer.extend_from_slice(chunk);
        if self.buffer.len() > self.max_frame_bytes {
            let delim_info = if let Some(idx) = self.find_subsequence(b"\r\n\r\n") {
                Some((idx, 4))
            } else if let Some(idx) = self.find_subsequence(b"\n\n") {
                Some((idx, 2))
            } else {
                None
            };

            match delim_info {
                Some((idx, _)) if idx <= self.max_frame_bytes => {
                    // Delimiter is within limit, next_event will drain it
                }
                _ => {
                    let observed_len = self.buffer.len();
                    return Err(format!(
                        "SSE_FRAME_TOO_LARGE: Frame buffer length {} exceeds maximum allowed limit of {} bytes",
                        observed_len, self.max_frame_bytes
                    ));
                }
            }
        }
        Ok(())
    }

    pub fn next_event(&mut self) -> Result<Option<StreamMessage>, String> {
        loop {
            let delim_info = if let Some(idx) = self.find_subsequence(b"\r\n\r\n") {
                Some((idx, 4))
            } else if let Some(idx) = self.find_subsequence(b"\n\n") {
                Some((idx, 2))
            } else {
                None
            };

            let (idx, delim_len) = match delim_info {
                Some(info) => info,
                None => return Ok(None),
            };

            if idx > self.max_frame_bytes {
                return Err(format!(
                    "SSE_FRAME_TOO_LARGE: Single frame size {} exceeds maximum allowed limit of {} bytes",
                    idx, self.max_frame_bytes
                ));
            }

            let frame_bytes: Vec<u8> = self.buffer.drain(..idx).collect();
            self.buffer.drain(..delim_len);

            let frame_str = match std::str::from_utf8(&frame_bytes) {
                Ok(s) => s,
                Err(e) => return Err(format!("INVALID_UTF8_IN_SSE_FRAME: {}", e)),
            };

            let trimmed = frame_str.trim();
            if trimmed.is_empty() {
                continue;
            }

            let mut event_name: Option<String> = None;
            let mut data_str: Option<String> = None;

            for line in frame_str.lines() {
                let l = line.trim_end_matches(['\r', '\n']);
                if l.is_empty() || l.starts_with(':') {
                    continue;
                }
                if let Some(rest) = l.strip_prefix("event:") {
                    event_name = Some(rest.trim().to_string());
                } else if let Some(rest) = l.strip_prefix("data:") {
                    let d = rest.strip_prefix(' ').unwrap_or(rest);
                    data_str = Some(d.to_string());
                }
            }

            let event_type = match event_name.as_deref() {
                Some("progress") => StreamEventType::Progress,
                Some("delta") => StreamEventType::Delta,
                Some("complete") => StreamEventType::Complete,
                Some("error") => StreamEventType::Error,
                Some(other) => return Err(format!("UNKNOWN_SSE_EVENT_TYPE: {}", other)),
                None => return Err("MISSING_EVENT_NAME_IN_SSE_FRAME".to_string()),
            };

            let raw_data = match data_str {
                Some(d) => d,
                None => return Err("MISSING_DATA_IN_SSE_FRAME".to_string()),
            };

            let parsed_data: serde_json::Value = match serde_json::from_str(&raw_data) {
                Ok(v) => v,
                Err(e) => return Err(format!("MALFORMED_SSE_JSON_DATA: {}", e)),
            };

            if event_type == StreamEventType::Complete || event_type == StreamEventType::Error {
                self.saw_terminal = true;
            }

            return Ok(Some(StreamMessage {
                event: event_type,
                data: parsed_data,
            }));
        }
    }

    pub fn finish(&mut self) -> Result<Option<StreamMessage>, String> {
        if self.buffer.len() > self.max_frame_bytes {
            return Err(format!(
                "SSE_FRAME_TOO_LARGE: Trailing frame buffer length {} exceeds maximum allowed limit of {} bytes",
                self.buffer.len(), self.max_frame_bytes
            ));
        }
        let has_content = self.buffer.iter().any(|&b| b != b' ' && b != b'\r' && b != b'\n' && b != b'\t');
        if has_content {
            let frame_bytes: Vec<u8> = self.buffer.drain(..).collect();
            let frame_str = match std::str::from_utf8(&frame_bytes) {
                Ok(s) => s,
                Err(e) => return Err(format!("INVALID_UTF8_IN_TRAILING_SSE_FRAME: {}", e)),
            };
            let mut event_name: Option<String> = None;
            let mut data_str: Option<String> = None;
            for line in frame_str.lines() {
                let l = line.trim_end_matches(['\r', '\n']);
                if l.is_empty() || l.starts_with(':') {
                    continue;
                }
                if let Some(rest) = l.strip_prefix("event:") {
                    event_name = Some(rest.trim().to_string());
                } else if let Some(rest) = l.strip_prefix("data:") {
                    let d = rest.strip_prefix(' ').unwrap_or(rest);
                    data_str = Some(d.to_string());
                }
            }
            if let (Some(ev), Some(dt)) = (event_name, data_str) {
                let event_type = match ev.as_str() {
                    "progress" => StreamEventType::Progress,
                    "delta" => StreamEventType::Delta,
                    "complete" => StreamEventType::Complete,
                    "error" => StreamEventType::Error,
                    other => return Err(format!("UNKNOWN_SSE_EVENT_TYPE: {}", other)),
                };
                let parsed_data: serde_json::Value = match serde_json::from_str(&dt) {
                    Ok(v) => v,
                    Err(e) => return Err(format!("MALFORMED_SSE_JSON_DATA: {}", e)),
                };
                if event_type == StreamEventType::Complete || event_type == StreamEventType::Error {
                    self.saw_terminal = true;
                }
                return Ok(Some(StreamMessage {
                    event: event_type,
                    data: parsed_data,
                }));
            }
            return Err("INCOMPLETE_TRAILING_SSE_FRAME".to_string());
        }
        Ok(None)
    }

    fn find_subsequence(&self, needle: &[u8]) -> Option<usize> {
        self.buffer
            .windows(needle.len())
            .position(|window| window == needle)
    }
}

pub fn perform_loopback_sse_stream<F>(
    host: &str,
    port: u16,
    path: &str,
    token: &str,
    body: Option<String>,
    mut emit_fn: F,
) -> Result<(), String>
where
    F: FnMut(StreamMessage) -> Result<(), String>,
{
    let addr = format!("{}:{}", host, port);
    let mut stream = TcpStream::connect_timeout(
        &addr.parse().map_err(|e| format!("INVALID_ADDRESS: {}", e))?,
        Duration::from_secs(5),
    )
    .map_err(|e| format!("CONNECTION_FAILED: {}", e))?;

    stream
        .set_read_timeout(Some(Duration::from_secs(120)))
        .map_err(|e| format!("TIMEOUT_SET_FAILED: {}", e))?;
    stream
        .set_write_timeout(Some(Duration::from_secs(10)))
        .map_err(|e| format!("TIMEOUT_SET_FAILED: {}", e))?;

    let body_bytes = body.as_deref().unwrap_or("{}").as_bytes();
    let content_length = body_bytes.len();

    let request_raw = format!(
        "POST {} HTTP/1.0\r\nHost: {}:{}\r\nAuthorization: Bearer {}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        path, host, port, token, content_length
    );

    stream
        .write_all(request_raw.as_bytes())
        .map_err(|e| format!("WRITE_FAILED: {}", e))?;

    if !body_bytes.is_empty() {
        stream
            .write_all(body_bytes)
            .map_err(|e| format!("BODY_WRITE_FAILED: {}", e))?;
    }

    stream.flush().map_err(|e| format!("FLUSH_FAILED: {}", e))?;

    let mut header_buf = Vec::new();
    let mut found_header_end = false;
    let mut initial_body_bytes = Vec::new();
    let mut chunk_buf = [0u8; 1024];

    loop {
        match stream.read(&mut chunk_buf) {
            Ok(0) => break,
            Ok(n) => {
                header_buf.extend_from_slice(&chunk_buf[..n]);
                if let Some(idx) = header_buf.windows(4).position(|w| w == b"\r\n\r\n") {
                    found_header_end = true;
                    initial_body_bytes = header_buf.split_off(idx + 4);
                    header_buf.truncate(idx);
                    break;
                } else if let Some(idx) = header_buf.windows(2).position(|w| w == b"\n\n") {
                    found_header_end = true;
                    initial_body_bytes = header_buf.split_off(idx + 2);
                    header_buf.truncate(idx);
                    break;
                }
                if header_buf.len() > 16384 {
                    return Err("HTTP_HEADERS_TOO_LARGE".to_string());
                }
            }
            Err(e) => return Err(format!("READ_HEADERS_FAILED: {}", e)),
        }
    }

    if !found_header_end {
        return Err("MALFORMED_HTTP_RESPONSE: No header delimiter found".to_string());
    }

    let header_str = String::from_utf8_lossy(&header_buf);
    let mut lines = header_str.lines();
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

    if status_code != 200 {
        return Err(format!("BACKEND_HTTP_ERROR_{}", status_code));
    }

    let content_type = response_headers
        .get("content-type")
        .cloned()
        .unwrap_or_default()
        .to_lowercase();
    if !content_type.contains("text/event-stream") {
        return Err(format!("INVALID_STREAM_CONTENT_TYPE: {}", content_type));
    }

    let mut parser = SseParser::new();
    let mut terminal_seen = false;

    if !initial_body_bytes.is_empty() {
        parser.push_chunk(&initial_body_bytes)?;
        while let Some(msg) = parser.next_event()? {
            let is_term = msg.event == StreamEventType::Complete || msg.event == StreamEventType::Error;
            emit_fn(msg)?;
            if is_term {
                terminal_seen = true;
                break;
            }
        }
    }

    if !terminal_seen {
        let mut buffer = [0u8; 2048];
        loop {
            match stream.read(&mut buffer) {
                Ok(0) => break,
                Ok(n) => {
                    parser.push_chunk(&buffer[..n])?;
                    while let Some(msg) = parser.next_event()? {
                        let is_term = msg.event == StreamEventType::Complete || msg.event == StreamEventType::Error;
                        emit_fn(msg)?;
                        if is_term {
                            terminal_seen = true;
                            break;
                        }
                    }
                    if terminal_seen {
                        break;
                    }
                }
                Err(e) => {
                    return Err(format!("STREAM_READ_ERROR: {}", e));
                }
            }
        }
    }

    if !terminal_seen {
        if let Some(msg) = parser.finish()? {
            let is_term = msg.event == StreamEventType::Complete || msg.event == StreamEventType::Error;
            emit_fn(msg)?;
            if is_term {
                terminal_seen = true;
            }
        }
    }

    if !terminal_seen {
        return Err("PREMATURE_EOF_BEFORE_TERMINAL".to_string());
    }

    Ok(())
}

#[tauri::command]
async fn api_stream(
    state: tauri::State<'_, BackendProcessState>,
    args: ApiStreamArgs,
    channel: tauri::ipc::Channel<StreamMessage>,
) -> Result<(), String> {
    let path = args.path.trim();

    // 0. Check if backend child process has exited
    #[cfg(target_os = "windows")]
    {
        if let Ok(guard_handle) = state.process_handle.lock() {
            if let Some(handle_val) = *guard_handle {
                unsafe {
                    extern "system" {
                        fn GetExitCodeProcess(h_process: *mut std::ffi::c_void, lp_exit_code: *mut u32) -> i32;
                    }
                    let mut exit_code: u32 = 0;
                    if GetExitCodeProcess(handle_val as *mut std::ffi::c_void, &mut exit_code) != 0 {
                        if exit_code != 259 {
                            let _ = state.auth_token.lock().map(|mut t| *t = None);
                            return Err(format!("BACKEND_PROCESS_TERMINATED: Backend process exited with status {}", exit_code));
                        }
                    }
                }
            }
        }
    }

    // 1. Strict Path Validation
    if !is_allowed_stream_route(path) {
        return Err(format!("FORBIDDEN_STREAM_ROUTE: Route {} is not an authorized streaming endpoint", path));
    }

    // 2. Body length bound (max 10MB)
    if let Some(ref b) = args.body {
        if b.len() > MAX_REQUEST_BODY_BYTES {
            return Err("REQUEST_TOO_LARGE: Request payload exceeds 10MB limit".to_string());
        }
    }

    // 3. Acquire Token & Endpoint from State
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

    let path_str = path.to_string();
    let body_opt = args.body;

    tauri::async_runtime::spawn_blocking(move || {
        perform_loopback_sse_stream(&host, port, &path_str, &token, body_opt, |msg| {
            channel.send(msg).map_err(|e| format!("CHANNEL_SEND_FAILED: {}", e))
        })
    })
    .await
    .map_err(|e| format!("TASK_JOIN_ERROR: {}", e))?
}

fn main() {
    let (child_pid, process_handle, job_handle, auth_token, api_host, api_port) = spawn_backend_and_bootstrap();

    let app = tauri::Builder::default()
        .manage(BackendProcessState {
            child_pid: Mutex::new(child_pid),
            #[cfg(target_os = "windows")]
            process_handle: Mutex::new(process_handle),
            job: Mutex::new(job_handle),
            auth_token: Mutex::new(auth_token),
            api_host: Mutex::new(api_host),
            api_port: Mutex::new(api_port),
        })
        .invoke_handler(tauri::generate_handler![api_request, review_pending_approval, api_stream])
        .build(tauri::generate_context!())
        .expect("error while building AI Marketing Department desktop application");

    app.run(|app_handle, event| {
        if let tauri::RunEvent::Exit = event {
            // Clean up spawned backend on exit
            if let Some(state) = app_handle.try_state::<BackendProcessState>() {
                if let Ok(mut lock_job) = state.job.lock() {
                    if let Some(job) = lock_job.take() {
                        println!("Terminating backend job object on exit...");
                        let _ = job.terminate(0);
                    }
                }
                #[cfg(target_os = "windows")]
                if let Ok(mut lock_handle) = state.process_handle.lock() {
                    if let Some(handle_val) = lock_handle.take() {
                        unsafe {
                            extern "system" {
                                fn CloseHandle(h: *mut std::ffi::c_void) -> i32;
                            }
                            CloseHandle(handle_val as *mut std::ffi::c_void);
                        }
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
            child_pid: Mutex::new(None),
            #[cfg(target_os = "windows")]
            process_handle: Mutex::new(None),
            job: Mutex::new(None),
            auth_token: Mutex::new(Some("SUPER_SECRET_TOKEN_1234567890".to_string())),
            api_host: Mutex::new("127.0.0.1".to_string()),
            api_port: Mutex::new(8765),
        };
        let debug_str = format!("{:?}", state);
        assert!(debug_str.contains("[REDACTED]"));
        assert!(!debug_str.contains("SUPER_SECRET_TOKEN_1234567890"));
    }

    #[test]
    fn test_job_object_creation_and_termination() {
        let job = job_object::JobObjectHandle::new();
        assert!(job.is_some());
        let j = job.unwrap();
        assert!(j.terminate(0));
    }

    #[test]
    fn test_job_object_suspended_process_assignment() {
        #[cfg(target_os = "windows")]
        {
            let job = job_object::JobObjectHandle::new().expect("Failed to create Job Object");
            let root = find_project_root();
            let helper_script = root.join("app_api").join("server.py");
            if helper_script.exists() {
                let spawn_res = job_object::spawn_in_job_suspended(&job, &helper_script, &root);
                assert!(spawn_res.is_ok());
                let res = spawn_res.unwrap();
                assert!(res.child_pid > 0);
                assert!(!res.process_handle.is_null());
                // Terminate job to clean up test process immediately
                assert!(job.terminate(0));
                unsafe {
                    extern "system" {
                        fn CloseHandle(h: *mut std::ffi::c_void) -> i32;
                    }
                    CloseHandle(res.process_handle);
                }
            }
        }
    }

    #[test]
    fn test_job_object_breakaway_is_disabled() {
        #[cfg(target_os = "windows")]
        {
            assert_eq!(job_object::JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, 0x00002000);
            // Verify breakaway flag (0x00000800) is NOT part of limit flags
            assert_eq!(job_object::JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE & 0x00000800, 0);
        }
    }

    #[test]
    fn test_job_object_assignment_failure_cleanup() {
        #[cfg(target_os = "windows")]
        {
            let job = job_object::JobObjectHandle::new().expect("Failed to create Job Object");
            // Attempt assigning null / invalid handle
            let assigned = job.assign_raw_process(std::ptr::null_mut());
            assert!(!assigned, "Assigning null handle must fail closed");
            assert!(job.terminate(0));
        }
    }

    #[test]
    fn test_job_object_immediate_grandchild_50_cycles() {
        #[cfg(target_os = "windows")]
        {
            extern "system" {
                fn OpenProcess(dwDesiredAccess: u32, bInheritHandle: i32, dwProcessId: u32) -> *mut std::ffi::c_void;
                fn GetExitCodeProcess(hProcess: *mut std::ffi::c_void, lpExitCode: *mut u32) -> i32;
                fn CloseHandle(hObject: *mut std::ffi::c_void) -> i32;
            }

            let root = find_project_root();
            let helper_script = root.join("tests").join("helper_grandchild.py");
            if !helper_script.exists() {
                return;
            }

            let mut escaped_count = 0usize;
            let start = std::time::Instant::now();

            for _cycle in 0..50 {
                let job = job_object::JobObjectHandle::new().expect("Failed to create Job Object");
                let spawn_res = job_object::spawn_in_job_suspended(&job, &helper_script, &root);
                assert!(spawn_res.is_ok());
                let res = spawn_res.unwrap();
                let child_pid = res.child_pid;

                let mut reader = std::io::BufReader::new(res.stdout_file);
                let mut line = String::new();
                let _ = reader.read_line(&mut line);

                let mut gc_pid = 0u32;
                if line.trim().starts_with("GC_PID:") {
                    if let Ok(p) = line.trim()["GC_PID:".len()..].parse::<u32>() {
                        gc_pid = p;
                    }
                }

                let h_proc = unsafe { OpenProcess(0x1000, 0, child_pid) };
                let mut exit_code: u32 = 0;
                let helper_alive_before = if !h_proc.is_null() {
                    unsafe {
                        GetExitCodeProcess(h_proc, &mut exit_code);
                        CloseHandle(h_proc);
                    }
                    exit_code == 259
                } else {
                    false
                };
                assert!(helper_alive_before, "Helper must be alive before Job Object termination");

                let h_gc = if gc_pid > 0 {
                    unsafe { OpenProcess(0x1000 | 0x00100000, 0, gc_pid) }
                } else {
                    std::ptr::null_mut()
                };

                if !h_gc.is_null() {
                    let mut gc_exit: u32 = 0;
                    unsafe {
                        GetExitCodeProcess(h_gc, &mut gc_exit);
                    }
                    assert_eq!(gc_exit, 259, "Grandchild must be active before Job Object termination");
                }

                // Terminate Job Object
                assert!(job.terminate(0));

                // Bounded wait for kernel termination to complete
                unsafe {
                    extern "system" {
                        fn WaitForSingleObject(hHandle: *mut std::ffi::c_void, dwMilliseconds: u32) -> u32;
                    }
                    WaitForSingleObject(res.process_handle, 3000);
                    if !h_gc.is_null() {
                        WaitForSingleObject(h_gc, 3000);
                    }
                }

                // Verify helper is dead after teardown
                let mut helper_exit: u32 = 0;
                unsafe {
                    GetExitCodeProcess(res.process_handle, &mut helper_exit);
                    CloseHandle(res.process_handle);
                }
                if helper_exit == 259 {
                    escaped_count += 1;
                }

                // Verify grandchild is dead after teardown
                if !h_gc.is_null() {
                    let mut gc_exit_after: u32 = 0;
                    unsafe {
                        GetExitCodeProcess(h_gc, &mut gc_exit_after);
                        CloseHandle(h_gc);
                    }
                    if gc_exit_after == 259 {
                        escaped_count += 1;
                    }
                }
            }

            println!("50 Rust Job Object immediate-grandchild cycles completed in {:?}", start.elapsed());
            assert_eq!(escaped_count, 0, "All 50 cycles must result in 0 escaped processes");
        }
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

    #[test]
    fn test_read_backend_state_valid_and_invalid() {
        let state_dir = get_backend_state_dir().expect("APPDATA or HOME must be available");
        std::fs::create_dir_all(&state_dir).unwrap();
        let state_path = state_dir.join("backend_instance.json");

        // Save any pre-existing state file to restore later
        let backup = if state_path.is_file() {
            Some(std::fs::read_to_string(&state_path).unwrap())
        } else {
            None
        };

        // 1. Clean slate -> None
        let _ = std::fs::remove_file(&state_path);
        let dummy_root = std::path::PathBuf::from("C:\\AI-Marketing-Department");
        assert_eq!(read_backend_state(&dummy_root), None);

        // 2. Valid file -> Some
        let valid_json = r#"{
            "pid": 12345,
            "host": "127.0.0.1",
            "port": 8765,
            "service": "AI Marketing Department API",
            "root_dir": "C:\\AI-Marketing-Department"
        }"#;
        std::fs::write(&state_path, valid_json).unwrap();
        let state = read_backend_state(&dummy_root).expect("Expected valid state");
        assert_eq!(state.pid, 12345);
        assert_eq!(state.service.as_deref(), Some("AI Marketing Department API"));

        // 3. State path must NOT be inside repo
        let state_str = state_path.to_string_lossy().to_lowercase();
        assert!(!state_str.contains("ai-marketing-department\\runtime\\backend_instance.json")
                || state_str.contains("appdata"),
            "State file must be in APPDATA, not repo root");

        // 4. Clear file
        clear_backend_state_file(&dummy_root);
        assert_eq!(read_backend_state(&dummy_root), None);

        // Restore backup if any
        if let Some(content) = backup {
            std::fs::write(&state_path, content).unwrap();
        }
    }

    #[test]
    fn test_is_backend_healthy_against_mock_servers() {
        use std::net::TcpListener;

        // 1. Healthy HTTP 200 server
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let server_thread = std::thread::spawn(move || {
            if let Ok((mut stream, _)) = listener.accept() {
                let mut req_buf = [0u8; 512];
                let _ = stream.read(&mut req_buf);
                let resp = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 58\r\n\r\n{\"status\":\"ok\",\"service\":\"AI Marketing Department API\"}";
                let _ = stream.write_all(resp.as_bytes());
            }
        });

        assert!(is_backend_healthy("127.0.0.1", port));
        let _ = server_thread.join();

        // 2. Unhealthy HTTP 500 server
        let listener500 = TcpListener::bind("127.0.0.1:0").unwrap();
        let port500 = listener500.local_addr().unwrap().port();
        let server_thread500 = std::thread::spawn(move || {
            if let Ok((mut stream, _)) = listener500.accept() {
                let mut req_buf = [0u8; 512];
                let _ = stream.read(&mut req_buf);
                let resp = "HTTP/1.1 500 Internal Server Error\r\nContent-Length: 0\r\n\r\n";
                let _ = stream.write_all(resp.as_bytes());
            }
        });

        assert!(!is_backend_healthy("127.0.0.1", port500));
        let _ = server_thread500.join();

        // 3. Non-listening port -> false
        assert!(!is_backend_healthy("127.0.0.1", 65432));
    }

    // =========================================================================
    // B4 TAURI SSE STREAMING TESTS
    // =========================================================================

    #[test]
    fn test_sse_parser_single_frame() {
        let mut parser = SseParser::new();
        parser.push_chunk(b"event: delta\r\ndata: {\"content\":\"Xin chao\"}\r\n\r\n").unwrap();
        let msg = parser.next_event().unwrap().expect("Expected event");
        assert_eq!(msg.event, StreamEventType::Delta);
        assert_eq!(msg.data["content"], "Xin chao");
        assert_eq!(parser.next_event().unwrap(), None);
    }

    #[test]
    fn test_sse_parser_split_across_reads() {
        let mut parser = SseParser::new();
        parser.push_chunk(b"event: del").unwrap();
        assert_eq!(parser.next_event().unwrap(), None);
        parser.push_chunk(b"ta\ndata: {\"content\":\"part 2\"}\n\n").unwrap();
        let msg = parser.next_event().unwrap().expect("Expected event");
        assert_eq!(msg.event, StreamEventType::Delta);
        assert_eq!(msg.data["content"], "part 2");
    }

    #[test]
    fn test_sse_parser_byte_by_byte() {
        let mut parser = SseParser::new();
        let payload = b"event: progress\r\ndata: {\"sequence\":1,\"event_type\":\"RUN_STARTED\"}\r\n\r\n";
        let mut found = None;
        for &byte in payload {
            parser.push_chunk(&[byte]).unwrap();
            if let Some(msg) = parser.next_event().unwrap() {
                found = Some(msg);
                break;
            }
        }
        let msg = found.expect("Expected parsed event byte-by-byte");
        assert_eq!(msg.event, StreamEventType::Progress);
        assert_eq!(msg.data["sequence"], 1);
        assert_eq!(msg.data["event_type"], "RUN_STARTED");
    }

    #[test]
    fn test_sse_parser_multiple_frames_in_one_read() {
        let mut parser = SseParser::new();
        let chunk = b"event: progress\r\ndata: {\"sequence\":1}\r\n\r\nevent: delta\r\ndata: {\"content\":\"A\"}\r\n\r\nevent: complete\r\ndata: {\"status\":\"COMPLETED\"}\r\n\r\n";
        parser.push_chunk(chunk).unwrap();

        let m1 = parser.next_event().unwrap().expect("m1");
        let m2 = parser.next_event().unwrap().expect("m2");
        let m3 = parser.next_event().unwrap().expect("m3");
        assert_eq!(parser.next_event().unwrap(), None);

        assert_eq!(m1.event, StreamEventType::Progress);
        assert_eq!(m2.event, StreamEventType::Delta);
        assert_eq!(m3.event, StreamEventType::Complete);
    }

    #[test]
    fn test_sse_parser_vietnamese_utf8_fragmentation() {
        let mut parser = SseParser::new();
        // UTF-8 for "Kế hoạch marketing" split across multi-byte boundary
        let full = "event: delta\r\ndata: {\"content\":\"Kế hoạch marketing chuỗi spa\"}\r\n\r\n";
        let bytes = full.as_bytes();

        // Split in the middle of 'ế' (0xE1 0xBA 0xBF)
        let split_idx = 27; // Inside "Kế hoạch"
        parser.push_chunk(&bytes[..split_idx]).unwrap();
        assert_eq!(parser.next_event().unwrap(), None);

        parser.push_chunk(&bytes[split_idx..]).unwrap();
        let msg = parser.next_event().unwrap().expect("Expected event after UTF-8 reassembly");
        assert_eq!(msg.event, StreamEventType::Delta);
        assert_eq!(msg.data["content"], "Kế hoạch marketing chuỗi spa");
    }

    #[test]
    fn test_sse_parser_progress_frame() {
        let mut parser = SseParser::new();
        parser.push_chunk(b"event: progress\r\ndata: {\"run_id\":\"RUN-1\",\"sequence\":2,\"event_type\":\"STAGE_STARTED\",\"stage\":\"CMO_INITIAL\",\"mode\":\"FULL_WORKFLOW\"}\r\n\r\n").unwrap();
        let msg = parser.next_event().unwrap().expect("Progress event");
        assert_eq!(msg.event, StreamEventType::Progress);
        assert_eq!(msg.data["stage"], "CMO_INITIAL");
        assert_eq!(msg.data["event_type"], "STAGE_STARTED");
    }

    #[test]
    fn test_sse_parser_delta_frame() {
        let mut parser = SseParser::new();
        parser.push_chunk(b"event: delta\r\ndata: {\"content\":\"chunk text\",\"provider\":\"xkiro\",\"model_name\":\"deepseek-v4-pro\"}\r\n\r\n").unwrap();
        let msg = parser.next_event().unwrap().expect("Delta event");
        assert_eq!(msg.event, StreamEventType::Delta);
        assert_eq!(msg.data["content"], "chunk text");
        assert_eq!(msg.data["provider"], "xkiro");
    }

    #[test]
    fn test_sse_parser_complete_frame() {
        let mut parser = SseParser::new();
        parser.push_chunk(b"event: complete\r\ndata: {\"status\":\"COMPLETED\",\"run_id\":\"RUN-FIN\"}\r\n\r\n").unwrap();
        let msg = parser.next_event().unwrap().expect("Complete event");
        assert_eq!(msg.event, StreamEventType::Complete);
        assert_eq!(msg.data["status"], "COMPLETED");
    }

    #[test]
    fn test_sse_parser_error_frame() {
        let mut parser = SseParser::new();
        parser.push_chunk(b"event: error\r\ndata: {\"error\":\"Pipeline execution error\",\"code\":\"INTERNAL_ERROR\"}\r\n\r\n").unwrap();
        let msg = parser.next_event().unwrap().expect("Error event");
        assert_eq!(msg.event, StreamEventType::Error);
        assert_eq!(msg.data["error"], "Pipeline execution error");
    }

    #[test]
    fn test_sse_parser_unknown_event_rejected() {
        let mut parser = SseParser::new();
        parser.push_chunk(b"event: unhandled_custom_event\r\ndata: {\"foo\":\"bar\"}\r\n\r\n").unwrap();
        let res = parser.next_event();
        assert!(res.is_err());
        assert!(res.unwrap_err().contains("UNKNOWN_SSE_EVENT_TYPE"));
    }

    #[test]
    fn test_sse_parser_malformed_json_rejected() {
        let mut parser = SseParser::new();
        parser.push_chunk(b"event: delta\r\ndata: {unquoted_broken_json\r\n\r\n").unwrap();
        let res = parser.next_event();
        assert!(res.is_err());
        assert!(res.unwrap_err().contains("MALFORMED_SSE_JSON_DATA"));
    }

    #[test]
    fn test_sse_parser_incomplete_trailing_rejected() {
        // Trailing frame missing data line
        let mut parser1 = SseParser::new();
        parser1.push_chunk(b"event: delta\r\n").unwrap();
        assert_eq!(parser1.next_event().unwrap(), None);
        let res1 = parser1.finish();
        assert!(res1.is_err());
        assert_eq!(res1.unwrap_err(), "INCOMPLETE_TRAILING_SSE_FRAME");

        // Trailing frame with unclosed JSON data
        let mut parser2 = SseParser::new();
        parser2.push_chunk(b"event: delta\r\ndata: {\"incomplete\":").unwrap();
        assert_eq!(parser2.next_event().unwrap(), None);
        let res2 = parser2.finish();
        assert!(res2.is_err());
        assert!(res2.unwrap_err().contains("MALFORMED_SSE_JSON_DATA"));
    }

    #[test]
    fn test_allowed_stream_routes() {
        assert!(is_allowed_stream_route("/api/chat/stream"));
        assert!(is_allowed_stream_route("/api/chat/sessions/chat_12345/stream"));
        assert!(is_allowed_stream_route("/api/chat/sessions/session-abc_123/stream"));
    }

    #[test]
    fn test_denied_stream_routes_and_traversal() {
        assert!(!is_allowed_stream_route("/api/chat/sessions/../evil/stream"));
        assert!(!is_allowed_stream_route("/api/chat/sessions/chat_1/messages"));
        assert!(!is_allowed_stream_route("/api/health"));
        assert!(!is_allowed_stream_route("http://127.0.0.1:8765/api/chat/stream"));
        assert!(!is_allowed_stream_route("/api/chat/stream\r\nHost: evil"));
        assert!(!is_allowed_stream_route("/api/chat/sessions//stream"));
    }

    #[test]
    fn test_stream_ordering_fifo() {
        let mut parser = SseParser::new();
        let payload = b"event: progress\r\ndata: {\"sequence\":1}\r\n\r\nevent: progress\r\ndata: {\"sequence\":2}\r\n\r\nevent: delta\r\ndata: {\"content\":\"Token A\"}\r\n\r\nevent: delta\r\ndata: {\"content\":\"Token B\"}\r\n\r\nevent: complete\r\ndata: {\"status\":\"COMPLETED\"}\r\n\r\n";
        parser.push_chunk(payload).unwrap();

        let mut events = Vec::new();
        while let Some(msg) = parser.next_event().unwrap() {
            events.push(msg);
        }

        assert_eq!(events.len(), 5);
        assert_eq!(events[0].event, StreamEventType::Progress);
        assert_eq!(events[0].data["sequence"], 1);
        assert_eq!(events[1].event, StreamEventType::Progress);
        assert_eq!(events[1].data["sequence"], 2);
        assert_eq!(events[2].event, StreamEventType::Delta);
        assert_eq!(events[2].data["content"], "Token A");
        assert_eq!(events[3].event, StreamEventType::Delta);
        assert_eq!(events[3].data["content"], "Token B");
        assert_eq!(events[4].event, StreamEventType::Complete);
    }

    #[test]
    fn test_stream_token_security_and_redaction() {
        let mut parser = SseParser::new();
        parser.push_chunk(b"event: delta\r\ndata: {\"content\":\"Safe response\"}\r\n\r\n").unwrap();
        let msg = parser.next_event().unwrap().expect("msg");
        let json_str = serde_json::to_string(&msg).unwrap();
        assert!(!json_str.contains("Authorization"));
        assert!(!json_str.contains("Bearer"));
        assert!(!json_str.contains("a9fca20f039a"));
    }

    #[test]
    fn test_loopback_stream_against_mock_server() {
        use std::net::TcpListener;

        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();

        let server_thread = std::thread::spawn(move || {
            if let Ok((mut stream, _)) = listener.accept() {
                let mut buf = [0u8; 1024];
                let _ = stream.read(&mut buf);
                let response = "HTTP/1.0 200 OK\r\nContent-Type: text/event-stream; charset=utf-8\r\nConnection: close\r\n\r\nevent: progress\r\ndata: {\"sequence\":1}\r\n\r\nevent: delta\r\ndata: {\"content\":\"Xin chao\"}\r\n\r\nevent: complete\r\ndata: {\"status\":\"COMPLETED\"}\r\n\r\n";
                let _ = stream.write_all(response.as_bytes());
                let _ = stream.flush();
            }
        });

        let mut collected = Vec::new();
        let res = perform_loopback_sse_stream(
            "127.0.0.1",
            port,
            "/api/chat/stream",
            "mock_secret_token",
            Some("{\"content\":\"hi\"}".to_string()),
            |msg| {
                collected.push(msg);
                Ok(())
            },
        );

        assert!(res.is_ok(), "Loopback stream failed: {:?}", res);
        assert_eq!(collected.len(), 3);
        assert_eq!(collected[0].event, StreamEventType::Progress);
        assert_eq!(collected[1].event, StreamEventType::Delta);
        assert_eq!(collected[2].event, StreamEventType::Complete);

        let _ = server_thread.join();
    }

    #[test]
    fn test_loopback_stream_status_errors() {
        use std::net::TcpListener;

        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();

        let server_thread = std::thread::spawn(move || {
            if let Ok((mut stream, _)) = listener.accept() {
                let mut buf = [0u8; 512];
                let _ = stream.read(&mut buf);
                let response = "HTTP/1.0 401 Unauthorized\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n{\"error\":\"UNAUTHORIZED\"}";
                let _ = stream.write_all(response.as_bytes());
            }
        });

        let res = perform_loopback_sse_stream(
            "127.0.0.1",
            port,
            "/api/chat/stream",
            "invalid_token",
            None,
            |_| Ok(()),
        );

        assert!(res.is_err());
        assert_eq!(res.unwrap_err(), "BACKEND_HTTP_ERROR_401");
        let _ = server_thread.join();
    }

    #[test]
    fn test_loopback_stream_invalid_content_type() {
        use std::net::TcpListener;

        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();

        let server_thread = std::thread::spawn(move || {
            if let Ok((mut stream, _)) = listener.accept() {
                let mut buf = [0u8; 512];
                let _ = stream.read(&mut buf);
                let response = "HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n{\"status\":\"ok\"}";
                let _ = stream.write_all(response.as_bytes());
            }
        });

        let res = perform_loopback_sse_stream(
            "127.0.0.1",
            port,
            "/api/chat/stream",
            "mock_token",
            None,
            |_| Ok(()),
        );

        assert!(res.is_err());
        assert!(res.unwrap_err().contains("INVALID_STREAM_CONTENT_TYPE"));
        let _ = server_thread.join();
    }

    #[test]
    fn test_loopback_stream_channel_send_failure_disconnects() {
        use std::net::TcpListener;

        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();

        let server_thread = std::thread::spawn(move || {
            if let Ok((mut stream, _)) = listener.accept() {
                let mut buf = [0u8; 512];
                let _ = stream.read(&mut buf);
                let response = "HTTP/1.0 200 OK\r\nContent-Type: text/event-stream; charset=utf-8\r\nConnection: close\r\n\r\nevent: delta\r\ndata: {\"content\":\"first\"}\r\n\r\nevent: delta\r\ndata: {\"content\":\"second\"}\r\n\r\n";
                let _ = stream.write_all(response.as_bytes());
            }
        });

        let mut call_count = 0;
        let res = perform_loopback_sse_stream(
            "127.0.0.1",
            port,
            "/api/chat/stream",
            "mock_token",
            None,
            |_| {
                call_count += 1;
                Err("CHANNEL_DISCONNECTED".to_string())
            },
        );

        assert!(res.is_err());
        assert_eq!(res.unwrap_err(), "CHANNEL_DISCONNECTED");
        assert_eq!(call_count, 1, "Reader should stop immediately on first channel error");
        let _ = server_thread.join();
    }

    #[test]
    fn test_loopback_stream_run_isolation() {
        let mut parser_a = SseParser::new();
        let mut parser_b = SseParser::new();

        parser_a.push_chunk(b"event: delta\r\ndata: {\"content\":\"Run A chunk\"}\r\n\r\n").unwrap();
        parser_b.push_chunk(b"event: delta\r\ndata: {\"content\":\"Run B chunk\"}\r\n\r\n").unwrap();

        let msg_a = parser_a.next_event().unwrap().unwrap();
        let msg_b = parser_b.next_event().unwrap().unwrap();

        assert_eq!(msg_a.data["content"], "Run A chunk");
        assert_eq!(msg_b.data["content"], "Run B chunk");
    }

    // =========================================================================
    // B4-R2 MEMORY BOUNDS & ASYNC CONCURRENCY TESTS
    // =========================================================================

    #[test]
    fn test_sse_frame_below_limit_accepted() {
        let mut parser = SseParser::with_max_frame_bytes(100);
        let frame = b"event: delta\r\ndata: {\"text\":\"ok\"}\r\n\r\n";
        assert!(frame.len() < 100);
        assert!(parser.push_chunk(frame).is_ok());
        let msg = parser.next_event().unwrap().unwrap();
        assert_eq!(msg.data["text"], "ok");
    }

    #[test]
    fn test_sse_frame_exact_boundary_accepted() {
        let prefix = "event: delta\r\ndata: {\"pad\":\"";
        let suffix = "\"}\r\n\r\n";
        let target_len = 100;
        let pad_len = target_len - prefix.len() - suffix.len();
        let padding = "a".repeat(pad_len);
        let exact_frame = format!("{}{}{}", prefix, padding, suffix);
        assert_eq!(exact_frame.len(), 100);

        let mut parser = SseParser::with_max_frame_bytes(100);
        assert!(parser.push_chunk(exact_frame.as_bytes()).is_ok());
        let msg = parser.next_event().unwrap().unwrap();
        assert_eq!(msg.data["pad"], padding);
    }

    #[test]
    fn test_sse_frame_above_limit_rejected() {
        let mut parser = SseParser::with_max_frame_bytes(50);
        let oversized = b"event: delta\r\ndata: {\"long_payload_exceeding_limit\":\"very_long_string_here\"}\r\n\r\n";
        assert!(oversized.len() > 50);
        let res = parser.push_chunk(oversized);
        assert!(res.is_err());
        let err = res.unwrap_err();
        assert!(err.contains("SSE_FRAME_TOO_LARGE"));
    }

    #[test]
    fn test_sse_unterminated_oversized_frame_rejected() {
        let mut parser = SseParser::with_max_frame_bytes(40);
        let chunk1 = b"event: delta\r\ndata: {\"unterminated\":";
        assert!(parser.push_chunk(chunk1).is_ok());
        let chunk2 = b" \"more bytes without delimiter\"";
        let res = parser.push_chunk(chunk2);
        assert!(res.is_err());
        assert!(res.unwrap_err().contains("SSE_FRAME_TOO_LARGE"));
    }

    #[test]
    fn test_sse_cumulative_many_small_frames_allowed() {
        let mut parser = SseParser::with_max_frame_bytes(60);
        // Stream 100 frames of 35 bytes each (cumulative 3500 bytes > 60 bytes limit)
        for i in 0..100 {
            let frame = format!("event: delta\r\ndata: {{\"i\":{}}}\r\n\r\n", i);
            assert!(frame.len() < 60);
            assert!(parser.push_chunk(frame.as_bytes()).is_ok());
            let msg = parser.next_event().unwrap().unwrap();
            assert_eq!(msg.data["i"], i);
        }
    }

    #[test]
    fn test_sse_oversized_payload_not_leaked_in_error() {
        let secret = "SUPER_SECRET_PAYLOAD_123456";
        let mut parser = SseParser::with_max_frame_bytes(30);
        let payload = format!("event: delta\r\ndata: {{\"secret\":\"{}\"}}\r\n\r\n", secret);
        let res = parser.push_chunk(payload.as_bytes());
        assert!(res.is_err());
        let err = res.unwrap_err();
        assert!(!err.contains(secret), "Secret payload must not leak in error message");
        assert!(err.contains("SSE_FRAME_TOO_LARGE"));
    }

    #[test]
    fn test_loopback_stream_headers_and_body_in_same_read() {
        use std::net::TcpListener;

        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();

        let server_thread = std::thread::spawn(move || {
            if let Ok((mut stream, _)) = listener.accept() {
                let mut buf = [0u8; 512];
                let _ = stream.read(&mut buf);
                // Entire response sent in a single write/packet: headers + 2 SSE frames
                let packet = "HTTP/1.0 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\nevent: progress\r\ndata: {\"step\":1}\r\n\r\nevent: complete\r\ndata: {\"status\":\"DONE\"}\r\n\r\n";
                let _ = stream.write_all(packet.as_bytes());
            }
        });

        let mut events = Vec::new();
        let res = perform_loopback_sse_stream(
            "127.0.0.1",
            port,
            "/api/chat/stream",
            "mock_token",
            None,
            |msg| {
                events.push(msg);
                Ok(())
            },
        );

        assert!(res.is_ok());
        assert_eq!(events.len(), 2);
        assert_eq!(events[0].event, StreamEventType::Progress);
        assert_eq!(events[0].data["step"], 1);
        assert_eq!(events[1].event, StreamEventType::Complete);
        let _ = server_thread.join();
    }

    #[test]
    fn test_response_header_limit_rejected() {
        use std::net::TcpListener;

        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();

        let server_thread = std::thread::spawn(move || {
            if let Ok((mut stream, _)) = listener.accept() {
                let mut buf = [0u8; 512];
                let _ = stream.read(&mut buf);
                let giant_header = "X-Padding: ".to_string() + &"a".repeat(20000) + "\r\n";
                let response = format!("HTTP/1.0 200 OK\r\nContent-Type: text/event-stream\r\n{}\r\n\r\n", giant_header);
                let _ = stream.write_all(response.as_bytes());
                let _ = stream.flush();
                let mut drain = [0u8; 128];
                while let Ok(n) = stream.read(&mut drain) {
                    if n == 0 {
                        break;
                    }
                }
            }
        });

        let res = perform_loopback_sse_stream(
            "127.0.0.1",
            port,
            "/api/chat/stream",
            "mock_token",
            None,
            |_| Ok(()),
        );

        assert!(res.is_err());
        assert_eq!(res.unwrap_err(), "HTTP_HEADERS_TOO_LARGE");
        let _ = server_thread.join();
    }

    #[test]
    fn test_concurrent_ordinary_ipc_while_stream_active() {
        use std::net::TcpListener;
        use std::sync::mpsc;
        use std::sync::Arc;
        use std::sync::Mutex;

        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();

        let (release_stream_tx, release_stream_rx) = mpsc::channel::<()>();
        let release_stream_rx = Arc::new(Mutex::new(release_stream_rx));

        let server_thread = std::thread::spawn(move || {
            for _ in 0..2 {
                if let Ok((mut stream, _)) = listener.accept() {
                    let release_stream_rx = Arc::clone(&release_stream_rx);
                    std::thread::spawn(move || {
                        let mut req_buf = [0u8; 1024];
                        let n = stream.read(&mut req_buf).unwrap_or(0);
                        let req_str = String::from_utf8_lossy(&req_buf[..n]);

                        if req_str.contains("/api/chat/stream") {
                            let header_and_progress = "HTTP/1.0 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\nevent: progress\r\ndata: {\"stage\":\"INIT\"}\r\n\r\nevent: delta\r\ndata: {\"content\":\"streaming...\"}\r\n\r\n";
                            let _ = stream.write_all(header_and_progress.as_bytes());
                            let _ = stream.flush();

                            let rx_guard = release_stream_rx.lock().unwrap();
                            let _ = rx_guard.recv();

                            let complete_frame = "event: complete\r\ndata: {\"status\":\"COMPLETED\"}\r\n\r\n";
                            let _ = stream.write_all(complete_frame.as_bytes());
                            let _ = stream.flush();
                        } else if req_str.contains("/api/health") {
                            let resp = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 26\r\n\r\n{\"status\":\"ok\",\"busy\":false}";
                            let _ = stream.write_all(resp.as_bytes());
                            let _ = stream.flush();
                        }
                    });
                }
            }
        });

        // 1. Spawn Stream A inside tauri::async_runtime::spawn_blocking
        let (stream_event_tx, stream_event_rx) = mpsc::channel::<StreamMessage>();
        let stream_handle = tauri::async_runtime::spawn_blocking(move || {
            perform_loopback_sse_stream(
                "127.0.0.1",
                port,
                "/api/chat/stream",
                "mock_token",
                None,
                |msg| {
                    let _ = stream_event_tx.send(msg);
                    Ok(())
                },
            )
        });

        // 2. Wait deterministically for Stream A to receive initial events
        let first_event = stream_event_rx.recv().expect("First event should arrive");
        assert_eq!(first_event.event, StreamEventType::Progress);
        let second_event = stream_event_rx.recv().expect("Second event should arrive");
        assert_eq!(second_event.event, StreamEventType::Delta);

        // 3. AT THIS EXACT MOMENT, Stream A is in-flight & blocked in loopback read.
        // Execute an ordinary loopback request:
        let ordinary_resp = perform_loopback_http_request(
            "127.0.0.1",
            port,
            "GET",
            "/api/health",
            "mock_token",
            None,
            None,
        );

        // Ordinary request must complete successfully WITHOUT waiting for Stream A to finish
        assert!(ordinary_resp.is_ok(), "Ordinary IPC request failed: {:?}", ordinary_resp);
        let resp_body = ordinary_resp.unwrap().body;
        assert!(resp_body.contains("\"busy\":false"));

        // 4. Authorize Stream A to complete
        release_stream_tx.send(()).expect("Should release stream");

        // 5. Stream A finishes and JoinHandle resolves with Ok(())
        let stream_result = tauri::async_runtime::block_on(stream_handle).expect("Task join error");
        assert!(stream_result.is_ok(), "Stream A should finish with Ok: {:?}", stream_result);

        let final_event = stream_event_rx.recv().expect("Final event should arrive");
        assert_eq!(final_event.event, StreamEventType::Complete);

        let _ = server_thread.join();
    }
}
