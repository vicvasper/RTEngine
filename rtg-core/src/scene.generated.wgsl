// ===========================================================
//  AUTO-GENERADO por rtg/codegen.py desde una frase .node
//  NO EDITAR A MANO. Regenera con:  python forge.py <archivo>
// ===========================================================

fn light_pos() -> vec3<f32> { return Obj.pos[0].xyz; }  // luz de 'sol' (4300 K, 200 lm)
const LIGHT_COL : vec3<f32> = vec3<f32>(1.00000, 0.83533, 0.70307);
const LIGHT_INT : f32 = 0.80000;   // intensidad (de brightness)
const LIGHT_MAT : f32 = 1.00000;   // material emisivo (la bombilla)
const LIGHT_R : f32 = 0.15000;   // radio de la lámpara (área -> sombras suaves)

// La frase: el campo de distancia de toda la escena.
// Devuelve (distancia, id de material).
fn scene_sdf(p : vec3<f32>, t : f32) -> vec2<f32> {
    var d = 1e9;
    var mat = 0.0;
    // suelo (firmamento bajo)
    { let dd = sd_plane(p, -1.00000); if (dd < d) { d = dd; mat = 0.0; } }
    // sol  ·  familia=luminary  ·  mat=1
    { let dd = sd_sphere(p, Obj.pos[0].xyz, 0.15000); if (dd < d) { d = dd; mat = 1.00000; } }
    // heroe  ·  familia=locomotion  ·  mat=2
    { let dd = sd_sphere(p, vec3<f32>(Obj.pos[1].x + 1.40000 * sin(t * 1.40000), Obj.pos[1].y, Obj.pos[1].z), 0.50000); if (dd < d) { d = dd; mat = 2.00000; } }
    // piedra  ·  familia=solid  ·  mat=3
    { let dd = sd_sphere(p, Obj.pos[2].xyz, 0.70000); if (dd < d) { d = dd; mat = 3.00000; } }
    // muro  ·  familia=structure  ·  mat=4
    { let dd = sd_box(p, Obj.pos[3].xyz, vec3<f32>(0.60000)); if (dd < d) { d = dd; mat = 4.00000; } }
    // charco  ·  familia=fluid  ·  mat=5
    { let dd = sd_plane(p, Obj.pos[4].y); if (dd < d) { d = dd; mat = 5.00000; } }
    // brote  ·  familia=scatter  ·  mat=6
    { let dd = sd_sphere(p, Obj.pos[5].xyz, 0.15000); if (dd < d) { d = dd; mat = 6.00000; } }
    // rubi  ·  familia=solid  ·  mat=7
    { let dd = sd_sphere(p, Obj.pos[6].xyz, 0.45000); if (dd < d) { d = dd; mat = 7.00000; } }
    return vec2<f32>(d, mat);
}

fn mat_color(id : f32) -> vec3<f32> {
    if (id < 0.5) { return vec3<f32>(0.20000, 0.20000, 0.24000); }  // suelo
    if (id < 1.50000) { return vec3<f32>(1.00000, 0.83533, 0.70307); }
    if (id < 2.50000) { return vec3<f32>(0.20000, 0.70000, 0.25000); }
    if (id < 3.50000) { return vec3<f32>(0.55000, 0.55000, 0.58000); }
    if (id < 4.50000) { return vec3<f32>(0.45000, 0.28000, 0.15000); }
    if (id < 5.50000) { return vec3<f32>(0.20000, 0.50000, 0.80000); }
    if (id < 6.50000) { return vec3<f32>(0.20000, 0.70000, 0.25000); }
    if (id < 7.50000) { return vec3<f32>(0.80000, 0.12000, 0.12000); }
    return vec3<f32>(1.0, 0.0, 1.0);  // material desconocido (magenta)
}

// Reflectividad por material (Fase 5): de 'shiny' en cada thing.
fn mat_reflect(id : f32) -> f32 {
    if (id < 1.50000) { return 0.00000; }
    if (id < 2.50000) { return 0.00000; }
    if (id < 3.50000) { return 0.00000; }
    if (id < 4.50000) { return 0.00000; }
    if (id < 5.50000) { return 0.00000; }
    if (id < 6.50000) { return 0.00000; }
    if (id < 7.50000) { return 0.60000; }
    return 0.0;
}

// Rugosidad PBR por material (Fase 5).
fn mat_rough(id : f32) -> f32 {
    if (id < 0.5) { return 0.32; }  // suelo: algo pulido
    if (id < 1.50000) { return 0.60000; }
    if (id < 2.50000) { return 0.60000; }
    if (id < 3.50000) { return 0.60000; }
    if (id < 4.50000) { return 0.60000; }
    if (id < 5.50000) { return 0.60000; }
    if (id < 6.50000) { return 0.60000; }
    if (id < 7.50000) { return 0.30000; }
    return 0.6;
}

// Metalicidad PBR por material (Fase 5).
fn mat_metal(id : f32) -> f32 {
    if (id < 1.50000) { return 0.00000; }
    if (id < 2.50000) { return 0.00000; }
    if (id < 3.50000) { return 0.00000; }
    if (id < 4.50000) { return 0.00000; }
    if (id < 5.50000) { return 0.00000; }
    if (id < 6.50000) { return 0.00000; }
    if (id < 7.50000) { return 0.00000; }
    return 0.0;
}
