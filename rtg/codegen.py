# -*- coding: utf-8 -*-
"""
Codegen RTGEngine -> WGSL (Fase 2: "La Frase").

Toma una frase del idioma (un archivo .node), la compila con la Fase 0 y
emite el fragmento de shader 'scene.generated.wgsl' que el motor nativo carga
en tiempo de ejecución. Así, editar el .node reconstruye la escena SIN tocar
ni recompilar el código Rust.

El WGSL generado define tres cosas que el núcleo (core.wgsl) consume:
    fn scene_sdf(p, t) -> vec2<f32>   // (distancia, id de material)
    fn mat_color(id)   -> vec3<f32>   // color por material
    const LIGHT_POS / LIGHT_COL       // primera luz (Emitter + luminaria)
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rtg import build  # noqa: E402
from rtg.evaluator import (  # noqa: E402
    FAM_LOCOMOTION, FAM_LUMINARY, FAM_SOLID, FAM_STRUCTURE, FAM_FLUID,
    FAM_SCATTER, FAM_MESH, FAM_ASSET,
)

# Color base por familia (Appearance por defecto; un parámetro 'color' podrá
# sobrescribirlo en el futuro).
FAMILY_COLOR = {
    FAM_LOCOMOTION: (0.30, 0.85, 0.55),   # verde néfesh
    FAM_SOLID:      (0.82, 0.80, 0.78),   # piedra
    FAM_STRUCTURE:  (0.70, 0.66, 0.60),   # construido
    FAM_FLUID:      (0.20, 0.50, 0.80),   # agua
    FAM_SCATTER:    (0.50, 0.70, 0.40),   # vegetación
}
GROUND_COLOR = (0.20, 0.20, 0.24)
GROUND_Y = -1.0

# Colores con nombre que el usuario puede poner con 'color <nombre>'.
COLOR_MAP = {
    "red": (0.80, 0.12, 0.12),    "green": (0.20, 0.70, 0.25),
    "blue": (0.15, 0.30, 0.85),   "white": (0.90, 0.90, 0.92),
    "black": (0.05, 0.05, 0.06),  "yellow": (0.90, 0.80, 0.15),
    "orange": (0.95, 0.45, 0.10), "purple": (0.55, 0.20, 0.75),
    "cyan": (0.15, 0.75, 0.80),   "grey": (0.55, 0.55, 0.58),
    "gray": (0.55, 0.55, 0.58),   "brown": (0.45, 0.28, 0.15),
}


def _f(x):
    """Formatea un float como literal WGSL (siempre con punto decimal)."""
    return f"{float(x):.5f}"


def _v3(t):
    return f"vec3<f32>({_f(t[0])}, {_f(t[1])}, {_f(t[2])})"


def kelvin_to_rgb(k):
    """Aproximación de Planck (Tanner Helland) temperatura -> RGB [0,1]."""
    t = k / 100.0
    # rojo
    if t <= 66:
        r = 255.0
    else:
        r = 329.698727446 * ((t - 60) ** -0.1332047592)
    # verde
    if t <= 66:
        g = 99.4708025861 * math.log(max(t, 1e-3)) - 161.1195681661
    else:
        g = 288.1221695283 * ((t - 60) ** -0.0755148492)
    # azul
    if t >= 66:
        b = 255.0
    elif t <= 19:
        b = 0.0
    else:
        b = 138.5177312231 * math.log(max(t - 10, 1e-3)) - 305.0447927307

    clamp = lambda v: max(0.0, min(255.0, v)) / 255.0
    return (clamp(r), clamp(g), clamp(b))


def generate_wgsl(src: str) -> str:
    """Compila una frase en interno (.node) y emite el WGSL de la escena."""
    _, behaviors = build(src)
    return emit_wgsl(behaviors)


def emit_wgsl(behaviors) -> str:
    """Emite el WGSL de la escena a partir de los Behaviors ya resueltos.
    Sirve igual al idioma interno interno y a la capa de usuario amigable."""
    geom_blocks = []     # bloques de scene_sdf
    color_arms = []      # ramas de mat_color
    reflect_arms = []    # ramas de mat_reflect (reflectividad, Fase 5)
    rough_arms = []      # ramas de mat_rough (rugosidad PBR, Fase 5)
    metal_arms = []      # ramas de mat_metal (metalicidad PBR, Fase 5)
    lights = []          # luces encontradas
    mat_id = 1           # 0 reservado para el suelo
    light_mat = -1.0     # id de material de la bombilla (para que sea emisiva)
    light_obj_idx = -1   # índice de objeto de la luz (para que las sombras la sigan)

    for b in behaviors:
        if b.is_light:
            lights.append(b)
        # ¿tiene cuerpo visible? (las luciérnagas/luz también dibujan su bombilla)
        if b.family == FAM_LUMINARY and not b.is_light:
            continue  # luminaria sin emitir: sin cuerpo propio en esta fase

        idx = mat_id - 1            # índice en Obj.pos[] (posición en runtime)
        # Importados (malla/asset): NO generan SDF, pero ocupan un índice de
        # objeto para que el gizmo los mueva (su posición vive en Obj.pos[idx]).
        if b.family in (FAM_MESH, FAM_ASSET):
            mat_id += 1
            continue
        center_expr = _center_wgsl(b, idx)
        if b.family == FAM_FLUID:
            sd = f"sd_plane(p, Obj.pos[{idx}].y)"
        elif b.family == FAM_STRUCTURE:
            sd = f"sd_box(p, {center_expr}, vec3<f32>({_f(b.size)}))"
        elif b.family == FAM_LUMINARY:
            sd = f"sd_sphere(p, {center_expr}, {_f(max(b.size * 0.3, 0.08))})"
        else:  # locomotion, solid, scatter, default
            r = 0.15 if b.family == FAM_SCATTER else b.size
            sd = f"sd_sphere(p, {center_expr}, {_f(r)})"

        geom_blocks.append(
            f"    // {b.name}  ·  familia={b.family}  ·  mat={mat_id}\n"
            f"    {{ let dd = {sd}; if (dd < d) {{ d = dd; mat = {_f(mat_id)}; }} }}"
        )

        if b.is_light:
            color = b.light and kelvin_to_rgb(b.light.kelvin) or (1.0, 1.0, 1.0)
            light_mat = float(mat_id)   # esta bombilla brillará (emisiva)
            if light_obj_idx < 0:
                light_obj_idx = idx     # la luz seguirá a este objeto al moverlo
        else:
            cname = str(b.params.get("color", "")).lower()
            color = COLOR_MAP.get(cname, FAMILY_COLOR.get(b.family, (0.8, 0.8, 0.8)))
        color_arms.append(
            f"    if (id < {_f(mat_id + 0.5)}) {{ return {_v3(color)}; }}"
        )
        shiny = float(b.params.get("shiny", 0.0))
        reflect_arms.append(
            f"    if (id < {_f(mat_id + 0.5)}) {{ return {_f(shiny)}; }}"
        )
        # PBR: rugosidad (0=espejo, 1=mate) y metalicidad (0=dieléctrico, 1=metal).
        # 'shiny' baja la rugosidad por defecto; 'rough'/'metal' la fijan a mano.
        rough = float(b.params.get("rough", max(0.18, 0.6 - 0.5 * shiny)))
        metal = float(b.params.get("metal", 0.0))
        rough_arms.append(
            f"    if (id < {_f(mat_id + 0.5)}) {{ return {_f(rough)}; }}"
        )
        metal_arms.append(
            f"    if (id < {_f(mat_id + 0.5)}) {{ return {_f(metal)}; }}"
        )
        mat_id += 1

    # Luz: la primera Emitter-luminaria; si no hay, una luz por defecto.
    if lights:
        lp = lights[0].place
        lc = kelvin_to_rgb(lights[0].light.kelvin)
        # 'brightness' (lúmenes) -> intensidad. Ahora SÍ afecta al render.
        light_int = max(lights[0].light.lumens, 1.0) / 250.0
        light_r = max(lights[0].size * 0.3, 0.08)  # radio de la bombilla (área de luz)
        light_comment = (f"// luz de '{lights[0].name}' "
                         f"({lights[0].light.kelvin:.0f} K, {lights[0].light.lumens:.0f} lm)")
    else:
        lp = (3.0, 5.0, 2.0)
        lc = (1.0, 0.95, 0.9)
        light_int = 2.0
        light_r = 0.2
        light_comment = "// sin luminaria en la frase: luz por defecto"

    out = []
    out.append("// ===========================================================")
    out.append("//  AUTO-GENERADO por rtg/codegen.py desde una frase .node")
    out.append("//  NO EDITAR A MANO. Regenera con:  python forge.py <archivo>")
    out.append("// ===========================================================")
    out.append("")
    if light_obj_idx >= 0:
        out.append(f"fn light_pos() -> vec3<f32> {{ return Obj.pos[{light_obj_idx}].xyz; }}  {light_comment}")
    else:
        out.append(f"fn light_pos() -> vec3<f32> {{ return {_v3(lp)}; }}  {light_comment}")
    out.append(f"const LIGHT_COL : vec3<f32> = {_v3(lc)};")
    out.append(f"const LIGHT_INT : f32 = {_f(light_int)};   // intensidad (de brightness)")
    out.append(f"const LIGHT_MAT : f32 = {_f(light_mat)};   // material emisivo (la bombilla)")
    out.append(f"const LIGHT_R : f32 = {_f(light_r)};   // radio de la lámpara (área -> sombras suaves)")
    out.append("")
    out.append("// La frase: el campo de distancia de toda la escena.")
    out.append("// Devuelve (distancia, id de material).")
    out.append("fn scene_sdf(p : vec3<f32>, t : f32) -> vec2<f32> {")
    out.append("    var d = 1e9;")
    out.append("    var mat = 0.0;")
    out.append(f"    // suelo (firmamento bajo)")
    out.append(f"    {{ let dd = sd_plane(p, {_f(GROUND_Y)}); if (dd < d) {{ d = dd; mat = 0.0; }} }}")
    out.extend(geom_blocks)
    out.append("    return vec2<f32>(d, mat);")
    out.append("}")
    out.append("")
    out.append("fn mat_color(id : f32) -> vec3<f32> {")
    out.append(f"    if (id < 0.5) {{ return {_v3(GROUND_COLOR)}; }}  // suelo")
    out.extend(color_arms)
    out.append("    return vec3<f32>(1.0, 0.0, 1.0);  // material desconocido (magenta)")
    out.append("}")
    out.append("")
    out.append("// Reflectividad por material (Fase 5): de 'shiny' en cada thing.")
    out.append("fn mat_reflect(id : f32) -> f32 {")
    out.extend(reflect_arms)
    out.append("    return 0.0;")
    out.append("}")
    out.append("")
    out.append("// Rugosidad PBR por material (Fase 5).")
    out.append("fn mat_rough(id : f32) -> f32 {")
    out.append("    if (id < 0.5) { return 0.32; }  // suelo: algo pulido")
    out.extend(rough_arms)
    out.append("    return 0.6;")
    out.append("}")
    out.append("")
    out.append("// Metalicidad PBR por material (Fase 5).")
    out.append("fn mat_metal(id : f32) -> f32 {")
    out.extend(metal_arms)
    out.append("    return 0.0;")
    out.append("}")
    out.append("")
    return "\n".join(out)


def _center_wgsl(b, idx) -> str:
    """Expresión WGSL del centro del cuerpo en función de t. La posición base
    sale de Obj.pos[idx] (uniform en runtime) para poder moverla sin recompilar."""
    base = f"Obj.pos[{idx}]"
    if b.family == FAM_LOCOMOTION and b.self_animated:
        # pasea alrededor de su posición: x = pos.x + range*sin(t*speed)
        return (f"vec3<f32>({base}.x + {_f(b.range)} * sin(t * {_f(b.speed)}), "
                f"{base}.y, {base}.z)")
    return f"{base}.xyz"


def scene_objects(behaviors):
    """Lista (name, x, y, z, size, kind) de los objetos, en el mismo orden que
    los índices de Obj.pos[]. 'kind' = 'sdf' | 'mesh' | 'asset'. El motor la usa
    para sembrar Obj.pos[], saber qué objeto es la malla/asset importado, y
    escribir de vuelta las posiciones tras mover con el gizmo."""
    objs = []
    for b in behaviors:
        if b.family == FAM_LUMINARY and not b.is_light:
            continue
        if b.family == FAM_MESH:
            kind, size = "mesh", float(getattr(b, "scale", 1.0))
        elif b.family == FAM_ASSET:
            kind, size = "asset", float(getattr(b, "scale", 1.0))
        else:
            kind, size = "sdf", float(b.size)
        x, y, z = b.place
        objs.append((b.name, float(x), float(y), float(z), size, kind))
    return objs


def main():
    if len(sys.argv) < 3:
        print("uso: python -m rtg.codegen <entrada.node> <salida.wgsl>")
        sys.exit(1)
    src_path, out_path = sys.argv[1], sys.argv[2]
    with open(src_path, "r", encoding="utf-8") as f:
        wgsl = generate_wgsl(f.read())
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(wgsl)
    print(f"WGSL generado: {out_path}")


if __name__ == "__main__":
    main()
