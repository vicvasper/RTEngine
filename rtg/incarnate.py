# -*- coding: utf-8 -*-
"""
Fase 4 — La Puerta: ENCARNACIÓN de assets externos.

Un modelo importado (malla OBJ) es un "préstamo": hay que naturalizarlo a la
representación nativa del motor (un campo de distancia, SDF). Etapas (como en el
manual): Validator (validar) -> Measure (normalizar ejes/escala) -> Incarnation
(hornear a campo). El resultado es un volumen de distancias que el raymarcher
sabe dibujar igual que un node analítico.

Distancia sin signo: punto-a-triángulo (Ericson). Signo: número de giro
generalizado (robusto, también con mallas no perfectas).

CLI:  python -m rtg.incarnate modelo.obj  [resolucion]
"""
import json
import os
import sys

import numpy as np

# ----------------------------------------------------------------------------
# Ingesta y validación
# ----------------------------------------------------------------------------
def parse_obj(path):
    """Lee vértices y caras de un .obj (triangula polígonos en abanico)."""
    verts, faces = [], []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.startswith("v "):
                p = line.split()
                verts.append([float(p[1]), float(p[2]), float(p[3])])
            elif line.startswith("f "):
                idx = []
                for tok in line.split()[1:]:
                    i = int(tok.split("/")[0])
                    idx.append(i - 1 if i > 0 else len(verts) + i)
                for k in range(1, len(idx) - 1):
                    faces.append([idx[0], idx[k], idx[k + 1]])
    return np.array(verts, dtype=np.float64), np.array(faces, dtype=np.int64)


def validate(verts, faces):
    """Validator: informe básico de la malla."""
    a, b, c = verts[faces[:, 0]], verts[faces[:, 1]], verts[faces[:, 2]]
    areas = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    return {
        "vertices": int(len(verts)),
        "triangulos": int(len(faces)),
        "degenerados": int(np.sum(areas < 1e-9)),
        "bbox_min": verts.min(axis=0).round(4).tolist(),
        "bbox_max": verts.max(axis=0).round(4).tolist(),
    }


def normalize(verts, padding=1.2):
    """Measure: centra en el origen y escala para caber en [-1, 1]."""
    center = (verts.min(axis=0) + verts.max(axis=0)) * 0.5
    v = verts - center
    radius = np.linalg.norm(v, axis=1).max()
    scale = 1.0 / (radius * padding)
    return v * scale, center.tolist(), float(scale)


# ----------------------------------------------------------------------------
# Incarnation: hornear a campo de distancia
# ----------------------------------------------------------------------------
def _closest_on_tri(P, a, b, c):
    """Punto más cercano del triángulo abc a cada punto de P (Ericson)."""
    ab, ac = b - a, c - a
    ap = P - a
    d1, d2 = ap @ ab, ap @ ac
    bp = P - b
    d3, d4 = bp @ ab, bp @ ac
    cp = P - c
    d5, d6 = cp @ ab, cp @ ac

    va = d3 * d6 - d5 * d4
    vb = d5 * d2 - d1 * d6
    vc = d1 * d4 - d3 * d2
    denom = 1.0 / np.where((va + vb + vc) != 0, va + vb + vc, 1.0)
    v_f = vb * denom
    w_f = vc * denom
    out = a + v_f[:, None] * ab + w_f[:, None] * ac  # región interior (cara)

    # aristas
    m_ab = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
    t_ab = np.where((d1 - d3) != 0, d1 / (d1 - d3), 0.0)
    out[m_ab] = (a + t_ab[:, None] * ab)[m_ab]
    m_ac = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
    t_ac = np.where((d2 - d6) != 0, d2 / (d2 - d6), 0.0)
    out[m_ac] = (a + t_ac[:, None] * ac)[m_ac]
    m_bc = (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)
    t_bc = np.where(((d4 - d3) + (d5 - d6)) != 0,
                    (d4 - d3) / ((d4 - d3) + (d5 - d6)), 0.0)
    out[m_bc] = (b + t_bc[:, None] * (c - b))[m_bc]

    # vértices (máxima prioridad)
    out[(d1 <= 0) & (d2 <= 0)] = a
    out[(d3 >= 0) & (d4 <= d3)] = b
    out[(d6 >= 0) & (d5 <= d6)] = c
    return out


