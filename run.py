# -*- coding: utf-8 -*-
"""
CLI de la Fase 0: compila un archivo .node, muestra el bytecode y ejecuta una
pequeña demostración en CPU que prueba que el forma genera comportamiento.

Uso:
    python run.py examples/start.node
"""
import sys
import os

# La consola de Windows usa cp1252 por defecto; forzamos UTF-8 para los acentos.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rtg import build, disassemble  # noqa: E402
from rtg.friendly import build_friendly  # noqa: E402


def main(path):
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()

    # .scene = capa de usuario;  .node = núcleo interno
    if path.endswith(".node"):
        module, behaviors = build(src)
    else:
        module, behaviors = build_friendly(src)

    print("=" * 68)
    print(f"  RTGEngine · Fase 0 — compilado: {os.path.basename(path)}")
    print("=" * 68)
    print(disassemble(module))
    print()

    # Demostración: ¿el caminante se mueve? ¿el candil ilumina?
    print("; --- demostración en CPU (la conjugación produce conducta) ---")
    for b in behaviors:
        tag = b.family.upper()
        if b.family == "locomotion":
            p0 = b.center(0.0)
            p2 = b.center(2.0)
            moved = abs(p2[0] - p0[0]) > 1e-9
            print(f"[{tag:11}] {b.name:<8} centro t=0 -> {fmt(p0)}   "
                  f"t=2 -> {fmt(p2)}   {'SE MUEVE' if moved else 'estático'}")
        elif b.is_light:
            L = b.light
            print(f"[{tag:11}] {b.name:<8} EMITE LUZ  "
                  f"{L.lumens:.0f} lm · {L.kelvin:.0f} K · r={L.radius:.1f} m")
        else:
            d = b.sdf((1.0, 0.0, 0.0), 0.0)
            print(f"[{tag:11}] {b.name:<8} estático · sdf(1,0,0)={d:+.3f}")

    print()
    # Un perfil de distancia 1D del caminante a lo largo del tiempo
    walker = next((b for b in behaviors if b.family == "locomotion"), None)
    if walker:
        print("; perfil: distancia del origen al caminante según avanza el tiempo")
        for t in [0.0, 0.5, 1.0, 1.5, 2.0]:
            d = walker.sdf((0.0, 0.0, 0.0), t)
            bar = "#" * max(0, int(d * 10))
            print(f"  t={t:>3} · d={d:5.2f} |{bar}")


def fmt(v):
    return f"({v[0]:+.2f},{v[1]:+.2f},{v[2]:+.2f})"


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "examples", "start.node")
    main(target)
