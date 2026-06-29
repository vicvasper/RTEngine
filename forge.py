# -*- coding: utf-8 -*-
"""
forge.py — "forjar" la escena del motor a partir de una frase del idioma.

Compila un archivo .node y escribe el WGSL de la escena donde el núcleo nativo
lo espera (rtg-core/src/scene.generated.wgsl).

    python forge.py examples/start.node

Después:  cd rtg-core && cargo run --release
"""
import os
import sys

ENGINE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ENGINE)

from rtg.codegen import emit_wgsl, scene_objects  # noqa: E402
from rtg import build  # noqa: E402
from rtg.friendly import build_friendly  # noqa: E402

OUT = os.path.join(ENGINE, "rtg-core", "src", "scene.generated.wgsl")
OBJ = os.path.join(ENGINE, "rtg-core", "src", "scene.objects.txt")


def write_objects(behaviors):
    """Sidecar con la posición inicial de cada objeto (índice = mat-1).
    El motor lo lee para sembrar Obj.pos[] y escribe de vuelta scene.live.txt
    cuando mueves un objeto con el gizmo."""
    lines = []
    for i, (name, x, y, z, size, kind) in enumerate(scene_objects(behaviors)):
        lines.append(f"{i} {x:.5f} {y:.5f} {z:.5f} {size:.5f} {kind} {name}")
    tmp = OBJ + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + ("\n" if lines else ""))
    os.replace(tmp, OBJ)


def main():
    src_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        ENGINE, "examples", "start.scene")
    with open(src_path, "r", encoding="utf-8") as f:
        src = f.read()

    # Autodetección: .scene = capa de usuario; .node = núcleo
    if src_path.endswith(".node"):
        _, behaviors = build(src)
        capa = "núcleo interno (.node)"
    else:
        _, behaviors = build_friendly(src)
        capa = "capa de usuario (.scene)"

    wgsl = emit_wgsl(behaviors)
    # Escritura atómica: el motor (hot-reload) nunca ve un archivo a medias.
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(wgsl)
    os.replace(tmp, OUT)
    write_objects(behaviors)
    print(f"Escena forjada [{capa}] desde {os.path.basename(src_path)} -> {OUT}")


if __name__ == "__main__":
    main()
