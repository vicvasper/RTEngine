// ============================================================================
//  RTGEngine · núcleo nativo — Fase 1 "La Luz"
//  Abre una ventana y dibuja, sin un solo polígono, una escena de campos de
//  distancia (SDF) mediante un fragment shader que hace sphere tracing.
//  La escena corresponde al Edén mínimo de ../examples/start.node.
//
//  NOTA: requiere la toolchain de Rust instalada (ver ../README_RUST.md).
// ============================================================================
// En release, sin ventana de consola (es una app gráfica). En debug se mantiene
// la consola para ver logs y el modo --snapshot.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::sync::Arc;
use std::time::Instant;

use winit::{
    event::{Event, WindowEvent},
    event_loop::EventLoop,
    keyboard::{KeyCode, PhysicalKey},
    window::WindowBuilder,
};

#[repr(C)]
#[derive(Copy, Clone, bytemuck::Pod, bytemuck::Zeroable)]
struct Uniforms {
    resolution: [f32; 2],
    time: f32,
    sample_count: f32,
    jitter: [f32; 2],
    _pad: [f32; 2],
    cam_pos: [f32; 4],
    cam_fwd: [f32; 4],
    asset: [f32; 4], // modelo importado: xyz=posición, w=escala (<=0 desactivado)
}

/// Secuencia de Halton (base-b) para repartir el jitter de forma uniforme.
fn halton(mut i: u32, base: u32) -> f32 {
    let mut f = 1.0f32;
    let mut r = 0.0f32;
    while i > 0 {
        f /= base as f32;
        r += f * (i % base) as f32;
        i /= base;
    }
    r
}

fn norm3(v: [f32; 3]) -> [f32; 3] {
    let l = (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]).sqrt().max(1e-6);
    [v[0] / l, v[1] / l, v[2] / l]
}

fn cross3(a: [f32; 3], b: [f32; 3]) -> [f32; 3] {
    [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]
}

fn dot3(a: [f32; 3], b: [f32; 3]) -> f32 {
    a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
}

fn dist2d(a: [f32; 2], b: [f32; 2]) -> f32 {
    let (dx, dy) = (a[0] - b[0], a[1] - b[1]);
    (dx * dx + dy * dy).sqrt()
}

/// Distancia 2D de un punto al segmento a-b (para tocar los ejes del gizmo).
fn dist_seg(p: [f32; 2], a: [f32; 2], b: [f32; 2]) -> f32 {
    let ab = [b[0] - a[0], b[1] - a[1]];
    let ap = [p[0] - a[0], p[1] - a[1]];
    let l2 = ab[0] * ab[0] + ab[1] * ab[1];
    let t = if l2 > 1e-6 {
        ((ap[0] * ab[0] + ap[1] * ab[1]) / l2).clamp(0.0, 1.0)
    } else {
        0.0
    };
    dist2d(p, [a[0] + ab[0] * t, a[1] + ab[1] * t])
}

/// Proyecta un punto del mundo a píxeles, con la MISMA cámara que el shader.
/// Compartida por el viewport vivo y el test headless del gizmo.
fn project_point(
    cam_pos: [f32; 3],
    fwd_in: [f32; 3],
    w: f32,
    h: f32,
    p: [f32; 3],
) -> Option<([f32; 2], f32)> {
    let fwd = norm3(fwd_in);
    let right = norm3(cross3(fwd, [0.0, 1.0, 0.0]));
    let up = cross3(right, fwd);
    let v = [p[0] - cam_pos[0], p[1] - cam_pos[1], p[2] - cam_pos[2]];
    let c = dot3(v, fwd);
    if c <= 0.02 {
        return None;
    }
    let aspect = w / h.max(1.0);
    let ndc_x = (1.5 * dot3(v, right) / c) / aspect;
    let ndc_y = 1.5 * dot3(v, up) / c;
    Some(([(ndc_x * 0.5 + 0.5) * w, (0.5 - ndc_y * 0.5) * h], c))
}

/// Intersección de un rayo con el plano horizontal y=h (arrastre en suelo).
fn ray_plane(ro: [f32; 3], rd: [f32; 3], h: f32) -> Option<[f32; 3]> {
    if rd[1].abs() < 1e-5 {
        return None;
    }
    let t = (h - ro[1]) / rd[1];
    if t <= 0.0 {
        return None;
    }
    Some([ro[0] + rd[0] * t, ro[1] + rd[1] * t, ro[2] + rd[2] * t])
}

/// Pinta un píxel RGBA en el buffer (para el test headless del gizmo).
fn put_px(px: &mut [u8], w: i32, h: i32, x: i32, y: i32, c: [u8; 3]) {
    if x >= 0 && x < w && y >= 0 && y < h {
        let i = ((y * w + x) * 4) as usize;
        px[i] = c[0];
        px[i + 1] = c[1];
        px[i + 2] = c[2];
        px[i + 3] = 255;
    }
}

/// Traza una línea 2D en el buffer (test headless del gizmo).
fn draw_line(px: &mut [u8], w: i32, h: i32, a: [f32; 2], b: [f32; 2], c: [u8; 3]) {
    let steps = (dist2d(a, b) as i32).max(1);
    for s in 0..=steps {
        let t = s as f32 / steps as f32;
        let x = (a[0] + (b[0] - a[0]) * t).round() as i32;
        let y = (a[1] + (b[1] - a[1]) * t).round() as i32;
        put_px(px, w, h, x, y, c);
        put_px(px, w, h, x + 1, y, c);
        put_px(px, w, h, x, y + 1, c);
    }
}

fn additive_blend() -> wgpu::BlendState {
    let add = wgpu::BlendComponent {
        src_factor: wgpu::BlendFactor::One,
        dst_factor: wgpu::BlendFactor::One,
        operation: wgpu::BlendOperation::Add,
    };
    wgpu::BlendState { color: add, alpha: add }
}

const DEPTH_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Depth32Float;

// ============================================================================
//  Malla importada (Fase 6 · primer ladrillo): rasteriza un personaje FBX
//  texturizado SOBRE la escena SDF (coexisten). Skinning/animación: siguiente.
// ============================================================================
#[repr(C)]
#[derive(Copy, Clone, bytemuck::Pod, bytemuck::Zeroable)]
struct MeshUniforms {
    mvp: [f32; 16],       // proyección·vista·modelo
    model: [f32; 16],     // modelo (para normales; escala uniforme)
    light_dir: [f32; 4],  // sol direccional (xyz) para iluminar la malla
}

/// mat4 columna-mayor (como WGSL): elemento (fila r, col c) = m[c*4+r].
fn mat_mul(a: &[f32; 16], b: &[f32; 16]) -> [f32; 16] {
    let mut o = [0.0f32; 16];
    for c in 0..4 {
        for r in 0..4 {
            let mut s = 0.0;
            for k in 0..4 {
                s += a[k * 4 + r] * b[c * 4 + k];
            }
            o[c * 4 + r] = s;
        }
    }
    o
}

/// Vista (mundo->cámara): base x=right, y=up, z=fwd (mira hacia +z).
fn mat_view(cam: [f32; 3], right: [f32; 3], up: [f32; 3], fwd: [f32; 3]) -> [f32; 16] {
    let tr = -dot3(right, cam);
    let tu = -dot3(up, cam);
    let tf = -dot3(fwd, cam);
    [
        right[0], up[0], fwd[0], 0.0,
        right[1], up[1], fwd[1], 0.0,
        right[2], up[2], fwd[2], 0.0,
        tr, tu, tf, 1.0,
    ]
}

/// Proyección perspectiva que COINCIDE con la cámara del raymarcher SDF
/// (focal 1.5, aspecto en x). Profundidad wgpu en [0,1].
fn mat_proj(aspect: f32, near: f32, far: f32) -> [f32; 16] {
    let f = 1.5f32;
    [
        f / aspect, 0.0, 0.0, 0.0,
        0.0, f, 0.0, 0.0,
        0.0, 0.0, far / (far - near), 1.0,
        0.0, 0.0, -far * near / (far - near), 0.0,
    ]
}

/// Modelo: escala uniforme + traslación (coloca el personaje en la escena).
fn mat_model(s: f32, t: [f32; 3]) -> [f32; 16] {
    [
        s, 0.0, 0.0, 0.0,
        0.0, s, 0.0, 0.0,
        0.0, 0.0, s, 0.0,
        t[0], t[1], t[2], 1.0,
    ]
}

/// Lee RTG_MESH (.rmesh) -> (bytes de vértices intercalados, nº vértices, modelo).
/// El modelo escala el personaje a ~1.8 de alto y le pone los pies en el suelo.
fn load_mesh() -> Option<(Vec<u8>, u32, [f32; 16])> {
    let path = std::env::var("RTG_MESH").ok()?;
    let data = std::fs::read(&path).ok()?;
    // RSM2 = malla con skinning (64 B/vértice: pos,nrm,uv,4 huesos u32,4 pesos f32)
    if data.len() < 8 || &data[0..4] != b"RSM2" {
        log::warn!("RTG_MESH inválido (se esperaba RSM2): {path}");
        return None;
    }
    let n = u32::from_le_bytes([data[4], data[5], data[6], data[7]]);
    let verts = data[8..].to_vec();
    let (mut miny, mut maxy) = (f32::MAX, f32::MIN);
    let (mut cx, mut cz, mut cnt) = (0.0f64, 0.0f64, 0u32);
    let stride = 64usize;
    let mut i = 0usize;
    while i + 12 <= verts.len() {
        let x = f32::from_le_bytes([verts[i], verts[i + 1], verts[i + 2], verts[i + 3]]);
        let y = f32::from_le_bytes([verts[i + 4], verts[i + 5], verts[i + 6], verts[i + 7]]);
        let z = f32::from_le_bytes([verts[i + 8], verts[i + 9], verts[i + 10], verts[i + 11]]);
        miny = miny.min(y);
        maxy = maxy.max(y);
        cx += x as f64;
        cz += z as f64;
        cnt += 1;
        i += stride;
    }
    let h = (maxy - miny).max(1e-3);
    // RTG_MESH_SCALE multiplica el auto-ajuste (~1.8 de alto); RTG_MESH_POS desplaza.
    let scale_mul = std::env::var("RTG_MESH_SCALE")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(1.0f32)
        .clamp(0.05, 50.0);
    let off = parse_vec3_env("RTG_MESH_POS", [0.0, 0.0, 0.0]);
    let s = (1.8 / h) * scale_mul;
    let ty = -1.0 - miny * s + off[1];
    let tx = -(cx / cnt.max(1) as f64) as f32 * s + off[0];
    let tz = -(cz / cnt.max(1) as f64) as f32 * s + off[2];
    Some((verts, n, mat_model(s, [tx, ty, tz])))
}

const MAX_BONES: usize = 128;

/// Lee RTG_MESH_ANIM (.ranim) -> (frames, huesos, fps, matrices de skin [F*B*16]).
fn load_anim() -> Option<(u32, u32, f32, Vec<f32>)> {
    let path = std::env::var("RTG_MESH_ANIM").ok()?;
    let data = std::fs::read(&path).ok()?;
    if data.len() < 16 || &data[0..4] != b"RANM" {
        return None;
    }
    let f = u32::from_le_bytes([data[4], data[5], data[6], data[7]]);
    let b = u32::from_le_bytes([data[8], data[9], data[10], data[11]]);
    let fps = f32::from_le_bytes([data[12], data[13], data[14], data[15]]);
    let mats: Vec<f32> = data[16..]
        .chunks_exact(4)
        .map(|c| f32::from_le_bytes([c[0], c[1], c[2], c[3]]))
        .collect();
    Some((f, b, fps, mats))
}

