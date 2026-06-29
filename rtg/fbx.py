# -*- coding: utf-8 -*-
"""
Lector de FBX binario (sin dependencias externas).

Parsea el árbol completo de records (FBX >= 7500, offsets de 64 bits) y extrae
la malla lista para subir a la GPU: triángulos con posición, normal y UV por
vértice (no indexado), más la textura difusa embebida (PNG). El esqueleto, los
pesos de skinning y las curvas de animación también están en el árbol (este
lector ya los navega) y se añadirán al construir el skinning.

    from rtg.fbx import load_fbx
    m = load_fbx("Personaje.fbx")
    m["positions"]   # [x,y,z, x,y,z, ...]  (3 por vértice, no indexado)
    m["normals"]     # [nx,ny,nz, ...]
    m["uvs"]         # [u,v, ...]
    m["vertex_count"]
    m["diffuse_png"] # bytes PNG de la textura difusa (o None)
    m["bbox"]        # ((minx,miny,minz),(maxx,maxy,maxz))
"""
import os
import struct
import zlib

_HEADER = 27


class Node:
    __slots__ = ("name", "props", "children")

    def __init__(self, name):
        self.name = name
        self.props = []        # lista de propiedades (ver _read_props)
        self.children = []

    def find(self, name):
        for c in self.children:
            if c.name == name:
                return c
        return None

    def find_all(self, name):
        return [c for c in self.children if c.name == name]

    def array(self, fmt, esz):
        """Devuelve la 1ª propiedad-array decodificada (descomprime si hace falta)."""
        for p in self.props:
            if p[0] in "fdli b":
                _, al, enc, raw = p
                if enc == 1:
                    raw = zlib.decompress(raw)
                return struct.unpack(f"<{al}{fmt}", raw[:al * esz])
        return ()

    def string(self):
        for p in self.props:
            if p[0] == "S":
                return p[1].decode("ascii", "replace")
        return ""

    def raw(self):
        for p in self.props:
            if p[0] == "R":
                return p[1]
        return None


def _read_props(buf, p, n):
    props = []
    for _ in range(n):
        t = chr(buf[p]); p += 1
        if t in "YCIFDL":
            sz = {"Y": 2, "C": 1, "I": 4, "F": 4, "D": 8, "L": 8}[t]
            props.append((t, buf[p:p + sz])); p += sz
        elif t in "fdlib":
            al, enc, cl = struct.unpack("<III", buf[p:p + 12]); p += 12
            props.append((t, al, enc, buf[p:p + cl])); p += cl
        elif t in "SR":
            ln = struct.unpack("<I", buf[p:p + 4])[0]; p += 4
            props.append((t, buf[p:p + ln])); p += ln
        else:
            raise ValueError(f"propiedad FBX desconocida: {t!r}")
    return props, p


def _parse(buf, p, end):
    """Lee una lista de records hasta 'end'. Devuelve (nodos, pos_final)."""
    nodes = []
    while p < end - 13:
        eo, npr, _pll = struct.unpack("<QQQ", buf[p:p + 24])
        if eo == 0:
            return nodes, p + 25
        nl = buf[p + 24]
        node = Node(buf[p + 25:p + 25 + nl].decode("ascii", "replace"))
        pp = p + 25 + nl
        node.props, pp = _read_props(buf, pp, npr)
        if pp < eo:
            node.children, _ = _parse(buf, pp, eo)
        nodes.append(node)
        p = eo
    return nodes, p


def _parse_tree(path):
    data = open(path, "rb").read()
    if data[:20] != b"Kaydara FBX Binary  ":
        raise ValueError("no es un FBX binario")
    root = Node("__root__")
    root.children, _ = _parse(data, _HEADER, len(data))
    return root


