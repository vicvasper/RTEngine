// Lanzador nativo de RTGEngine — abre el editor SIN ventana de consola.
// windows_subsystem="windows" => el propio lanzador no tiene consola; y arranca
// el editor con pythonw (también sin consola). Doble clic y listo.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::path::PathBuf;
use std::process::Command;

fn main() {
    let exe = std::env::current_exe().unwrap_or_default();
    let dir = exe
        .parent()
        .map(|p| p.to_path_buf())
        .unwrap_or_else(|| PathBuf::from("."));

    // Busca studio.py junto al .exe o en ./engine (según cómo se distribuya).
    let candidates = [
        dir.join("studio.py"),
        dir.join("engine").join("studio.py"),
    ];
    let (script, cwd) = candidates
        .iter()
        .find(|p| p.exists())
        .map(|p| (p.clone(), p.parent().unwrap().to_path_buf()))
        .unwrap_or((dir.join("studio.py"), dir.clone()));

    // pythonw = Python sin consola; si no está, cae a python.
    for py in ["pythonw.exe", "pythonw", "python.exe", "python"] {
        if Command::new(py)
            .arg(&script)
            .current_dir(&cwd)
            .spawn()
            .is_ok()
        {
            return;
        }
    }
}