/// Matrices de huesos del frame `t` (segundos) -> buffer plano [MAX_BONES*16].
/// Si no hay animación, identidades (bind pose).
fn bone_frame(anim: &Option<(u32, u32, f32, Vec<f32>)>, t: f32) -> Vec<f32> {
    let mut out = vec![0.0f32; MAX_BONES * 16];
    // identidad por defecto en todos los huesos
    for i in 0..MAX_BONES {
        out[i * 16] = 1.0;
        out[i * 16 + 5] = 1.0;
        out[i * 16 + 10] = 1.0;
        out[i * 16 + 15] = 1.0;
    }
    if let Some((f, b, fps, mats)) = anim {
        let (f, b) = (*f as usize, *b as usize);
        if f > 0 && b > 0 {
            let frame = ((t * fps).floor() as i64).rem_euclid(f as i64) as usize;
            let base = frame * b * 16;
            let nb = b.min(MAX_BONES);
            out[..nb * 16].copy_from_slice(&mats[base..base + nb * 16]);
        }
    }
    out
}

/// Carga la textura difusa (RTG_MESH_TEX, PNG) -> vista + sampler.
fn load_mesh_texture(
    device: &wgpu::Device,
    queue: &wgpu::Queue,
) -> (wgpu::TextureView, wgpu::Sampler) {
    let sampler = device.create_sampler(&wgpu::SamplerDescriptor {
        label: Some("mesh-tex-smp"),
        address_mode_u: wgpu::AddressMode::Repeat,
        address_mode_v: wgpu::AddressMode::Repeat,
        mag_filter: wgpu::FilterMode::Linear,
        min_filter: wgpu::FilterMode::Linear,
        mipmap_filter: wgpu::FilterMode::Linear,
        ..Default::default()
    });
    let path = std::env::var("RTG_MESH_TEX").ok();
    let img = path.and_then(|p| image::open(&p).ok()).map(|i| i.to_rgba8());
    let (w, h, pixels) = match img {
        Some(im) => (im.width(), im.height(), im.into_raw()),
        None => (1, 1, vec![200, 200, 205, 255]),
    };
    let tex = device.create_texture(&wgpu::TextureDescriptor {
        label: Some("mesh-diffuse"),
        size: wgpu::Extent3d { width: w, height: h, depth_or_array_layers: 1 },
        mip_level_count: 1,
        sample_count: 1,
        dimension: wgpu::TextureDimension::D2,
        format: wgpu::TextureFormat::Rgba8UnormSrgb,
        usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
        view_formats: &[],
    });
    queue.write_texture(
        wgpu::ImageCopyTexture {
            texture: &tex,
            mip_level: 0,
            origin: wgpu::Origin3d::ZERO,
            aspect: wgpu::TextureAspect::All,
        },
        &pixels,
        wgpu::ImageDataLayout {
            offset: 0,
            bytes_per_row: Some(4 * w),
            rows_per_image: Some(h),
        },
        wgpu::Extent3d { width: w, height: h, depth_or_array_layers: 1 },
    );
    (tex.create_view(&Default::default()), sampler)
}

/// Textura de profundidad para la rasterización de la malla.
fn make_depth(device: &wgpu::Device, w: u32, h: u32) -> wgpu::TextureView {
    let tex = device.create_texture(&wgpu::TextureDescriptor {
        label: Some("mesh-depth"),
        size: wgpu::Extent3d { width: w.max(1), height: h.max(1), depth_or_array_layers: 1 },
        mip_level_count: 1,
        sample_count: 1,
        dimension: wgpu::TextureDimension::D2,
        format: DEPTH_FORMAT,
        usage: wgpu::TextureUsages::RENDER_ATTACHMENT,
        view_formats: &[],
    });
    tex.create_view(&Default::default())
}

const MESH_WGSL: &str = r#"
struct MU {
    mvp : mat4x4<f32>,
    model : mat4x4<f32>,
    light_dir : vec4<f32>,
};
struct Bones { m : array<mat4x4<f32>, 128>, };
@group(0) @binding(0) var<uniform> U : MU;
@group(0) @binding(1) var tex : texture_2d<f32>;
@group(0) @binding(2) var smp : sampler;
@group(0) @binding(3) var<uniform> BN : Bones;

struct VO {
    @builtin(position) clip : vec4<f32>,
    @location(0) nrm : vec3<f32>,
    @location(1) uv : vec2<f32>,
};

@vertex
fn vs(@location(0) pos : vec3<f32>, @location(1) nrm : vec3<f32>,
      @location(2) uv : vec2<f32>, @location(3) bidx : vec4<u32>,
      @location(4) wt : vec4<f32>) -> VO {
    // Skinning lineal: mezcla de las matrices de los 4 huesos por sus pesos.
    let skin = BN.m[bidx.x] * wt.x + BN.m[bidx.y] * wt.y
             + BN.m[bidx.z] * wt.z + BN.m[bidx.w] * wt.w;
    let sp = skin * vec4<f32>(pos, 1.0);          // posición animada (local)
    let sn = (skin * vec4<f32>(nrm, 0.0)).xyz;    // normal animada
    var o : VO;
    o.clip = U.mvp * sp;
    o.nrm = (U.model * vec4<f32>(sn, 0.0)).xyz;
    o.uv = uv;
    return o;
}

@fragment
fn fs(in : VO) -> @location(0) vec4<f32> {
    let albedo = textureSample(tex, smp, in.uv).rgb;
    let n = normalize(in.nrm);
    let l = normalize(U.light_dir.xyz);
    let ndl = clamp(dot(n, l), 0.0, 1.0);
    let lit = albedo * (0.35 + 1.15 * ndl);   // difusa + relleno (LINEAL; ACES al presentar)
    // light_dir.w = factor de escala (1 en vivo; nº de muestras en snapshot acumulado)
    return vec4<f32>(lit * U.light_dir.w, 1.0);
}
"#;

fn make_mesh_pipeline(
    device: &wgpu::Device,
    format: wgpu::TextureFormat,
) -> (wgpu::RenderPipeline, wgpu::BindGroupLayout) {
    let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
        label: Some("mesh"),
        source: wgpu::ShaderSource::Wgsl(MESH_WGSL.into()),
    });
    let bgl = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
        label: Some("mesh_bgl"),
        entries: &[
            wgpu::BindGroupLayoutEntry {
                binding: 0,
                visibility: wgpu::ShaderStages::VERTEX_FRAGMENT,
                ty: wgpu::BindingType::Buffer {
                    ty: wgpu::BufferBindingType::Uniform,
                    has_dynamic_offset: false,
                    min_binding_size: None,
                },
                count: None,
            },
            wgpu::BindGroupLayoutEntry {
                binding: 1,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Texture {
                    sample_type: wgpu::TextureSampleType::Float { filterable: true },
                    view_dimension: wgpu::TextureViewDimension::D2,
                    multisampled: false,
                },
                count: None,
            },
            wgpu::BindGroupLayoutEntry {
                binding: 2,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
                count: None,
            },
            // binding 3: matrices de huesos (skinning)
            wgpu::BindGroupLayoutEntry {
                binding: 3,
                visibility: wgpu::ShaderStages::VERTEX,
                ty: wgpu::BindingType::Buffer {
                    ty: wgpu::BufferBindingType::Uniform,
                    has_dynamic_offset: false,
                    min_binding_size: None,
                },
                count: None,
            },
        ],
    });
    let layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
        label: Some("mesh_layout"),
        bind_group_layouts: &[&bgl],
        push_constant_ranges: &[],
    });
    let pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
        label: Some("mesh_pipeline"),
        layout: Some(&layout),
        vertex: wgpu::VertexState {
            module: &shader,
            entry_point: "vs",
            buffers: &[wgpu::VertexBufferLayout {
                array_stride: 64,
                step_mode: wgpu::VertexStepMode::Vertex,
                attributes: &[
                    wgpu::VertexAttribute { format: wgpu::VertexFormat::Float32x3, offset: 0, shader_location: 0 },
                    wgpu::VertexAttribute { format: wgpu::VertexFormat::Float32x3, offset: 12, shader_location: 1 },
                    wgpu::VertexAttribute { format: wgpu::VertexFormat::Float32x2, offset: 24, shader_location: 2 },
                    wgpu::VertexAttribute { format: wgpu::VertexFormat::Uint32x4, offset: 32, shader_location: 3 },
                    wgpu::VertexAttribute { format: wgpu::VertexFormat::Float32x4, offset: 48, shader_location: 4 },
                ],
            }],
            compilation_options: Default::default(),
        },
        fragment: Some(wgpu::FragmentState {
            module: &shader,
            entry_point: "fs",
            targets: &[Some(wgpu::ColorTargetState {
                format,
                blend: Some(wgpu::BlendState::REPLACE),
                write_mask: wgpu::ColorWrites::ALL,
            })],
            compilation_options: Default::default(),
        }),
        primitive: wgpu::PrimitiveState {
            cull_mode: None,
            ..Default::default()
        },
        depth_stencil: Some(wgpu::DepthStencilState {
            format: DEPTH_FORMAT,
            depth_write_enabled: true,
            depth_compare: wgpu::CompareFunction::Less,
            stencil: Default::default(),
            bias: Default::default(),
        }),
        multisample: wgpu::MultisampleState::default(),
        multiview: None,
    });
    (pipeline, bgl)
}


/// el editor (y permite empaquetar el .exe); si no, la carpeta src/ del crate (dev).
fn scene_dir() -> String {
    std::env::var("RTG_SCENE_DIR")
        .unwrap_or_else(|_| concat!(env!("CARGO_MANIFEST_DIR"), "/src").to_string())
}
/// Ruta de la escena generada (la observa el hot-reload).
fn scene_path() -> String {
    format!("{}/scene.generated.wgsl", scene_dir())
}
/// Sidecar con las posiciones iniciales de los objetos (lo escribe forge.py).
fn obj_path() -> String {
    format!("{}/scene.objects.txt", scene_dir())
}
/// Donde el motor escribe las posiciones tras mover con el gizmo (lo lee el editor).
fn live_path() -> String {
    format!("{}/scene.live.txt", scene_dir())
}
/// Máximo de objetos (coincide con array<vec4,32> en prelude.wgsl).
const MAX_OBJ: usize = 32;

/// Un objeto editable: su posición (movible con el gizmo), tamaño y nombre.
struct ObjInfo {
    pos: [f32; 3],
    size: f32,
    #[allow(dead_code)] // reservado para etiquetas de objeto en el viewport
    name: String,
}

/// Lee el sidecar scene.objects.txt -> lista de objetos (índice = mat-1).
fn load_objects() -> Vec<ObjInfo> {
    let mut v = Vec::new();
    if let Ok(txt) = std::fs::read_to_string(obj_path()) {
        for line in txt.lines() {
            let p: Vec<&str> = line.split_whitespace().collect();
            if p.len() >= 5 {
                v.push(ObjInfo {
                    pos: [
                        p[1].parse().unwrap_or(0.0),
                        p[2].parse().unwrap_or(0.0),
                        p[3].parse().unwrap_or(0.0),
                    ],
                    size: p[4].parse().unwrap_or(0.3),
                    name: p.get(5..).map(|w| w.join(" ")).unwrap_or_default(),
                });
            }
        }
    }
    v
}

/// Empaqueta las posiciones en el formato del uniform (array<vec4,32>).
fn obj_buffer_data(objs: &[ObjInfo]) -> Vec<[f32; 4]> {
    let mut d = vec![[0.0f32; 4]; MAX_OBJ];
    for (i, o) in objs.iter().take(MAX_OBJ).enumerate() {
        d[i] = [o.pos[0], o.pos[1], o.pos[2], 0.0];
    }
    d
}

/// Teclas mantenidas para el control de cámara.
#[derive(Default)]
struct Keys {
    fwd: bool,
    back: bool,
    left: bool,
    right: bool,
    up: bool,
    down: bool,
    yaw_l: bool,
    yaw_r: bool,
    pitch_u: bool,
    pitch_d: bool,
}