def _diffuse_png(root):
    """Bytes PNG de la textura difusa embebida (Video > Content)."""
    objs = root.find("Objects")
    if not objs:
        return None
    best = None
    for v in objs.find_all("Video"):
        rel = v.find("RelativeFilename")
        name = rel.string() if rel else ""
        content = v.find("Content")
        blob = content.raw() if content else None
        if not blob:
            continue
        low = name.lower()
        if "diffuse" in low or "albedo" in low or "basecolor" in low:
            return blob               # exacta
        if best is None:
            best = blob               # cualquiera, por si no hay 'diffuse'
    return best


def load_fbx(path):
    root = _parse_tree(path)
    objs = root.find("Objects")
    geo = objs.find("Geometry") if objs else None
    if geo is None:
        raise ValueError("el FBX no tiene Geometry")

    verts = geo.find("Vertices").array("d", 8)
    idx = geo.find("PolygonVertexIndex").array("i", 4)

    # --- Normales ---
    normals = ()
    nmap = nref = ""
    ln = geo.find("LayerElementNormal")
    if ln:
        normals = ln.find("Normals").array("d", 8) if ln.find("Normals") else ()
        nmap = ln.find("MappingInformationType").string() if ln.find("MappingInformationType") else ""
        nref = ln.find("ReferenceInformationType").string() if ln.find("ReferenceInformationType") else ""

    # --- UVs ---
    uv = ()
    uvidx = ()
    umap = uref = ""
    lu = geo.find("LayerElementUV")
    if lu:
        uv = lu.find("UV").array("d", 8) if lu.find("UV") else ()
        uvidx = lu.find("UVIndex").array("i", 4) if lu.find("UVIndex") else ()
        umap = lu.find("MappingInformationType").string() if lu.find("MappingInformationType") else ""
        uref = lu.find("ReferenceInformationType").string() if lu.find("ReferenceInformationType") else ""

    def vpos(vi):
        return (verts[vi * 3], verts[vi * 3 + 1], verts[vi * 3 + 2])

    def vnormal(vi, pv):
        if not normals:
            return None
        j = pv if nmap == "ByPolygonVertex" else vi
        return (normals[j * 3], normals[j * 3 + 1], normals[j * 3 + 2])

    def vuv(vi, pv):
        if not uv:
            return (0.0, 0.0)
        if uref == "IndexToDirect" and uvidx:
            k = uvidx[pv]
        else:
            k = pv if umap == "ByPolygonVertex" else vi
        return (uv[k * 2], uv[k * 2 + 1])

    # --- Triangula (abanico). Cada polígono termina con índice negativo. ---
    positions, norms, uvs, cps = [], [], [], []
    poly = []           # (vertex_index, polygon_vertex_index)
    pv = 0
    for raw in idx:
        vi = raw if raw >= 0 else (-raw - 1)
        poly.append((vi, pv))
        pv += 1
        if raw < 0:
            for k in range(1, len(poly) - 1):
                for (cvi, cpv) in (poly[0], poly[k], poly[k + 1]):
                    p = vpos(cvi)
                    positions.extend(p)
                    n = vnormal(cvi, cpv)
                    norms.extend(n if n else (0.0, 1.0, 0.0))
                    u = vuv(cvi, cpv)
                    uvs.extend((u[0], 1.0 - u[1]))   # V invertida (convención GPU)
                    cps.append(cvi)                  # punto de control (para skinning)
            poly = []

    xs = verts[0::3]; ys = verts[1::3]; zs = verts[2::3]
    bbox = ((min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs)))
    return {
        "positions": positions,
        "normals": norms,
        "uvs": uvs,
        "cp_index": cps,
        "vertex_count": len(positions) // 3,
        "diffuse_png": _diffuse_png(root),
        "bbox": bbox,
    }