def _winding(P, V, F):
    """Número de giro generalizado (signo dentro/fuera) en cada punto de P."""
    w = np.zeros(len(P))
    for tri in F:
        a = V[tri[0]] - P
        b = V[tri[1]] - P
        c = V[tri[2]] - P
        la = np.linalg.norm(a, axis=1)
        lb = np.linalg.norm(b, axis=1)
        lc = np.linalg.norm(c, axis=1)
        det = np.einsum("ij,ij->i", a, np.cross(b, c))
        denom = (la * lb * lc
                 + np.einsum("ij,ij->i", a, b) * lc
                 + np.einsum("ij,ij->i", a, c) * lb
                 + np.einsum("ij,ij->i", b, c) * la)
        w += 2.0 * np.arctan2(det, denom)   # ángulo sólido firmado del triángulo
    return w / (4.0 * np.pi)                # número de giro: ~±1 dentro, ~0 fuera


def bake_sdf(V, F, res=48):
    """Hornea un campo de distancia firmado en una rejilla res^3 sobre [-1,1]."""
    lin = np.linspace(-1.0, 1.0, res)
    gx, gy, gz = np.meshgrid(lin, lin, lin, indexing="ij")
    P = np.stack([gx.ravel(), gy.ravel(), gz.ravel()], axis=1)

    dist = np.full(len(P), 1e9)
    for tri in F:
        d = np.linalg.norm(P - _closest_on_tri(P, V[tri[0]], V[tri[1]], V[tri[2]]), axis=1)
        dist = np.minimum(dist, d)

    # |winding| ~1 dentro, ~0 fuera: el abs lo hace robusto a la orientación.
    inside = np.abs(_winding(P, V, F)) > 0.5
    sign = np.where(inside, -1.0, 1.0)
    return (dist * sign).reshape(res, res, res).astype(np.float32)


def incarnate(obj_path, res=48, out_dir=None):
    """Pipeline completo: importar -> validar -> normalizar -> hornear -> guardar."""
    verts, faces = parse_obj(obj_path)
    report = validate(verts, faces)
    nverts, center, scale = normalize(verts)
    sdf = bake_sdf(nverts, faces, res)

    name = os.path.splitext(os.path.basename(obj_path))[0]
    out_dir = out_dir or os.path.dirname(os.path.abspath(obj_path))
    sdf_path = os.path.join(out_dir, name + ".sdf")
    meta_path = os.path.join(out_dir, name + ".sdf.json")
    # La textura 3D de la GPU espera x como índice más rápido (luego y, luego z).
    # bake_sdf devuelve [x][y][z] (C-order: z el más rápido) -> transponemos.
    sdf.transpose(2, 1, 0).copy().tofile(sdf_path)  # raw f32, orden GPU
    meta = {
        "name": name, "resolution": res, "bounds": [-1.0, 1.0],
        "source_center": center, "source_scale": scale, "report": report,
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    return sdf, meta


def main():
    if len(sys.argv) < 2:
        print("uso: python -m rtg.incarnate <modelo.obj> [resolucion]")
        sys.exit(1)
    res = int(sys.argv[2]) if len(sys.argv) > 2 else 48
    _, meta = incarnate(sys.argv[1], res)
    r = meta["report"]
    print(f"Encarnado '{meta['name']}'  ->  campo {res}^3")
    print(f"  malla: {r['vertices']} vértices, {r['triangulos']} triángulos, "
          f"{r['degenerados']} degenerados")
    print(f"  bbox origen: {r['bbox_min']} .. {r['bbox_max']}")
    print(f"  guardado: {meta['name']}.sdf (+ .json)")


if __name__ == "__main__":
    main()