const HDR_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Rgba16Float;

/// Estado de la malla rasterizada (personaje FBX) que coexiste con el SDF.
struct MeshState {
    pipeline: wgpu::RenderPipeline,
    vbuf: wgpu::Buffer,
    vcount: u32,
    bg: wgpu::BindGroup,
    uniform_buf: wgpu::Buffer,
    bone_buf: wgpu::Buffer,
    anim: Option<(u32, u32, f32, Vec<f32>)>,   // frames, huesos, fps, matrices
    model: [f32; 16],
}

struct State {
    mesh: Option<MeshState>,
    scene_depth: wgpu::TextureView,   // profundidad compartida SDF <-> malla
    surface: wgpu::Surface<'static>,
    device: wgpu::Device,
    queue: wgpu::Queue,
    config: wgpu::SurfaceConfiguration,
    size: winit::dpi::PhysicalSize<u32>,
    scene_pipeline: wgpu::RenderPipeline,    // escena -> HDR (mezcla aditiva)
    present_pipeline: wgpu::RenderPipeline,  // HDR -> pantalla (upscale + divide n)
    present_bgl: wgpu::BindGroupLayout,
    uniform_buf: wgpu::Buffer,
    scene_bg: wgpu::BindGroup,
    inv_buf: wgpu::Buffer,
    present_bg: wgpu::BindGroup,
    hdr_view: wgpu::TextureView,
    sampler: wgpu::Sampler,
    render_scale: f32,   // resolución interna (0.7 = 70%); se reconstruye al presentar
    hdr_w: u32,
    hdr_h: u32,
    fps_accum: f32,
    fps_frames: u32,
    window: Arc<winit::window::Window>,
    last: Instant,
    sim_time: f32,
    paused: bool,      // Espacio: congela el tiempo y deja que la imagen refine
    frame_index: u32,
    accum_n: u32,      // muestras acumuladas desde el último reinicio (Cache)
    // --- cámara navegable (estilo Unreal) ---
    cam_pos: [f32; 3],
    yaw: f32,
    pitch: f32,
    keys: Keys,
    rmb: bool,          // botón derecho: modo vuelo (mirar con ratón + WASD)
    mmb: bool,          // botón central: pan
    move_speed: f32,    // velocidad de vuelo (la rueda la ajusta)
    cam_dirty: bool,    // la cámara cambió por ratón/rueda este frame
    // --- hot-reload de la escena ---
    scene_mtime: Option<std::time::SystemTime>,
    // --- modelo importado (Fase 4) ---
    asset_uniform: [f32; 4],
    asset_view: wgpu::TextureView,
    asset_sampler: wgpu::Sampler,
    asset_filterable: bool,
    // --- objetos editables + gizmo (mover sin recompilar) ---
    obj_buf: wgpu::Buffer,
    objects: Vec<ObjInfo>,
    obj_dirty: bool,        // hay que reescribir obj_buf (tras cargar o mover)
    selected: i32,          // objeto seleccionado (-1 = ninguno)
    lmb: bool,              // botón izquierdo (seleccionar / arrastrar)
    cursor_pos: [f32; 2],   // posición del cursor en píxeles de ventana
    drag_mode: u8,          // 0 ninguno · 1 X · 2 Y · 3 Z · 4 plano XZ
    drag_start_cursor: [f32; 2],
    drag_start_pos: [f32; 3],
    drag_plane_off: [f32; 3],
    drag_moved: bool,       // el arrastre movió algo (para escribir de vuelta)
}

impl State {
    async fn new(window: Arc<winit::window::Window>) -> Self {
        let size = window.inner_size();

        let instance = wgpu::Instance::new(wgpu::InstanceDescriptor {
            backends: wgpu::Backends::PRIMARY,
            ..Default::default()
        });

        // Arc<Window> permite una surface 'static (sin atar a un préstamo).
        let surface = instance.create_surface(window.clone()).unwrap();

        let adapter = instance
            .request_adapter(&wgpu::RequestAdapterOptions {
                power_preference: wgpu::PowerPreference::HighPerformance,
                compatible_surface: Some(&surface),
                force_fallback_adapter: false,
            })
            .await
            .expect("No se encontró un adaptador de GPU compatible");

        log::info!("GPU: {:?}", adapter.get_info());

        // Filtrado trilineal de texturas float32 (para el SDF del modelo importado).
        let asset_filterable = adapter
            .features()
            .contains(wgpu::Features::FLOAT32_FILTERABLE);
        let req_features = if asset_filterable {
            wgpu::Features::FLOAT32_FILTERABLE
        } else {
            wgpu::Features::empty()
        };
        let (device, queue) = adapter
            .request_device(
                &wgpu::DeviceDescriptor {
                    label: Some("rtg-device"),
                    required_features: req_features,
                    required_limits: wgpu::Limits::default(),
                },
                None,
            )
            .await
            .expect("No se pudo crear el dispositivo");

        let caps = surface.get_capabilities(&adapter);
        let format = caps
            .formats
            .iter()
            .copied()
            .find(|f| f.is_srgb())
            .unwrap_or(caps.formats[0]);

        // RTG_NOVSYNC=1 desactiva el vsync para MEDIR los fps reales.
        let present_mode = if std::env::var("RTG_NOVSYNC").is_ok() {
            wgpu::PresentMode::AutoNoVsync
        } else {
            wgpu::PresentMode::AutoVsync
        };
        let config = wgpu::SurfaceConfiguration {
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT,
            format,
            width: size.width.max(1),
            height: size.height.max(1),
            present_mode,
            alpha_mode: caps.alpha_modes[0],
            view_formats: vec![],
            desired_maximum_frame_latency: 2,
        };
        surface.configure(&device, &config);

        // --- Cache en vivo: escena -> HDR acumulado -> presente ---
        let uniform_buf = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("uniforms"),
            size: std::mem::size_of::<Uniforms>() as u64,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let (scene_pipeline, bgl) =
            make_pipeline(&device, HDR_FORMAT, additive_blend(), asset_filterable);
        // Modelo importado (Fase 4): textura 3D del SDF + su colocación.
        let (asset_view, asset_smp, asset_uniform) =
            load_asset(&device, &queue, asset_filterable);
        // Objetos editables: posiciones en runtime (binding 3).
        let objects = load_objects();
        let obj_buf = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("obj-pos"),
            size: (MAX_OBJ * 16) as u64,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        queue.write_buffer(&obj_buf, 0, bytemuck::cast_slice(&obj_buffer_data(&objects)));
        let scene_bg =
            make_scene_bg(&device, &bgl, &uniform_buf, &asset_view, &asset_smp, &obj_buf);

        let (present_pipeline, present_bgl) = make_present(&device, format);
        let inv_buf = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("inv"),
            size: 48, // 1/N + datos del gizmo (centro + 3 puntas + eje activo)
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let sampler = device.create_sampler(&wgpu::SamplerDescriptor {
            label: Some("present-sampler"),
            mag_filter: wgpu::FilterMode::Linear,
            min_filter: wgpu::FilterMode::Linear,
            mipmap_filter: wgpu::FilterMode::Nearest,
            ..Default::default()
        });
        // Resolución interna reducida: menos píxeles que trazar; el presente
        // las reconstruye (upscale bilineal) y la acumulación recupera detalle.
        // Hay rendimiento de sobra (~2700 fps en release): por defecto, resolución
        // completa (nítido). RTG_SCALE<1 la reduce para escenas muy pesadas.
        let render_scale = std::env::var("RTG_SCALE")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(1.0f32)
            .clamp(0.3, 1.0);
        let hdr_w = ((size.width as f32 * render_scale) as u32).max(1);
        let hdr_h = ((size.height as f32 * render_scale) as u32).max(1);
        let hdr_view = make_hdr(&device, hdr_w, hdr_h);
        let present_bg = make_present_bg(&device, &present_bgl, &inv_buf, &hdr_view, &sampler);

        // Malla importada (Fase 6): personaje texturizado rasterizado sobre la
        // escena SDF. Solo si RTG_MESH apunta a un .rmesh.
        let mesh = load_mesh().map(|(verts, vcount, model)| {
            let (pipeline, mbgl) = make_mesh_pipeline(&device, HDR_FORMAT);
            let vbuf = device.create_buffer(&wgpu::BufferDescriptor {
                label: Some("mesh-vbuf"),
                size: verts.len() as u64,
                usage: wgpu::BufferUsages::VERTEX | wgpu::BufferUsages::COPY_DST,
                mapped_at_creation: false,
            });
            queue.write_buffer(&vbuf, 0, &verts);
            let (tex_view, tex_smp) = load_mesh_texture(&device, &queue);
            let uniform_buf = device.create_buffer(&wgpu::BufferDescriptor {
                label: Some("mesh-uniforms"),
                size: std::mem::size_of::<MeshUniforms>() as u64,
                usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
                mapped_at_creation: false,
            });
            let bone_buf = device.create_buffer(&wgpu::BufferDescriptor {
                label: Some("mesh-bones"),
                size: (MAX_BONES * 64) as u64,
                usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
                mapped_at_creation: false,
            });
            let anim = load_anim();
            queue.write_buffer(&bone_buf, 0, bytemuck::cast_slice(&bone_frame(&anim, 0.0)));
            let bg = device.create_bind_group(&wgpu::BindGroupDescriptor {
                label: Some("mesh_bg"),
                layout: &mbgl,
                entries: &[
                    wgpu::BindGroupEntry { binding: 0, resource: uniform_buf.as_entire_binding() },
                    wgpu::BindGroupEntry { binding: 1, resource: wgpu::BindingResource::TextureView(&tex_view) },
                    wgpu::BindGroupEntry { binding: 2, resource: wgpu::BindingResource::Sampler(&tex_smp) },
                    wgpu::BindGroupEntry { binding: 3, resource: bone_buf.as_entire_binding() },
                ],
            });
            log::info!("malla cargada: {vcount} vértices · animación: {}",
                       if anim.is_some() { "sí" } else { "no" });
            MeshState { pipeline, vbuf, vcount, bg, uniform_buf, bone_buf, anim, model }
        });
        let scene_depth = make_depth(&device, hdr_w, hdr_h);

        Self {
            mesh,
            scene_depth,
            surface,
            device,
            queue,
            config,
            size,
            scene_pipeline,
            present_pipeline,
            present_bgl,
            uniform_buf,
            scene_bg,
            inv_buf,
            present_bg,
            hdr_view,
            sampler,
            render_scale,
            hdr_w,
            hdr_h,
            fps_accum: 0.0,
            fps_frames: 0,
            window,
            last: Instant::now(),
            sim_time: 0.0,
            paused: false,
            frame_index: 0,
            accum_n: 0,
            cam_pos: [0.0, 1.2, 5.0],
            yaw: 0.0,
            pitch: -0.2,
            keys: Keys::default(),
            rmb: false,
            mmb: false,
            move_speed: 3.5,
            cam_dirty: false,
            scene_mtime: std::fs::metadata(scene_path()).and_then(|m| m.modified()).ok(),
            asset_uniform,
            asset_view,
            asset_sampler: asset_smp,
            asset_filterable,
            obj_buf,
            objects,
            obj_dirty: false,
            selected: -1,
            lmb: false,
            cursor_pos: [0.0, 0.0],
            drag_mode: 0,
            drag_start_cursor: [0.0, 0.0],
            drag_start_pos: [0.0, 0.0, 0.0],
            drag_plane_off: [0.0, 0.0, 0.0],
            drag_moved: false,
        }
    }

    fn toggle_pause(&mut self) {
        self.paused = !self.paused;
        self.accum_n = 0; // reinicia la acumulación al cambiar de modo
    }