def export_mesh(fbx_path, out_prefix):
    """FBX -> '<out_prefix>.rmesh' (vértices intercalados) + '<out_prefix>.png'
    (textura difusa). Devuelve metadatos. Formato .rmesh (little-endian):
        u32 magic 'RMSH' · u32 vertex_count · luego N×(pos.xyz, nrm.xyz, uv.uv) f32."""
    import struct as _s
    m = load_fbx(fbx_path)
    n = m["vertex_count"]
    p, nr, u = m["positions"], m["normals"], m["uvs"]
    buf = bytearray()
    buf += _s.pack("<II", 0x48534D52, n)            # 'RMSH'
    pack = _s.Struct("<8f").pack
    for i in range(n):
        buf += pack(p[i * 3], p[i * 3 + 1], p[i * 3 + 2],
                    nr[i * 3], nr[i * 3 + 1], nr[i * 3 + 2],
                    u[i * 2], u[i * 2 + 1])
    with open(out_prefix + ".rmesh", "wb") as f:
        f.write(buf)
    if m["diffuse_png"]:
        with open(out_prefix + ".png", "wb") as f:
            f.write(m["diffuse_png"])
    return {"vertex_count": n, "bbox": m["bbox"], "has_texture": bool(m["diffuse_png"])}


# ============================================================================
#  Skinning + animación (Fase 6). Convención validada contra TransformLink:
#  local = Translate(T) @ (Rz·Ry·Rx)(grados) @ Scale(S)   [Euler FBX XYZ = ZYX]
# ============================================================================
_KTIME = 46186158000.0   # unidades de tiempo FBX por segundo


def _oid(n):
    for p in n.props:
        if p[0] == "L":
            return struct.unpack("<q", p[1])[0]
    return None


def _props70(n):
    d = {}
    pp = n.find("Properties70")
    if pp:
        for p in pp.children:
            if p.name == "P" and p.props and p.props[0][0] == "S":
                k = p.props[0][1].decode("ascii", "replace")
                d[k] = [struct.unpack("<d", x[1])[0] for x in p.props if x[0] == "D"]
    return d


def _euler_zyx(rx, ry, rz):
    import numpy as np
    rx, ry, rz = np.radians([rx, ry, rz])
    cx, sx = np.cos(rx), np.sin(rx)
    cy, sy = np.cos(ry), np.sin(ry)
    cz, sz = np.cos(rz), np.sin(rz)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


