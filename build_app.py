# -*- coding: utf-8 -*-
"""
Empaqueta RTGEngine en un .exe sin consola con PyInstaller.

    python build_app.py

Produce:  dist/RTGEngine/RTGEngine.exe   (editor, sin consola)
          dist/RTGEngine/rtg-core.exe    (motor, sin consola)
          dist/RTGEngine/engine/examples/...

Requisitos:  pip install pyinstaller   y el motor compilado en release
             (cd rtg-core && cargo build --release).
"""
import os
import shutil
import subprocess
import sys

ENGINE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.join(ENGINE, "rtg-core")
ENGINE_EXE = os.path.join(CORE, "target", "release", "rtg-core.exe")
DIST = os.path.join(ENGINE, "dist", "RTGEngine")


def main():
    if not os.path.exists(ENGINE_EXE):
        sys.exit("Falta el motor: cd rtg-core && cargo build --release")
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        sys.exit("Falta PyInstaller:  pip install pyinstaller")

    # 1) Empaqueta el editor (one-dir, sin consola). El paquete rtg va dentro.
    cmd = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--name", "RTGEngine", "--windowed",
        "--paths", ENGINE,
        "--collect-submodules", "rtg",
        os.path.join(ENGINE, "studio.py"),
    ]
    print(">>", " ".join(cmd))
    subprocess.run(cmd, cwd=ENGINE, check=True)

    # 2) Copia el motor junto al editor y los ejemplos a engine/examples.
    shutil.copy2(ENGINE_EXE, os.path.join(DIST, "rtg-core.exe"))
    ex_dst = os.path.join(DIST, "engine", "examples")
    os.makedirs(ex_dst, exist_ok=True)
    src_ex = os.path.join(ENGINE, "examples")
    for fn in os.listdir(src_ex):
        if fn.endswith((".scene", ".md", ".obj")):
            shutil.copy2(os.path.join(src_ex, fn), os.path.join(ex_dst, fn))

    print("\nOK ->", os.path.join(DIST, "RTGEngine.exe"))


if __name__ == "__main__":
    main()