    fn set_key(&mut self, code: KeyCode, pressed: bool) {
        match code {
            KeyCode::KeyW => self.keys.fwd = pressed,
            KeyCode::KeyS => self.keys.back = pressed,
            KeyCode::KeyA => self.keys.left = pressed,
            KeyCode::KeyD => self.keys.right = pressed,
            KeyCode::KeyR | KeyCode::KeyE => self.keys.up = pressed,
            KeyCode::KeyF | KeyCode::KeyQ => self.keys.down = pressed,
            KeyCode::ArrowLeft => self.keys.yaw_l = pressed,
            KeyCode::ArrowRight => self.keys.yaw_r = pressed,
            KeyCode::ArrowUp => self.keys.pitch_u = pressed,
            KeyCode::ArrowDown => self.keys.pitch_d = pressed,
            _ => {}
        }
    }

    fn forward(&self) -> [f32; 3] {
        let (cp, sp) = (self.pitch.cos(), self.pitch.sin());
        let (cy, sy) = (self.yaw.cos(), self.yaw.sin());
        [cp * sy, sp, -cp * cy]
    }

    // ---- Cámara: misma construcción de rayo que el shader (core.wgsl) ----
    /// Base de la cámara (derecha, arriba, delante), idéntica al shader.
    fn cam_basis(&self) -> ([f32; 3], [f32; 3], [f32; 3]) {
        let fwd = norm3(self.forward());
        let right = norm3(cross3(fwd, [0.0, 1.0, 0.0]));
        let up = cross3(right, fwd);
        (right, up, fwd)
    }

    /// Proyecta un punto del mundo a píxeles de ventana. None si está detrás.
    fn project(&self, p: [f32; 3]) -> Option<([f32; 2], f32)> {
        project_point(
            self.cam_pos,
            self.forward(),
            self.size.width as f32,
            self.size.height as f32,
            p,
        )
    }

    /// Rayo (origen, dirección) que pasa por un píxel de ventana.
    fn cursor_ray(&self, cx: f32, cy: f32) -> ([f32; 3], [f32; 3]) {
        let (right, up, fwd) = self.cam_basis();
        let aspect = self.size.width as f32 / self.size.height.max(1) as f32;
        let ux = (cx / self.size.width as f32 * 2.0 - 1.0) * aspect;
        let uy = 1.0 - cy / self.size.height as f32 * 2.0;
        let rd = norm3([
            ux * right[0] + uy * up[0] + 1.5 * fwd[0],
            ux * right[1] + uy * up[1] + 1.5 * fwd[1],
            ux * right[2] + uy * up[2] + 1.5 * fwd[2],
        ]);
        (self.cam_pos, rd)
    }

    /// Puntos del gizmo en pantalla: [centro, puntaX, puntaY, puntaZ].
    /// La longitud de los ejes es ~constante en pantalla (escala con la distancia).
    fn gizmo_pts(&self) -> Option<[[f32; 2]; 4]> {
        let i = self.selected;
        if i < 0 || i as usize >= self.objects.len() {
            return None;
        }
        let c = self.objects[i as usize].pos;
        let (cpx, depth) = self.project(c)?;
        let len = (0.13 * depth).clamp(0.35, 1.0e3);
        let tx = self.project([c[0] + len, c[1], c[2]])?.0;
        let ty = self.project([c[0], c[1] + len, c[2]])?.0;
        let tz = self.project([c[0], c[1], c[2] + len])?.0;
        Some([cpx, tx, ty, tz])
    }

    /// ¿El cursor está sobre un eje del gizmo? 1=X 2=Y 3=Z, 0=ninguno.
    fn pick_axis(&self, cur: [f32; 2]) -> u8 {
        if let Some(g) = self.gizmo_pts() {
            let dx = dist_seg(cur, g[0], g[1]);
            let dy = dist_seg(cur, g[0], g[2]);
            let dz = dist_seg(cur, g[0], g[3]);
            let m = dx.min(dy).min(dz);
            if m < 9.0 {
                return if m == dx {
                    1
                } else if m == dy {
                    2
                } else {
                    3
                };
            }
        }
        0
    }

    /// Objeto bajo el cursor (proyección del centro + radio aparente). -1 si ninguno.
    fn pick_object(&self, cur: [f32; 2]) -> i32 {
        let mut best = -1i32;
        let mut bestd = 1.0e9f32;
        for (i, o) in self.objects.iter().enumerate() {
            if let Some((px, _)) = self.project(o.pos) {
                let rad = match self.project([o.pos[0] + o.size, o.pos[1], o.pos[2]]) {
                    Some((e, _)) => dist2d(px, e).max(12.0),
                    None => 18.0,
                };
                let d = dist2d(px, cur);
                if d < rad + 6.0 && d < bestd {
                    bestd = d;
                    best = i as i32;
                }
            }
        }
        best
    }

    /// Clic izquierdo: agarra un eje del gizmo, o selecciona un objeto.
    fn on_left_down(&mut self) {
        let cur = self.cursor_pos;
        self.drag_moved = false;
        if self.selected >= 0 {
            let ax = self.pick_axis(cur);
            if ax != 0 {
                self.drag_mode = ax;
                self.drag_start_cursor = cur;
                self.drag_start_pos = self.objects[self.selected as usize].pos;
                return;
            }
        }
        let hit = self.pick_object(cur);
        if hit >= 0 {
            self.selected = hit;
            self.accum_n = 0;
            self.drag_mode = 4; // arrastre en plano XZ
            self.drag_start_cursor = cur;
            self.drag_start_pos = self.objects[hit as usize].pos;
            let (ro, rd) = self.cursor_ray(cur[0], cur[1]);
            self.drag_plane_off = match ray_plane(ro, rd, self.drag_start_pos[1]) {
                Some(hp) => [
                    self.drag_start_pos[0] - hp[0],
                    0.0,
                    self.drag_start_pos[2] - hp[2],
                ],
                None => [0.0, 0.0, 0.0],
            };
        } else {
            self.selected = -1;
            self.drag_mode = 0;
        }
    }

    /// El cursor se movió con el botón izquierdo: aplica el arrastre.
    fn update_drag(&mut self) {
        if self.drag_mode == 0 || self.selected < 0 {
            return;
        }
        let cur = self.cursor_pos;
        let i = self.selected as usize;
        let start = self.drag_start_pos;
        let mut np = self.objects[i].pos;
        if self.drag_mode == 4 {
            let (ro, rd) = self.cursor_ray(cur[0], cur[1]);
            if let Some(hp) = ray_plane(ro, rd, start[1]) {
                np[0] = hp[0] + self.drag_plane_off[0];
                np[2] = hp[2] + self.drag_plane_off[2];
            }
        } else {
            let axis = match self.drag_mode {
                1 => [1.0f32, 0.0, 0.0],
                2 => [0.0, 1.0, 0.0],
                _ => [0.0, 0.0, 1.0],
            };
            let p1 = [start[0] + axis[0], start[1] + axis[1], start[2] + axis[2]];
            if let (Some((c0, _)), Some((t0, _))) = (self.project(start), self.project(p1)) {
                let sdir = [t0[0] - c0[0], t0[1] - c0[1]];
                let slen = (sdir[0] * sdir[0] + sdir[1] * sdir[1]).sqrt().max(1e-3);
                let dcur = [
                    cur[0] - self.drag_start_cursor[0],
                    cur[1] - self.drag_start_cursor[1],
                ];
                // píxeles del cursor a lo largo del eje / píxeles por unidad de mundo
                let world = (dcur[0] * sdir[0] + dcur[1] * sdir[1]) / (slen * slen);
                np = [
                    start[0] + axis[0] * world,
                    start[1] + axis[1] * world,
                    start[2] + axis[2] * world,
                ];
            }
        }
        if np != self.objects[i].pos {
            self.objects[i].pos = np;
            self.obj_dirty = true;
            self.drag_moved = true;
            self.accum_n = 0;
        }
    }

    /// Soltar el botón: si se movió algo, escribe las posiciones (las lee el editor).
    fn on_left_up(&mut self) {
        if self.drag_mode != 0 && self.drag_moved {
            self.write_live();
        }
        self.drag_mode = 0;
        self.drag_moved = false;
    }

    /// Escribe scene.live.txt con las posiciones actuales (índice x y z).
    fn write_live(&self) {
        let mut s = String::new();
        for (i, o) in self.objects.iter().enumerate() {
            s.push_str(&format!(
                "{} {:.5} {:.5} {:.5}\n",
                i, o.pos[0], o.pos[1], o.pos[2]
            ));
        }
        let _ = std::fs::write(live_path(), s);
    }

    /// Botón de ratón pulsado/soltado. El derecho activa el "modo vuelo" de
    /// Unreal: oculta y confina el cursor para mirar con el ratón.
    fn on_mouse_button(&mut self, button: winit::event::MouseButton, pressed: bool) {
        use winit::event::MouseButton;
        match button {
            MouseButton::Right => {
                self.rmb = pressed;
                let mode = if pressed {
                    winit::window::CursorGrabMode::Confined
                } else {
                    winit::window::CursorGrabMode::None
                };
                let _ = self.window.set_cursor_grab(mode);
                self.window.set_cursor_visible(!pressed);
            }
            MouseButton::Middle => self.mmb = pressed,
            MouseButton::Left => {
                self.lmb = pressed;
                if pressed {
                    self.on_left_down();
                } else {
                    self.on_left_up();
                }
            }
            _ => {}
        }
    }

    /// Movimiento crudo del ratón. En modo vuelo (botón derecho) gira la cámara;
    /// con el botón central hace pan.
    fn on_mouse_motion(&mut self, dx: f64, dy: f64) {
        if self.rmb {
            let s = 0.0024;
            self.yaw += dx as f32 * s;
            self.pitch = (self.pitch - dy as f32 * s).clamp(-1.4, 1.4);
            self.cam_dirty = true;
        } else if self.mmb {
            let f = self.forward();
            let r = norm3(cross3(f, [0.0, 1.0, 0.0]));
            let up = norm3(cross3(r, f));
            let p = 0.006 * self.move_speed.max(1.0);
            for i in 0..3 {
                self.cam_pos[i] += -r[i] * dx as f32 * p + up[i] * dy as f32 * p;
            }
            self.cam_dirty = true;
        }
    }

    /// Rueda: en modo vuelo ajusta la velocidad; si no, hace dolly (acercar/alejar).
    fn on_wheel(&mut self, scroll: f32) {
        if self.rmb {
            self.move_speed = (self.move_speed * 1.15f32.powf(scroll)).clamp(0.2, 60.0);
        } else {
            let f = self.forward();
            for i in 0..3 {
                self.cam_pos[i] += f[i] * scroll * 0.6;
            }
            self.cam_dirty = true;
        }
    }

    /// Aplica teclado y devuelve true si la cámara cambió este frame.
    fn update_camera(&mut self, dt: f32) -> bool {
        let look = 1.8;
        let mut moved = self.cam_dirty; // ratón/rueda ya marcaron cambios
        self.cam_dirty = false;

        // Mirar con flechas (sin ratón) — siempre disponible
        if self.keys.yaw_l {
            self.yaw -= look * dt;
            moved = true;
        }
        if self.keys.yaw_r {
            self.yaw += look * dt;
            moved = true;
        }
        if self.keys.pitch_u {
            self.pitch += look * dt;
            moved = true;
        }
        if self.keys.pitch_d {
            self.pitch -= look * dt;
            moved = true;
        }
        self.pitch = self.pitch.clamp(-1.4, 1.4);

        // Mover con WASD/EQ SOLO en modo vuelo (botón derecho), como Unreal.
        if self.rmb {
            let f = self.forward();
            let r = norm3(cross3(f, [0.0, 1.0, 0.0]));
            let s = self.move_speed * dt;
            let mut step = |d: [f32; 3], k: f32| {
                self.cam_pos[0] += d[0] * k;
                self.cam_pos[1] += d[1] * k;
                self.cam_pos[2] += d[2] * k;
            };
            if self.keys.fwd {
                step(f, s);
                moved = true;
            }
            if self.keys.back {
                step(f, -s);
                moved = true;
            }
            if self.keys.right {
                step(r, s);
                moved = true;
            }
            if self.keys.left {
                step(r, -s);
                moved = true;
            }
            if self.keys.up {
                self.cam_pos[1] += s;
                moved = true;
            }
            if self.keys.down {
                self.cam_pos[1] -= s;
                moved = true;
            }
        }
        moved
    }

