// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::TcpStream;
use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::Manager;

#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;

struct BackendProcessState {
    child: Mutex<Option<Child>>,
}

fn is_backend_healthy() -> bool {
    // Quick TCP probe to 127.0.0.1:8765
    if let Ok(_stream) = TcpStream::connect_timeout(
        &"127.0.0.1:8765".parse().unwrap(),
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

fn spawn_backend_if_needed() -> Option<Child> {
    if is_backend_healthy() {
        println!("Backend already running and healthy on 127.0.0.1:8765");
        return None;
    }

    let root_dir = find_project_root();
    let server_script = root_dir.join("app_api").join("server.py");

    println!("Starting backend process from: {:?}", root_dir);

    let mut cmd = Command::new("python");
    cmd.arg(&server_script)
        .current_dir(&root_dir);

    #[cfg(target_os = "windows")]
    {
        const CREATE_NO_WINDOW: u32 = 0x08000000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    match cmd.spawn() {
        Ok(child) => {
            println!("Spawned backend process with PID: {}", child.id());

            // Wait up to 6 seconds for backend port to become responsive
            let start = Instant::now();
            while start.elapsed() < Duration::from_secs(6) {
                if is_backend_healthy() {
                    println!("Backend is ready and listening on 127.0.0.1:8765");
                    break;
                }
                std::thread::sleep(Duration::from_millis(100));
            }

            Some(child)
        }
        Err(e) => {
            eprintln!("Failed to spawn backend python process: {}", e);
            None
        }
    }
}

fn main() {
    let child_process = spawn_backend_if_needed();

    let app = tauri::Builder::default()
        .manage(BackendProcessState {
            child: Mutex::new(child_process),
        })
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