def export_skinned(fbx_path, prefix):
    """FBX riggeado -> '<prefix>.rmesh' (pos,nrm,uv,4 huesos,4 pesos = 64 B/vért)
    + '<prefix>.png' (difusa) + '<prefix>.ranim' (matrices de skin por frame).
    Devuelve metadatos. Si el FBX no tiene skin, cae a export_mesh."""
    import numpy as np
    root = _parse_tree(fbx_path)
    objs = root.find("Objects")
    conns = root.find("Connections")
    geo = objs.find("Geometry") if objs else None
    if geo is None:
        raise ValueError("sin Geometry")

    # --- conexiones ---
    oo, op = [], []
    for c in conns.children:
        if c.name == "C" and c.props and c.props[0][0] == "S":
            kind = c.props[0][1]
            ch = struct.unpack("<q", c.props[1][1])[0]
            pa = struct.unpack("<q", c.props[2][1])[0]
            if kind == b"OO":
                oo.append((ch, pa))
            elif kind == b"OP":
                nm = c.props[3][1].decode("ascii", "replace") if len(c.props) > 3 else ""
                op.append((ch, pa, nm))

    models = {_oid(m): m for m in objs.find_all("Model")}
    clusters = [d for d in objs.find_all("Deformer")
                if any(p[0] == "S" and b"Cluster" in p[1] for p in d.props)]
    if not clusters:
        meta = export_mesh(fbx_path, prefix)
        meta["animated"] = False
        return meta

    # bone (Model) -> cluster (parent);  bone -> parent bone
    bone_ids = list(models.keys())
    cl_ids = {_oid(c) for c in clusters}
    cl2bone = {pa: ch for (ch, pa) in oo if ch in models and pa in cl_ids}
    boneparent = {}
    for ch, pa in oo:
        if ch in models and pa in models:
            boneparent.setdefault(ch, pa)
    # solo huesos que deforman (los que están en un cluster) + sus ancestros
    used = set(cl2bone.values())
    for b in list(used):
        p = boneparent.get(b)
        while p in models and p not in used:
            used.add(p)
            p = boneparent.get(p)
    bones = [b for b in bone_ids if b in used]
    bidx = {b: i for i, b in enumerate(bones)}
    B = len(bones)

    # bind global (TransformLink) e inversa, por hueso
    bind = [np.eye(4) for _ in range(B)]
    invbind = [np.eye(4) for _ in range(B)]
    for cl in clusters:
        bone = cl2bone.get(_oid(cl))
        if bone not in bidx:
            continue
        tl = cl.find("TransformLink")
        if tl:
            TL = np.array(tl.array("d", 8)).reshape(4, 4).T
            bind[bidx[bone]] = TL
            invbind[bidx[bone]] = np.linalg.inv(TL)

    # rest local (T, pre, S) por hueso
    rest = []
    for b in bones:
        d = _props70(models[b])
        rest.append((d.get("Lcl Translation", [0, 0, 0]),
                     d.get("PreRotation", [0, 0, 0]),
                     d.get("Lcl Scaling", [1, 1, 1])))

    # --- curvas de animación: bone -> canal -> componente -> (times, vals) ---
    curvenodes = {_oid(n): n for n in objs.find_all("AnimationCurveNode")}
    curves = {_oid(n): n for n in objs.find_all("AnimationCurve")}
    # animcurvenode -> (bone, propiedad)
    node2bone = {}
    for ch, pa, nm in op:
        if ch in curvenodes and pa in models:
            node2bone[ch] = (pa, nm)
    # curve -> (node, componente d|X/Y/Z)
    # bone -> {"R": {0:(t,v),1:,2:}, "T": {...}}
    anim = {b: {"R": {}, "T": {}} for b in bones}
    for ch, pa, nm in op:
        if ch in curves and pa in curvenodes and pa in node2bone:
            bone, prop = node2bone[pa]
            if bone not in bidx:
                continue
            comp = {"d|X": 0, "d|Y": 1, "d|Z": 2}.get(nm)
            if comp is None:
                continue
            cv = curves[ch]
            kt = cv.find("KeyTime")
            kv = cv.find("KeyValueFloat")
            if not kt or not kv:
                continue
            times = np.array(kt.array("q", 8), dtype=np.float64) / _KTIME
            vals = np.array(kv.array("f", 4), dtype=np.float64)
            chan = "R" if "Rotation" in prop else ("T" if "Translation" in prop else None)
            if chan:
                anim[bone][chan][comp] = (times, vals)

    # rango temporal y frames (30 fps)
    tmin, tmax = 1e18, -1e18
    for b in bones:
        for chan in ("R", "T"):
            for comp in anim[b][chan].values():
                tmin = min(tmin, comp[0][0])
                tmax = max(tmax, comp[0][-1])
    if tmax <= tmin:
        tmin, tmax = 0.0, 0.0
    fps = 30.0
    F = max(int(round((tmax - tmin) * fps)) + 1, 1)

    # huesos raíz (sin padre hueso). Por defecto se CONSERVA el root motion
    # (el personaje se desplaza con la animación). RTG_INPLACE lo anula
    # (trote en el sitio) si se prefiere.
    root_bones = {i for i, b in enumerate(bones) if boneparent.get(b) not in models}
    in_place = os.environ.get("RTG_INPLACE") is not None

    def sample(b, chan, comp, t, default):
        c = anim[b][chan].get(comp)
        if c is None:
            return default
        return float(np.interp(t, c[0], c[1]))

    def local_at(i, t):
        Tr, pre, S = rest[i]
        b = bones[i]
        if in_place and i in root_bones:
            tx, ty, tz = Tr[0], Tr[1], Tr[2]          # raíz: traslación de reposo
        else:
            tx = sample(b, "T", 0, t, Tr[0]); ty = sample(b, "T", 1, t, Tr[1]); tz = sample(b, "T", 2, t, Tr[2])
        rx = sample(b, "R", 0, t, 0.0); ry = sample(b, "R", 1, t, 0.0); rz = sample(b, "R", 2, t, 0.0)
        Rpre = _euler_zyx(*pre)
        Ranim = _euler_zyx(rx, ry, rz)
        L = np.eye(4)
        L[:3, :3] = Rpre @ Ranim @ np.diag(S)
        L[:3, 3] = [tx, ty, tz]
        return L

    # --- hornea matrices de skin por frame ---
    skin = np.zeros((F, B, 16), dtype=np.float32)
    for fi in range(F):
        t = tmin + fi / fps
        glob = [None] * B
        for i in range(B):
            L = local_at(i, t)
            pa = boneparent.get(bones[i])
            pidx = bidx.get(pa)
            glob[i] = (glob[pidx] @ L) if (pidx is not None and glob[pidx] is not None) else L
        for i in range(B):
            M = (glob[i] @ invbind[i]).astype(np.float32)
            skin[fi, i] = M.T.flatten()      # column-major para WGSL

    # --- pesos por punto de control (top 4) ---
    nverts_cp = len(geo.find("Vertices").array("d", 8)) // 3
    cp_w = [[] for _ in range(nverts_cp)]
    for cl in clusters:
        bone = cl2bone.get(_oid(cl))
        if bone not in bidx:
            continue
        idxs = cl.find("Indexes")
        wts = cl.find("Weights")
        if not idxs or not wts:
            continue
        ii = idxs.array("i", 4)
        ww = wts.array("d", 8)
        bi = bidx[bone]
        for k in range(min(len(ii), len(ww))):
            if 0 <= ii[k] < nverts_cp:
                cp_w[ii[k]].append((ww[k], bi))
    cp_bi = np.zeros((nverts_cp, 4), dtype=np.uint32)
    cp_wt = np.zeros((nverts_cp, 4), dtype=np.float32)
    for v in range(nverts_cp):
        top = sorted(cp_w[v], reverse=True)[:4]
        s = sum(w for w, _ in top) or 1.0
        for j, (w, b) in enumerate(top):
            cp_bi[v, j] = b
            cp_wt[v, j] = w / s
        if not top:
            cp_wt[v, 0] = 1.0

    # --- geometría triangulada + cp por vértice de salida ---
    g = load_fbx(fbx_path)
    cvis = g["cp_index"]
    pos, nrm, uvs = g["positions"], g["normals"], g["uvs"]
    n = g["vertex_count"]

    # --- escribe .rmesh (64 B/vértice) ---
    out = bytearray()
    out += struct.pack("<II", 0x324D5352, n)   # 'RSM2' (con skin)
    vp = struct.Struct("<8f").pack
    for i in range(n):
        cp = cvis[i]
        out += vp(pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2],
                  nrm[i * 3], nrm[i * 3 + 1], nrm[i * 3 + 2],
                  uvs[i * 2], uvs[i * 2 + 1])
        out += struct.pack("<4I", *cp_bi[cp])
        out += struct.pack("<4f", *cp_wt[cp])
    with open(prefix + ".rmesh", "wb") as f:
        f.write(out)

    # --- escribe .ranim ---
    an = bytearray()
    an += struct.pack("<IIIf", 0x4D4E4152, F, B, fps)   # 'RANM'
    an += skin.tobytes()
    with open(prefix + ".ranim", "wb") as f:
        f.write(an)

    if g["diffuse_png"]:
        with open(prefix + ".png", "wb") as f:
            f.write(g["diffuse_png"])
    return {"vertex_count": n, "bones": B, "frames": F, "fps": fps,
            "has_texture": bool(g["diffuse_png"]), "animated": F > 1}


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("uso: python -m rtg.fbx <entrada.fbx> <prefijo_salida>")
        sys.exit(1)
    meta = export_skinned(sys.argv[1], sys.argv[2])
    print(f"exportado: {meta['vertex_count']} vértices · {meta.get('bones',0)} huesos "
          f"· {meta.get('frames',1)} frames · textura: {'sí' if meta['has_texture'] else 'no'}")