    /// Hot-reload: si la escena generada cambió en disco, recompila el shader.
    fn check_reload(&mut self) {
        let m = std::fs::metadata(scene_path()).and_then(|x| x.modified()).ok();
        if m != self.scene_mtime {
            self.scene_mtime = m;
            if self.frame_index > 0 {
                let (sp, bgl) = make_pipeline(
                    &self.device, HDR_FORMAT, additive_blend(), self.asset_filterable);
                self.scene_pipeline = sp;
                // La escena cambió: recargar posiciones (puede haber objetos nuevos).
                self.objects = load_objects();
                if self.selected >= self.objects.len() as i32 {
                    self.selected = -1;
                }
                self.obj_dirty = true;
                self.scene_bg = make_scene_bg(
                    &self.device, &bgl, &self.uniform_buf,
                    &self.asset_view, &self.asset_sampler, &self.obj_buf);
                self.accum_n = 0;
            }
        }
    }

    fn resize(&mut self, new: winit::dpi::PhysicalSize<u32>) {
        if new.width > 0 && new.height > 0 {
            self.size = new;
            self.config.width = new.width;
            self.config.height = new.height;
            self.surface.configure(&self.device, &self.config);
            self.hdr_w = ((new.width as f32 * self.render_scale) as u32).max(1);
            self.hdr_h = ((new.height as f32 * self.render_scale) as u32).max(1);
            self.hdr_view = make_hdr(&self.device, self.hdr_w, self.hdr_h);
            self.present_bg = make_present_bg(
                &self.device, &self.present_bgl, &self.inv_buf, &self.hdr_view, &self.sampler);
            self.scene_depth = make_depth(&self.device, self.hdr_w, self.hdr_h);
            self.accum_n = 0;
        }
    }

    fn render(&mut self) -> Result<(), wgpu::SurfaceError> {
        let now = Instant::now();
        let dt = (now - self.last).as_secs_f32().min(0.1);
        self.last = now;

        // Contador de FPS al título (para medir el rendimiento de verdad).
        self.fps_accum += dt;
        self.fps_frames += 1;
        if self.fps_accum >= 0.5 {
            let fps = self.fps_frames as f32 / self.fps_accum;
            let mode = if self.paused { "refinando" } else { "vivo" };
            self.window.set_title(&format!(
                "RTGEngine · RTGEngine — {fps:.0} fps · {mode} · clic dcho+WASD volar · Espacio refinar · Esc"
            ));
            self.fps_accum = 0.0;
            self.fps_frames = 0;
        }

        if self.frame_index % 12 == 0 {
            self.check_reload();
        }
        let moved = self.update_camera(dt);

        // El tiempo avanza si NO está en pausa. Acumulamos (refinamos) solo si
        // está en pausa Y la cámara no se mueve; si algo cambia, se reinicia.
        if !self.paused {
            self.sim_time += dt;
        }
        if self.paused && !moved {
            self.accum_n += 1;
        } else {
            self.accum_n = 0;
        }
        // Con malla rasterizada no acumulamos (se sobreescribe cada frame).
        if self.mesh.is_some() {
            self.accum_n = 0;
        }
        let n = self.accum_n;

        let jx = (halton(self.frame_index + 1, 2) - 0.5) * 2.0 / self.hdr_w as f32;
        let jy = (halton(self.frame_index + 1, 3) - 0.5) * 2.0 / self.hdr_h as f32;
        let f = self.forward();
        let u = Uniforms {
            resolution: [self.hdr_w as f32, self.hdr_h as f32],
            time: self.sim_time,
            sample_count: (n + 1) as f32,
            jitter: [jx, jy],
            _pad: [self.frame_index as f32, 0.0], // semilla de ruido del path tracer
            cam_pos: [self.cam_pos[0], self.cam_pos[1], self.cam_pos[2], 0.0],
            cam_fwd: [f[0], f[1], f[2], 0.0],
            asset: self.asset_uniform,
        };
        self.queue.write_buffer(&self.uniform_buf, 0, bytemuck::bytes_of(&u));
        // Posiciones de objetos (solo si cambiaron: coste cero, sin recompilar).
        if self.obj_dirty {
            self.queue.write_buffer(
                &self.obj_buf, 0, bytemuck::cast_slice(&obj_buffer_data(&self.objects)));
            self.obj_dirty = false;
        }
        // Datos del gizmo para el pase de presente (overlay siempre encima).
        // RU = [1/N, on, eje_resaltado, _, centro.xy, puntaX.xy, puntaY.xy, puntaZ.xy]
        let mut ru = [0.0f32; 12];
        ru[0] = 1.0 / (n + 1) as f32;
        if let Some(g) = self.gizmo_pts() {
            let hl = if self.drag_mode >= 1 && self.drag_mode <= 3 {
                self.drag_mode
            } else {
                self.pick_axis(self.cursor_pos)
            };
            ru[1] = 1.0;
            ru[2] = hl as f32;
            ru[4] = g[0][0];
            ru[5] = g[0][1];
            ru[6] = g[1][0];
            ru[7] = g[1][1];
            ru[8] = g[2][0];
            ru[9] = g[2][1];
            ru[10] = g[3][0];
            ru[11] = g[3][1];
        }
        self.queue.write_buffer(&self.inv_buf, 0, bytemuck::bytes_of(&ru));

        let frame = self.surface.get_current_texture()?;
        let view = frame
            .texture
            .create_view(&wgpu::TextureViewDescriptor::default());
        let mut encoder = self
            .device
            .create_command_encoder(&wgpu::CommandEncoderDescriptor { label: Some("encoder") });

        // 1) escena -> HDR (mezcla aditiva; limpia solo en la 1ª muestra)
        {
            let load = if n == 0 {
                wgpu::LoadOp::Clear(wgpu::Color::TRANSPARENT)
            } else {
                wgpu::LoadOp::Load
            };
            let mut rp = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("scene-pass"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &self.hdr_view,
                    resolve_target: None,
                    ops: wgpu::Operations { load, store: wgpu::StoreOp::Store },
                })],
                depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                    view: &self.scene_depth,
                    depth_ops: Some(wgpu::Operations {
                        load: wgpu::LoadOp::Clear(1.0),
                        store: wgpu::StoreOp::Store,
                    }),
                    stencil_ops: None,
                }),
                timestamp_writes: None,
                occlusion_query_set: None,
            });
            rp.set_pipeline(&self.scene_pipeline);
            rp.set_bind_group(0, &self.scene_bg, &[]);
            rp.draw(0..3, 0..1);
        }
        // 1.5) malla (personaje FBX) rasterizada SOBRE la escena, con profundidad.
        if let Some(m) = &self.mesh {
            let aspect = self.hdr_w as f32 / self.hdr_h.max(1) as f32;
            let fwd = norm3(self.forward());
            let right = norm3(cross3(fwd, [0.0, 1.0, 0.0]));
            let up = cross3(right, fwd);
            let view_m = mat_view(self.cam_pos, right, up, fwd);
            let proj = mat_proj(aspect, 0.05, 120.0);
            let vp = mat_mul(&proj, &view_m);
            let mvp = mat_mul(&vp, &m.model);
            let mu = MeshUniforms {
                mvp,
                model: m.model,
                light_dir: [0.4, 0.9, 0.45, 1.0],   // xyz=sol direccional, w=escala (vivo=1)
            };
            self.queue.write_buffer(&m.uniform_buf, 0, bytemuck::bytes_of(&mu));
            // Matrices de huesos del frame actual (animación por tiempo).
            self.queue.write_buffer(
                &m.bone_buf, 0, bytemuck::cast_slice(&bone_frame(&m.anim, self.sim_time)));
            let mut rp = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("mesh-pass"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &self.hdr_view,
                    resolve_target: None,
                    ops: wgpu::Operations { load: wgpu::LoadOp::Load, store: wgpu::StoreOp::Store },
                })],
                depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                    view: &self.scene_depth,         // comparte la profundidad del SDF
                    depth_ops: Some(wgpu::Operations {
                        load: wgpu::LoadOp::Load,    // conserva la profundidad de la escena
                        store: wgpu::StoreOp::Store,
                    }),
                    stencil_ops: None,
                }),
                timestamp_writes: None,
                occlusion_query_set: None,
            });
            rp.set_pipeline(&m.pipeline);
            rp.set_bind_group(0, &m.bg, &[]);
            rp.set_vertex_buffer(0, m.vbuf.slice(..));
            rp.draw(0..m.vcount, 0..1);
        }
        // 2) presente -> pantalla (divide la suma por n+1)
        {
            let mut rp = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("present-pass"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &view,
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Clear(wgpu::Color::BLACK),
                        store: wgpu::StoreOp::Store,
                    },
                })],
                depth_stencil_attachment: None,
                timestamp_writes: None,
                occlusion_query_set: None,
            });
            rp.set_pipeline(&self.present_pipeline);
            rp.set_bind_group(0, &self.present_bg, &[]);
            rp.draw(0..3, 0..1);
        }
        self.queue.submit(Some(encoder.finish()));
        frame.present();
        self.frame_index += 1;
        Ok(())
    }
}

/// Compone el shader: prelude (embebido) + escena (generada, leída en runtime)
/// + core (embebido). Editar el .node + reforjar cambia la escena sin
/// recompilar Rust.
fn compose_shader(device: &wgpu::Device) -> wgpu::ShaderModule {
    let prelude = include_str!("prelude.wgsl");
    let core = include_str!("core.wgsl");
    let sp = scene_path();
    let scene = std::fs::read_to_string(&sp).unwrap_or_else(|e| {
        panic!(
            "No se pudo leer la escena generada ({sp}): {e}\n\
             Genérala con:  python forge.py examples/start.scene"
        )
    });
    let shader_src = format!("{prelude}\n{scene}\n{core}");
    device.create_shader_module(wgpu::ShaderModuleDescriptor {
        label: Some("rtg-scene"),
        source: wgpu::ShaderSource::Wgsl(shader_src.into()),
    })
}

