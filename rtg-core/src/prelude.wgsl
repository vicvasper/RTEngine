// ============================================================================
//  RTGEngine · prelude.wgsl  (se concatena PRIMERO)
//  Uniforms compartidos y primitivas de campo (Letters). La escena generada
//  desde el idioma las usa; por eso van antes.
// ============================================================================

struct Uniforms {
    resolution   : vec2<f32>,
    time         : f32,
    sample_count : f32,
    jitter       : vec2<f32>,   // desplazamiento sub-píxel (amortización temporal)
    _pad         : vec2<f32>,
    cam_pos      : vec4<f32>,   // posición de la cámara (xyz)
    cam_fwd      : vec4<f32>,   // dirección hacia delante (xyz)
    asset        : vec4<f32>,   // modelo importado: xyz = posición, w = escala (<=0 desactivado)
};

// Posiciones de los objetos en tiempo de ejecución (editor: mover sin recompilar).
// La escena generada lee Obj.pos[k] en vez de constantes horneadas, así arrastrar
// un objeto sólo actualiza este uniform (coste cero, sin recompilar el shader).
struct ObjData {
    pos : array<vec4<f32>, 32>,   // xyz = posición de cada objeto; índice = mat-1
};

@group(0) @binding(0) var<uniform> U : Uniforms;
@group(0) @binding(1) var asset_tex : texture_3d<f32>;   // campo del modelo importado
@group(0) @binding(2) var asset_smp : sampler;
@group(0) @binding(3) var<uniform> Obj : ObjData;

// Campo de distancia del modelo importado (Fase 4). Transforma el punto a su
// caja local [-1,1] y muestrea la textura 3D; fuera de la caja usa la distancia
// a la caja para que el rayo converja. Si w<=0, no hay asset.
fn imported_sdf(p : vec3<f32>) -> f32 {
    let s = U.asset.w;
    if (s <= 0.0) { return 1.0e9; }
    let lp = (p - U.asset.xyz) / s;             // a espacio local [-1,1]
    let q = abs(lp) - vec3<f32>(1.0);
    let outside = length(max(q, vec3<f32>(0.0)));
    if (outside > 0.0) { return outside * s; }  // fuera de la caja: distancia a la caja
    let uvw = clamp(lp * 0.5 + 0.5, vec3<f32>(0.001), vec3<f32>(0.999));
    return textureSampleLevel(asset_tex, asset_smp, uvw, 0.0).r * s;
}

fn sd_sphere(p : vec3<f32>, c : vec3<f32>, r : f32) -> f32 {
    return length(p - c) - r;
}

fn sd_plane(p : vec3<f32>, h : f32) -> f32 {
    return p.y - h;
}

fn sd_box(p : vec3<f32>, c : vec3<f32>, b : vec3<f32>) -> f32 {
    let q = abs(p - c) - b;
    return length(max(q, vec3<f32>(0.0))) + min(max(q.x, max(q.y, q.z)), 0.0);
}