/// Crea el render pipeline del raymarcher para un formato de color dado.
/// Devuelve también el bind group layout para que el llamador ate su uniform.
fn make_pipeline(
    device: &wgpu::Device,
    format: wgpu::TextureFormat,
    blend: wgpu::BlendState,
    filterable: bool,
) -> (wgpu::RenderPipeline, wgpu::BindGroupLayout) {
    let shader = compose_shader(device);
    let sampler_ty = if filterable {
        wgpu::SamplerBindingType::Filtering
    } else {
        wgpu::SamplerBindingType::NonFiltering
    };
    let bgl = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
        label: Some("bgl"),
        entries: &[
            wgpu::BindGroupLayoutEntry {
                binding: 0,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Buffer {
                    ty: wgpu::BufferBindingType::Uniform,
                    has_dynamic_offset: false,
                    min_binding_size: None,
                },
                count: None,
            },
            // binding 1: textura 3D del SDF del modelo importado
            wgpu::BindGroupLayoutEntry {
                binding: 1,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Texture {
                    sample_type: wgpu::TextureSampleType::Float { filterable },
                    view_dimension: wgpu::TextureViewDimension::D3,
                    multisampled: false,
                },
                count: None,
            },
            wgpu::BindGroupLayoutEntry {
                binding: 2,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Sampler(sampler_ty),
                count: None,
            },
            // binding 3: posiciones de objetos en runtime (gizmo/mover)
            wgpu::BindGroupLayoutEntry {
                binding: 3,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Buffer {
                    ty: wgpu::BufferBindingType::Uniform,
                    has_dynamic_offset: false,
                    min_binding_size: None,
                },
                count: None,
            },
        ],
    });
    let layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
        label: Some("layout"),
        bind_group_layouts: &[&bgl],
        push_constant_ranges: &[],
    });
    let pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
        label: Some("raymarch-pipeline"),
        layout: Some(&layout),
        vertex: wgpu::VertexState {
            module: &shader,
            entry_point: "vs_main",
            buffers: &[],
            compilation_options: Default::default(),
        },
        fragment: Some(wgpu::FragmentState {
            module: &shader,
            entry_point: "fs_main",
            targets: &[Some(wgpu::ColorTargetState {
                format,
                blend: Some(blend),
                write_mask: wgpu::ColorWrites::ALL,
            })],
            compilation_options: Default::default(),
        }),
        primitive: wgpu::PrimitiveState::default(),
        // El raymarcher escribe profundidad (frag_depth) para que la malla
        // rasterizada se ocluya correctamente con la escena SDF.
        depth_stencil: Some(wgpu::DepthStencilState {
            format: DEPTH_FORMAT,
            depth_write_enabled: true,
            depth_compare: wgpu::CompareFunction::Always,
            stencil: Default::default(),
            bias: Default::default(),
        }),
        multisample: wgpu::MultisampleState::default(),
        multiview: None,
    });
    (pipeline, bgl)
}

fn make_scene_bg(
    device: &wgpu::Device,
    bgl: &wgpu::BindGroupLayout,
    uniform_buf: &wgpu::Buffer,
    asset_view: &wgpu::TextureView,
    asset_smp: &wgpu::Sampler,
    obj_buf: &wgpu::Buffer,
) -> wgpu::BindGroup {
    device.create_bind_group(&wgpu::BindGroupDescriptor {
        label: Some("scene_bg"),
        layout: bgl,
        entries: &[
            wgpu::BindGroupEntry {
                binding: 0,
                resource: uniform_buf.as_entire_binding(),
            },
            wgpu::BindGroupEntry {
                binding: 1,
                resource: wgpu::BindingResource::TextureView(asset_view),
            },
            wgpu::BindGroupEntry {
                binding: 2,
                resource: wgpu::BindingResource::Sampler(asset_smp),
            },
            wgpu::BindGroupEntry {
                binding: 3,
                resource: obj_buf.as_entire_binding(),
            },
        ],
    })
}

fn parse_vec3_env(name: &str, default: [f32; 3]) -> [f32; 3] {
    if let Ok(v) = std::env::var(name) {
        let parts: Vec<f32> = v.split(',').filter_map(|s| s.trim().parse().ok()).collect();
        if parts.len() == 3 {
            return [parts[0], parts[1], parts[2]];
        }
    }
    default
}

/// Carga el modelo importado (Fase 4) desde RTG_ASSET (.sdf raw f32, res^3).
/// Devuelve (vista de textura 3D, sampler, uniform [pos.xyz, escala]). Sin asset,
/// una textura 1x1x1 dummy y escala 0 (desactivado).
fn load_asset(
    device: &wgpu::Device,
    queue: &wgpu::Queue,
    filterable: bool,
) -> (wgpu::TextureView, wgpu::Sampler, [f32; 4]) {
    let filt = if filterable {
        wgpu::FilterMode::Linear
    } else {
        wgpu::FilterMode::Nearest
    };
    let sampler = device.create_sampler(&wgpu::SamplerDescriptor {
        label: Some("asset-smp"),
        address_mode_u: wgpu::AddressMode::ClampToEdge,
        address_mode_v: wgpu::AddressMode::ClampToEdge,
        address_mode_w: wgpu::AddressMode::ClampToEdge,
        mag_filter: filt,
        min_filter: filt,
        mipmap_filter: wgpu::FilterMode::Nearest,
        ..Default::default()
    });

    let make_tex = |res: u32, data: &[u8]| -> wgpu::TextureView {
        let tex = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("asset-sdf"),
            size: wgpu::Extent3d {
                width: res,
                height: res,
                depth_or_array_layers: res,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D3,
            format: wgpu::TextureFormat::R32Float,
            usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
            view_formats: &[],
        });
        queue.write_texture(
            wgpu::ImageCopyTexture {
                texture: &tex,
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
            },
            data,
            wgpu::ImageDataLayout {
                offset: 0,
                bytes_per_row: Some(res * 4),
                rows_per_image: Some(res),
            },
            wgpu::Extent3d {
                width: res,
                height: res,
                depth_or_array_layers: res,
            },
        );
        tex.create_view(&wgpu::TextureViewDescriptor::default())
    };

    if let Ok(path) = std::env::var("RTG_ASSET") {
        if let Ok(bytes) = std::fs::read(&path) {
            let n = bytes.len() / 4;
            let res = (n as f64).cbrt().round() as u32;
            if res >= 2 && (res as usize).pow(3) == n {
                let view = make_tex(res, &bytes);
                let pos = parse_vec3_env("RTG_ASSET_POS", [0.0, 0.4, 0.0]);
                let scale = std::env::var("RTG_ASSET_SCALE")
                    .ok()
                    .and_then(|s| s.parse().ok())
                    .unwrap_or(0.9f32);
                log::info!("asset cargado: {path} ({res}^3)");
                return (view, sampler, [pos[0], pos[1], pos[2], scale]);
            }
            log::warn!("asset {path}: tamaño no cúbico ({n} muestras)");
        }
    }
    let view = make_tex(1, &1.0e9f32.to_le_bytes());
    (view, sampler, [0.0, 0.0, 0.0, 0.0])
}

/// Crea una textura HDR (acumulación) y devuelve su vista. La vista mantiene
/// viva la textura, así que no hace falta guardar esta última.
fn make_hdr(device: &wgpu::Device, width: u32, height: u32) -> wgpu::TextureView {
    let tex = device.create_texture(&wgpu::TextureDescriptor {
        label: Some("hdr-accum"),
        size: wgpu::Extent3d { width, height, depth_or_array_layers: 1 },
        mip_level_count: 1,
        sample_count: 1,
        dimension: wgpu::TextureDimension::D2,
        format: HDR_FORMAT,
        usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::TEXTURE_BINDING,
        view_formats: &[],
    });
    tex.create_view(&Default::default())
}

/// Pipeline de "presente": divide la HDR acumulada por N y la pasa a pantalla.
/// Reutiliza RESOLVE_WGSL (binding 0 = 1/N, binding 1 = textura acumulada).
fn make_present(
    device: &wgpu::Device,
    surface_format: wgpu::TextureFormat,
) -> (wgpu::RenderPipeline, wgpu::BindGroupLayout) {
    let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
        label: Some("present"),
        source: wgpu::ShaderSource::Wgsl(PRESENT_WGSL.into()),
    });
    let bgl = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
        label: Some("present_bgl"),
        entries: &[
            wgpu::BindGroupLayoutEntry {
                binding: 0,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Buffer {
                    ty: wgpu::BufferBindingType::Uniform,
                    has_dynamic_offset: false,
                    min_binding_size: None,
                },
                count: None,
            },
            wgpu::BindGroupLayoutEntry {
                binding: 1,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Texture {
                    sample_type: wgpu::TextureSampleType::Float { filterable: true },
                    view_dimension: wgpu::TextureViewDimension::D2,
                    multisampled: false,
                },
                count: None,
            },
            wgpu::BindGroupLayoutEntry {
                binding: 2,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
                count: None,
            },
        ],
    });
    let layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
        label: Some("present_layout"),
        bind_group_layouts: &[&bgl],
        push_constant_ranges: &[],
    });
    let pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
        label: Some("present_pipeline"),
        layout: Some(&layout),
        vertex: wgpu::VertexState {
            module: &shader,
            entry_point: "vs",
            buffers: &[],
            compilation_options: Default::default(),
        },
        fragment: Some(wgpu::FragmentState {
            module: &shader,
            entry_point: "fs",
            targets: &[Some(wgpu::ColorTargetState {
                format: surface_format,
                blend: Some(wgpu::BlendState::REPLACE),
                write_mask: wgpu::ColorWrites::ALL,
            })],
            compilation_options: Default::default(),
        }),
        primitive: wgpu::PrimitiveState::default(),
        depth_stencil: None,
        multisample: wgpu::MultisampleState::default(),
        multiview: None,
    });
    (pipeline, bgl)
}

fn make_present_bg(
    device: &wgpu::Device,
    bgl: &wgpu::BindGroupLayout,
    inv_buf: &wgpu::Buffer,
    hdr_view: &wgpu::TextureView,
    sampler: &wgpu::Sampler,
) -> wgpu::BindGroup {
    device.create_bind_group(&wgpu::BindGroupDescriptor {
        label: Some("present_bg"),
        layout: bgl,
        entries: &[
            wgpu::BindGroupEntry {
                binding: 0,
                resource: inv_buf.as_entire_binding(),
            },
            wgpu::BindGroupEntry {
                binding: 1,
                resource: wgpu::BindingResource::TextureView(hdr_view),
            },
            wgpu::BindGroupEntry {
                binding: 2,
                resource: wgpu::BindingResource::Sampler(sampler),
            },
        ],
    })
}

/// Shader de "presente": reconstruye (upscale bilineal) la HDR a resolución de
/// pantalla y divide por el nº de muestras. Usado por el viewport en vivo.
const PRESENT_WGSL: &str = r#"
struct RU {
    inv_samples : f32,
    giz_on      : f32,   // 1 si hay objeto seleccionado (mostrar gizmo)
    giz_axis    : f32,   // eje resaltado: 1=X 2=Y 3=Z, 0=ninguno
    _p0         : f32,
    center      : vec2<f32>,
    tipx        : vec2<f32>,
    tipy        : vec2<f32>,
    tipz        : vec2<f32>,
};
@group(0) @binding(0) var<uniform> R : RU;
@group(0) @binding(1) var tex : texture_2d<f32>;
@group(0) @binding(2) var smp : sampler;

struct VO { @builtin(position) pos : vec4<f32>, @location(0) uv : vec2<f32>, };

@vertex
fn vs(@builtin(vertex_index) vid : u32) -> VO {
    var o : VO;
    let p = vec2<f32>(f32((vid << 1u) & 2u), f32(vid & 2u));
    o.uv = vec2<f32>(p.x, 1.0 - p.y);
    o.pos = vec4<f32>(p * 2.0 - 1.0, 0.0, 1.0);
    return o;
}

fn aces(x : vec3<f32>) -> vec3<f32> {
    let a = 2.51; let b = 0.03; let c = 2.43; let d = 0.59; let e = 0.14;
    return clamp((x * (a * x + b)) / (x * (c * x + d) + e),
                 vec3<f32>(0.0), vec3<f32>(1.0));
}

// Distancia 2D al segmento a-b (para dibujar los ejes del gizmo).
fn seg_d(p : vec2<f32>, a : vec2<f32>, b : vec2<f32>) -> f32 {
    let ab = b - a;
    let t = clamp(dot(p - a, ab) / max(dot(ab, ab), 1e-4), 0.0, 1.0);
    return length(p - (a + ab * t));
}

// Dibuja un eje (línea + cabeza) sobre el color, resaltando el eje activo.
fn axis(col : vec3<f32>, p : vec2<f32>, a : vec2<f32>, b : vec2<f32>,
        tint : vec3<f32>, hl : f32, id : f32) -> vec3<f32> {
    let w = select(2.0, 3.4, abs(hl - id) < 0.5);
    let line = 1.0 - smoothstep(w - 1.0, w + 1.0, seg_d(p, a, b));
    let head = 1.0 - smoothstep(4.0, 6.5, length(p - b));
    return mix(col, tint, max(line, head));
}

@fragment
fn fs(in : VO) -> @location(0) vec4<f32> {
    let c = textureSample(tex, smp, in.uv).rgb * R.inv_samples;
    var o = aces(c);
    // Dither de salida (±1/255, imperceptible): rompe el banding de 8 bits.
    let r = fract(sin(dot(in.pos.xy, vec2<f32>(12.9898, 78.233))) * 43758.5453);
    o = o + (r - 0.5) * (1.0 / 255.0);
    // Gizmo: overlay en espacio de pantalla, siempre encima de la escena.
    if (R.giz_on > 0.5) {
        let fp = in.pos.xy;
        o = axis(o, fp, R.center, R.tipx, vec3<f32>(0.95, 0.26, 0.26), R.giz_axis, 1.0);
        o = axis(o, fp, R.center, R.tipy, vec3<f32>(0.36, 0.95, 0.40), R.giz_axis, 2.0);
        o = axis(o, fp, R.center, R.tipz, vec3<f32>(0.36, 0.56, 0.98), R.giz_axis, 3.0);
        let cm = 1.0 - smoothstep(3.0, 5.0, length(fp - R.center));
        o = mix(o, vec3<f32>(1.0, 0.9, 0.35), cm);
    }
    return vec4<f32>(o, 1.0);
}
"#;

/// Shader de resolución (snapshot): lee la HDR exacta y divide por el nº de muestras.
const RESOLVE_WGSL: &str = r#"
struct RU { inv_samples : f32, _p0 : f32, _p1 : f32, _p2 : f32, };
@group(0) @binding(0) var<uniform> R : RU;
@group(0) @binding(1) var accum_tex : texture_2d<f32>;

@vertex
fn vs(@builtin(vertex_index) vid : u32) -> @builtin(position) vec4<f32> {
    var p = array<vec2<f32>, 3>(
        vec2<f32>(-1.0, -1.0), vec2<f32>(3.0, -1.0), vec2<f32>(-1.0, 3.0));
    return vec4<f32>(p[vid], 0.0, 1.0);
}

fn aces(x : vec3<f32>) -> vec3<f32> {
    let a = 2.51; let b = 0.03; let c = 2.43; let d = 0.59; let e = 0.14;
    return clamp((x * (a * x + b)) / (x * (c * x + d) + e),
                 vec3<f32>(0.0), vec3<f32>(1.0));
}

@fragment
fn fs(@builtin(position) pos : vec4<f32>) -> @location(0) vec4<f32> {
    let c = textureLoad(accum_tex, vec2<i32>(i32(pos.x), i32(pos.y)), 0).rgb * R.inv_samples;
    var o = aces(c);
    // Dither de salida (±1/255, imperceptible): rompe el banding de 8 bits.
    let r = fract(sin(dot(pos.xy, vec2<f32>(12.9898, 78.233))) * 43758.5453);
    o = o + (r - 0.5) * (1.0 / 255.0);
    return vec4<f32>(o, 1.0);
}
"#;

/// Modo headless: renderiza un frame (en el instante `time`) a un PNG, sin
/// abrir ventana, acumulando `samples` muestras. Útil para verificar y el manual.
fn run_snapshot(path: &str, time: f32, width: u32, height: u32, samples: u32) {
    pollster::block_on(async {
        let instance = wgpu::Instance::new(wgpu::InstanceDescriptor {
            backends: wgpu::Backends::PRIMARY,
            ..Default::default()
        });
        let adapter = instance
            .request_adapter(&wgpu::RequestAdapterOptions {
                power_preference: wgpu::PowerPreference::HighPerformance,
                compatible_surface: None,
                force_fallback_adapter: false,
            })
            .await
            .expect("sin adaptador de GPU");
        let asset_filterable = adapter
            .features()
            .contains(wgpu::Features::FLOAT32_FILTERABLE);
        let req_features = if asset_filterable {
            wgpu::Features::FLOAT32_FILTERABLE
        } else {
            wgpu::Features::empty()
        };
        let (device, queue) = adapter
            .request_device(
                &wgpu::DeviceDescriptor {
                    label: Some("snapshot"),
                    required_features: req_features,
                    required_limits: wgpu::Limits::default(),
                },
                None,
            )
            .await
            .unwrap();

        // --- Cache v0: amortización temporal -------------------------------
        // Acumulamos `samples` renders, cada uno con un jitter sub-píxel, en un
        // buffer HDR mediante mezcla aditiva; al final dividimos por N (resolve).
        // Es el principio del Cache: repartir la calidad entre frames en vez
        // de pagarla toda en uno. Con la vista quieta, la imagen converge.
        let scene_format = wgpu::TextureFormat::Rgba16Float; // HDR, mezclable
        let out_format = wgpu::TextureFormat::Rgba8UnormSrgb;

        let additive = wgpu::BlendState {
            color: wgpu::BlendComponent {
                src_factor: wgpu::BlendFactor::One,
                dst_factor: wgpu::BlendFactor::One,
                operation: wgpu::BlendOperation::Add,
            },
            alpha: wgpu::BlendComponent {
                src_factor: wgpu::BlendFactor::One,
                dst_factor: wgpu::BlendFactor::One,
                operation: wgpu::BlendOperation::Add,
            },
        };
        let (scene_pipeline, bgl) =
            make_pipeline(&device, scene_format, additive, asset_filterable);

        let uniform_buf = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("u"),
            size: std::mem::size_of::<Uniforms>() as u64,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let (asset_view, asset_smp, asset_uniform) =
            load_asset(&device, &queue, asset_filterable);
        // Posiciones de objetos (binding 3): el snapshot usa las del sidecar.
        let objects = load_objects();
        let obj_buf = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("obj-pos"),
            size: (MAX_OBJ * 16) as u64,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        queue.write_buffer(&obj_buf, 0, bytemuck::cast_slice(&obj_buffer_data(&objects)));
        let scene_bg =
            make_scene_bg(&device, &bgl, &uniform_buf, &asset_view, &asset_smp, &obj_buf);

        let accum = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("accum-hdr"),
            size: wgpu::Extent3d { width, height, depth_or_array_layers: 1 },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: scene_format,
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::TEXTURE_BINDING,
            view_formats: &[],
        });
        let accum_view = accum.create_view(&Default::default());
        let snap_depth = make_depth(&device, width, height);   // compartida SDF/malla

        // Bucle de acumulación: cada muestra con su jitter de Halton.
        for i in 0..samples {
            let jx = (halton(i + 1, 2) - 0.5) * 2.0 / width as f32;
            let jy = (halton(i + 1, 3) - 0.5) * 2.0 / height as f32;
            let u = Uniforms {
                resolution: [width as f32, height as f32],
                time,
                sample_count: samples as f32,
                jitter: [jx, jy],
                _pad: [i as f32, 0.0], // semilla de ruido distinta por muestra
                // cámara por defecto (la vista clásica del Edén)
                cam_pos: [0.0, 1.2, 5.0, 0.0],
                cam_fwd: [0.0, -0.19867, -0.98007, 0.0],
                asset: asset_uniform,
            };
            queue.write_buffer(&uniform_buf, 0, bytemuck::bytes_of(&u));

            let mut enc =
                device.create_command_encoder(&wgpu::CommandEncoderDescriptor { label: None });
            {
                let load = if i == 0 {
                    wgpu::LoadOp::Clear(wgpu::Color::TRANSPARENT)
                } else {
                    wgpu::LoadOp::Load
                };
                let mut rp = enc.begin_render_pass(&wgpu::RenderPassDescriptor {
                    label: Some("accum-pass"),
                    color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                        view: &accum_view,
                        resolve_target: None,
                        ops: wgpu::Operations { load, store: wgpu::StoreOp::Store },
                    })],
                    depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                        view: &snap_depth,
                        depth_ops: Some(wgpu::Operations {
                            load: wgpu::LoadOp::Clear(1.0),
                            store: wgpu::StoreOp::Store,
                        }),
                        stencil_ops: None,
                    }),
                    timestamp_writes: None,
                    occlusion_query_set: None,
                });
                rp.set_pipeline(&scene_pipeline);
                rp.set_bind_group(0, &scene_bg, &[]);
                rp.draw(0..3, 0..1);
            }
            queue.submit(Some(enc.finish()));
        }

        // --- Malla (personaje FBX) en el snapshot, si RTG_MESH está puesto ---
        if let Some((verts, vcount, model)) = load_mesh() {
            let (pipeline, mbgl) = make_mesh_pipeline(&device, scene_format);
            let vbuf = device.create_buffer(&wgpu::BufferDescriptor {
                label: Some("snap-mesh-vbuf"),
                size: verts.len() as u64,
                usage: wgpu::BufferUsages::VERTEX | wgpu::BufferUsages::COPY_DST,
                mapped_at_creation: false,
            });
            queue.write_buffer(&vbuf, 0, &verts);
            let (tv, ts) = load_mesh_texture(&device, &queue);
            let mu_buf = device.create_buffer(&wgpu::BufferDescriptor {
                label: Some("snap-mesh-u"),
                size: std::mem::size_of::<MeshUniforms>() as u64,
                usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
                mapped_at_creation: false,
            });
            let cam = [0.0f32, 1.2, 5.0];
            let fwd = norm3([0.0, -0.19867, -0.98007]);
            let right = norm3(cross3(fwd, [0.0, 1.0, 0.0]));
            let up = cross3(right, fwd);
            let vp = mat_mul(&mat_proj(width as f32 / height as f32, 0.05, 120.0),
                             &mat_view(cam, right, up, fwd));
            let mvp = mat_mul(&vp, &model);
            // w = nº de muestras: compensa el /N del resolve (acumulación).
            let mu = MeshUniforms { mvp, model, light_dir: [0.4, 0.9, 0.45, samples as f32] };
            queue.write_buffer(&mu_buf, 0, bytemuck::bytes_of(&mu));
            let bone_buf = device.create_buffer(&wgpu::BufferDescriptor {
                label: Some("snap-mesh-bones"),
                size: (MAX_BONES * 64) as u64,
                usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
                mapped_at_creation: false,
            });
            queue.write_buffer(&bone_buf, 0, bytemuck::cast_slice(&bone_frame(&load_anim(), time)));
            let bg = device.create_bind_group(&wgpu::BindGroupDescriptor {
                label: Some("snap-mesh-bg"),
                layout: &mbgl,
                entries: &[
                    wgpu::BindGroupEntry { binding: 0, resource: mu_buf.as_entire_binding() },
                    wgpu::BindGroupEntry { binding: 1, resource: wgpu::BindingResource::TextureView(&tv) },
                    wgpu::BindGroupEntry { binding: 2, resource: wgpu::BindingResource::Sampler(&ts) },
                    wgpu::BindGroupEntry { binding: 3, resource: bone_buf.as_entire_binding() },
                ],
            });
            let mut enc = device.create_command_encoder(&wgpu::CommandEncoderDescriptor { label: None });
            {
                let mut rp = enc.begin_render_pass(&wgpu::RenderPassDescriptor {
                    label: Some("snap-mesh-pass"),
                    color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                        view: &accum_view,
                        resolve_target: None,
                        ops: wgpu::Operations { load: wgpu::LoadOp::Load, store: wgpu::StoreOp::Store },
                    })],
                    depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                        view: &snap_depth,           // comparte la profundidad del SDF
                        depth_ops: Some(wgpu::Operations { load: wgpu::LoadOp::Load, store: wgpu::StoreOp::Store }),
                        stencil_ops: None,
                    }),
                    timestamp_writes: None,
                    occlusion_query_set: None,
                });
                rp.set_pipeline(&pipeline);
                rp.set_bind_group(0, &bg, &[]);
                rp.set_vertex_buffer(0, vbuf.slice(..));
                rp.draw(0..vcount, 0..1);
            }
            queue.submit(Some(enc.finish()));
        }

        // --- Resolve: divide la suma por N y pasa a sRGB ---
        let resolve_shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("resolve"),
            source: wgpu::ShaderSource::Wgsl(RESOLVE_WGSL.into()),
        });
        let inv = [1.0f32 / samples.max(1) as f32, 0.0, 0.0, 0.0];
        let inv_buf = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("inv"),
            size: 16,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        queue.write_buffer(&inv_buf, 0, bytemuck::bytes_of(&inv));

        let resolve_bgl = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("resolve_bgl"),
            entries: &[
                wgpu::BindGroupLayoutEntry {
                    binding: 0,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Uniform,
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                    count: None,
                },
                wgpu::BindGroupLayoutEntry {
                    binding: 1,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Texture {
                        sample_type: wgpu::TextureSampleType::Float { filterable: false },
                        view_dimension: wgpu::TextureViewDimension::D2,
                        multisampled: false,
                    },
                    count: None,
                },
            ],
        });
        let resolve_bg = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("resolve_bg"),
            layout: &resolve_bgl,
            entries: &[
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: inv_buf.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: wgpu::BindingResource::TextureView(&accum_view),
                },
            ],
        });
        let resolve_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("resolve_layout"),
            bind_group_layouts: &[&resolve_bgl],
            push_constant_ranges: &[],
        });
        let resolve_pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("resolve_pipeline"),
            layout: Some(&resolve_layout),
            vertex: wgpu::VertexState {
                module: &resolve_shader,
                entry_point: "vs",
                buffers: &[],
                compilation_options: Default::default(),
            },
            fragment: Some(wgpu::FragmentState {
                module: &resolve_shader,
                entry_point: "fs",
                targets: &[Some(wgpu::ColorTargetState {
                    format: out_format,
                    blend: Some(wgpu::BlendState::REPLACE),
                    write_mask: wgpu::ColorWrites::ALL,
                })],
                compilation_options: Default::default(),
            }),
            primitive: wgpu::PrimitiveState::default(),
            depth_stencil: None,
            multisample: wgpu::MultisampleState::default(),
            multiview: None,
        });

        let out_tex = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("out"),
            size: wgpu::Extent3d { width, height, depth_or_array_layers: 1 },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: out_format,
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC,
            view_formats: &[],
        });
        let out_view = out_tex.create_view(&Default::default());

        // Test del pase de PRESENTE: renderiza por el MISMO pipeline que el
        // viewport en vivo (PRESENT_WGSL + textureSample), para diagnosticar el
        // "todo negro" sin captura de pantalla.  RTG_PRESENT_TEST=1
        let present_test = std::env::var("RTG_PRESENT_TEST").is_ok();
        let (present_pipeline, present_bg) = if present_test {
            let (pp, pbgl) = make_present(&device, out_format);
            let p_inv = device.create_buffer(&wgpu::BufferDescriptor {
                label: Some("p-inv"),
                size: 48,
                usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
                mapped_at_creation: false,
            });
            let mut ru = [0.0f32; 12];
            ru[0] = 1.0 / samples.max(1) as f32;
            queue.write_buffer(&p_inv, 0, bytemuck::bytes_of(&ru));
            let p_smp = device.create_sampler(&wgpu::SamplerDescriptor {
                label: Some("p-smp"),
                mag_filter: wgpu::FilterMode::Linear,
                min_filter: wgpu::FilterMode::Linear,
                ..Default::default()
            });
            let bg = make_present_bg(&device, &pbgl, &p_inv, &accum_view, &p_smp);
            (Some(pp), Some(bg))
        } else {
            (None, None)
        };

        // bytes_per_row alineado a 256 para la copia a buffer
        let bpp = 4u32;
        let unpadded = width * bpp;
        let align = wgpu::COPY_BYTES_PER_ROW_ALIGNMENT;
        let padded = ((unpadded + align - 1) / align) * align;
        let out_buf = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("readback"),
            size: (padded * height) as u64,
            usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
            mapped_at_creation: false,
        });

        let mut encoder =
            device.create_command_encoder(&wgpu::CommandEncoderDescriptor { label: None });
        {
            let mut rp = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("resolve-pass"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &out_view,
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Clear(wgpu::Color::BLACK),
                        store: wgpu::StoreOp::Store,
                    },
                })],
                depth_stencil_attachment: None,
                timestamp_writes: None,
                occlusion_query_set: None,
            });
            if let (Some(pp), Some(pbg)) = (&present_pipeline, &present_bg) {
                rp.set_pipeline(pp);
                rp.set_bind_group(0, pbg, &[]);
            } else {
                rp.set_pipeline(&resolve_pipeline);
                rp.set_bind_group(0, &resolve_bg, &[]);
            }
            rp.draw(0..3, 0..1);
        }
        encoder.copy_texture_to_buffer(
            wgpu::ImageCopyTexture {
                texture: &out_tex,
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
            },
            wgpu::ImageCopyBuffer {
                buffer: &out_buf,
                layout: wgpu::ImageDataLayout {
                    offset: 0,
                    bytes_per_row: Some(padded),
                    rows_per_image: Some(height),
                },
            },
            wgpu::Extent3d { width, height, depth_or_array_layers: 1 },
        );
        queue.submit(Some(encoder.finish()));

        let slice = out_buf.slice(..);
        let (tx, rx) = std::sync::mpsc::channel();
        slice.map_async(wgpu::MapMode::Read, move |r| tx.send(r).unwrap());
        device.poll(wgpu::Maintain::Wait);
        rx.recv().unwrap().unwrap();

        let data = slice.get_mapped_range();
        let mut pixels = Vec::with_capacity((unpadded * height) as usize);
        for row in 0..height {
            let start = (row * padded) as usize;
            pixels.extend_from_slice(&data[start..start + unpadded as usize]);
        }
        drop(data);
        out_buf.unmap();

        // Test headless del gizmo: dibuja (en CPU) la proyección de cada objeto
        // sobre la imagen. Si las cruces caen sobre los cuerpos, la proyección
        // (la misma que usa el viewport) es correcta. Cámara fija del snapshot.
        if std::env::var("RTG_GIZMO_TEST").is_ok() {
            let cam = [0.0f32, 1.2, 5.0];
            let fwd = [0.0f32, -0.19867, -0.98007];
            let (w, h) = (width as i32, height as i32);
            let pr = |p: [f32; 3]| project_point(cam, fwd, width as f32, height as f32, p);
            for o in &objects {
                if let Some((c, depth)) = pr(o.pos) {
                    let len = (0.13 * depth).clamp(0.35, 1.0e3);
                    if let Some((t, _)) = pr([o.pos[0] + len, o.pos[1], o.pos[2]]) {
                        draw_line(&mut pixels, w, h, c, t, [240, 60, 60]);
                    }
                    if let Some((t, _)) = pr([o.pos[0], o.pos[1] + len, o.pos[2]]) {
                        draw_line(&mut pixels, w, h, c, t, [60, 240, 90]);
                    }
                    if let Some((t, _)) = pr([o.pos[0], o.pos[1], o.pos[2] + len]) {
                        draw_line(&mut pixels, w, h, c, t, [80, 120, 250]);
                    }
                    for dx in -2..=2 {
                        for dy in -2..=2 {
                            put_px(&mut pixels, w, h, c[0] as i32 + dx, c[1] as i32 + dy, [255, 230, 80]);
                        }
                    }
                }
            }
        }

        let img = image::RgbaImage::from_raw(width, height, pixels)
            .expect("buffer de imagen inválido");
        img.save(path).expect("no se pudo guardar el PNG");
        println!("Snapshot guardado: {path} (t={time}, {samples} muestras)");
    });
}

fn main() {
    env_logger::init();

    // Modo headless:  rtg-core --snapshot salida.png
    let args: Vec<String> = std::env::args().collect();
    if let Some(i) = args.iter().position(|a| a == "--snapshot") {
        let path = args.get(i + 1).map(|s| s.as_str()).unwrap_or("snapshot.png");
        let time: f32 = std::env::var("SNAP_TIME")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(0.55);
        // nº de muestras de amortización temporal:  --samples N
        let samples: u32 = args
            .iter()
            .position(|a| a == "--samples")
            .and_then(|j| args.get(j + 1))
            .and_then(|s| s.parse().ok())
            .unwrap_or(1)
            .max(1);
        run_snapshot(path, time, 1024, 768, samples);
        return;
    }

    let event_loop = EventLoop::new().unwrap();
    let window = Arc::new(
        WindowBuilder::new()
            .with_title("RTGEngine · RTGEngine  —  Clic dcho + ratón: mirar + WASD/EQ: volar · rueda: velocidad · clic central: pan · Espacio: refinar · Esc")
            .with_inner_size(winit::dpi::LogicalSize::new(1024.0, 768.0))
            .build(&event_loop)
            .unwrap(),
    );

    let mut state = pollster::block_on(State::new(window.clone()));

    event_loop
        .run(move |event, elwt| {
            elwt.set_control_flow(winit::event_loop::ControlFlow::Poll);
            match event {
                Event::WindowEvent { event, window_id } if window_id == state.window.id() => {
                    match event {
                        WindowEvent::CloseRequested
                        | WindowEvent::KeyboardInput {
                            event:
                                winit::event::KeyEvent {
                                    physical_key: PhysicalKey::Code(KeyCode::Escape),
                                    state: winit::event::ElementState::Pressed,
                                    ..
                                },
                            ..
                        } => elwt.exit(),
                        WindowEvent::KeyboardInput {
                            event:
                                winit::event::KeyEvent {
                                    physical_key: PhysicalKey::Code(KeyCode::Space),
                                    state: winit::event::ElementState::Pressed,
                                    ..
                                },
                            ..
                        } => state.toggle_pause(),
                        WindowEvent::KeyboardInput {
                            event:
                                winit::event::KeyEvent {
                                    physical_key: PhysicalKey::Code(code),
                                    state: key_state,
                                    ..
                                },
                            ..
                        } => state.set_key(
                            code,
                            key_state == winit::event::ElementState::Pressed,
                        ),
                        WindowEvent::MouseInput {
                            state: btn_state,
                            button,
                            ..
                        } => state.on_mouse_button(
                            button,
                            btn_state == winit::event::ElementState::Pressed,
                        ),
                        WindowEvent::MouseWheel { delta, .. } => {
                            let s = match delta {
                                winit::event::MouseScrollDelta::LineDelta(_, y) => y,
                                winit::event::MouseScrollDelta::PixelDelta(p) => {
                                    p.y as f32 / 120.0
                                }
                            };
                            state.on_wheel(s);
                        }
                        WindowEvent::CursorMoved { position, .. } => {
                            state.cursor_pos = [position.x as f32, position.y as f32];
                            if state.lmb && state.drag_mode != 0 {
                                state.update_drag();
                            }
                        }
                        WindowEvent::Resized(new) => state.resize(new),
                        WindowEvent::RedrawRequested => match state.render() {
                            Ok(()) => {}
                            Err(wgpu::SurfaceError::Lost | wgpu::SurfaceError::Outdated) => {
                                state.resize(state.size)
                            }
                            Err(wgpu::SurfaceError::OutOfMemory) => elwt.exit(),
                            Err(e) => log::warn!("surface: {e:?}"),
                        },
                        _ => {}
                    }
                }
                Event::DeviceEvent {
                    event: winit::event::DeviceEvent::MouseMotion { delta },
                    ..
                } => state.on_mouse_motion(delta.0, delta.1),
                Event::AboutToWait => state.window.request_redraw(),
                _ => {}
            }
        })
        .unwrap();
}
