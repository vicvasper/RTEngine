// ============================================================================
//  RTGEngine · core.wgsl  —  ILUMINACIÓN DETERMINISTA SOBRE CAMPOS (sin ruido).
//
//  Idea propia: como la escena es un campo de distancia ANALÍTICO (no mallas),
//  conocemos la distancia a todo en todas partes. Eso permite calcular sombras
//  suaves y oclusión de forma DETERMINISTA (sin muestreo aleatorio => sin
//  ruido), limpio desde el primer frame y en tiempo real. Las mallas no pueden
//  hacerlo igual de barato. No deroga la física: la evalúa aprovechando la
//  estructura del campo.
//
//  Consume de la escena generada: scene_sdf, mat_color, LIGHT_POS/COL/INT/MAT/R.
// ============================================================================

struct VSOut {
    @builtin(position) pos : vec4<f32>,
    @location(0) uv : vec2<f32>,
};

const ASSET_MAT : f32 = 99.0;

// Escena completa = escena analítica (generada) UNIDA al modelo importado.
fn full_scene(p : vec3<f32>, t : f32) -> vec2<f32> {
    var s = scene_sdf(p, t);
    let ad = imported_sdf(p);
    if (ad < s.x) { s = vec2<f32>(ad, ASSET_MAT); }
    return s;
}

fn map(p : vec3<f32>, t : f32) -> f32 {
    return full_scene(p, t).x;
}

fn calc_normal(p : vec3<f32>, t : f32) -> vec3<f32> {
    let e = vec2<f32>(0.0030, 0.0);  // mayor = normales más suaves en los pliegues
    return normalize(vec3<f32>(
        map(p + e.xyy, t) - map(p - e.xyy, t),
        map(p + e.yxy, t) - map(p - e.yxy, t),
        map(p + e.yyx, t) - map(p - e.yyx, t),
    ));
}

// Marcha primaria.
fn march(o : vec3<f32>, d : vec3<f32>, t : f32) -> f32 {
    var tt = 0.02;
    for (var i = 0; i < 110; i = i + 1) {
        let h = map(o + d * tt, t);
        if (h < 0.0008) { return tt; }
        tt = tt + h;
        if (tt > 60.0) { break; }
    }
    return -1.0;
}

// Sombra suave ANALÍTICA del campo (Quilez): la penumbra sale del menor
// cociente distancia/longitud a lo largo del rayo. 'k' = dureza (mayor = más
// nítida); la derivamos del tamaño angular de la lámpara. SIN ruido.
fn sdf_soft_shadow(o : vec3<f32>, l : vec3<f32>, maxt : f32, w : f32, t : f32) -> f32 {
    // Versión mejorada de Quilez: usa la distancia al rayo (no h/t directo),
    // lo que elimina el banding en superficies grandes. 'w' = ancho de penumbra.
    var res = 1.0;
    var tt = 0.03;
    var ph = 1.0e20;
    for (var i = 0; i < 64; i = i + 1) {
        let h = map(o + l * tt, t);
        if (h < 0.0006) { return 0.0; }
        let y = h * h / (2.0 * ph);
        let d = sqrt(max(h * h - y * y, 0.0));
        res = min(res, d / (w * max(0.0, tt - y)));
        ph = h;
        tt = tt + h;
        if (tt > maxt) { break; }
    }
    return clamp(res, 0.0, 1.0);
}

// Oclusión ambiental ANALÍTICA por muestreo del campo a lo largo de la normal.
fn sdf_ao(p : vec3<f32>, n : vec3<f32>, t : f32) -> f32 {
    var occ = 0.0;
    var sca = 1.0;
    for (var i = 0; i < 5; i = i + 1) {
        let hd = 0.015 + 0.12 * f32(i);
        let d = map(p + n * hd, t);
        occ += (hd - d) * sca;
        sca *= 0.6;
    }
    return clamp(1.0 - 1.5 * occ, 0.0, 1.0);
}

fn is_light(mid : f32) -> bool {
    return abs(mid - LIGHT_MAT) < 0.5;
}

fn sky(d : vec3<f32>) -> vec3<f32> {
    let up = clamp(d.y * 0.5 + 0.5, 0.0, 1.0);
    return mix(vec3<f32>(0.05, 0.07, 0.11),
               vec3<f32>(0.20, 0.28, 0.45), up);
}

// Visibilidad dura (sombra) de un punto hacia una dirección, hasta maxt.
fn occluded(o : vec3<f32>, d : vec3<f32>, maxt : f32, t : f32) -> bool {
    var tt = 0.03;
    for (var i = 0; i < 30; i = i + 1) {
        let h = map(o + d * tt, t);
        if (h < 0.0008) { return true; }
        tt = tt + h;
        if (tt > maxt) { return false; }
    }
    return false;
}

const PI : f32 = 3.14159265;

// Función de fase Henyey-Greenstein: concentra la dispersión hacia delante
// (g>0) -> halo brillante alrededor de la luz = god rays / rayos crepusculares.
fn hg(c : f32, g : f32) -> f32 {
    let g2 = g * g;
    return (1.0 - g2) / (4.0 * PI * pow(max(1.0 + g2 - 2.0 * g * c, 1e-4), 1.5));
}

// Dither ordenado de Bayer 4x4: patrón regular y tenue (no ruido aleatorio),
// para repartir el muestreo del volumétrico sin grano.
fn bayer4(px : i32, py : i32) -> f32 {
    var m = array<f32, 16>(
         0.0,  8.0,  2.0, 10.0,
        12.0,  4.0, 14.0,  6.0,
         3.0, 11.0,  1.0,  9.0,
        15.0,  7.0, 13.0,  5.0);
    let idx = (py & 3) * 4 + (px & 3);
    return m[idx] / 16.0;
}

// God rays: marcha el rayo de cámara por el aire y acumula la luz dispersada,
// con test de sombra en cada paso (los objetos abren los haces y las sombras
// volumétricas). Determinista (con dither para no bandear). Devuelve la luz
// in-dispersada a sumar al color de superficie.
fn volumetric(ro : vec3<f32>, rd : vec3<f32>, maxd : f32, dither : f32, t : f32) -> vec3<f32> {
    let nsteps = 48;
    let stepd = maxd / f32(nsteps);
    var scatter = vec3<f32>(0.0);
    var pos = ro + rd * (stepd * dither);
    for (var i = 0; i < nsteps; i = i + 1) {
        let tol = light_pos() - pos;
        let ld = length(tol);
        let ldir = tol / ld;
        var vis = 1.0;
        if (occluded(pos, ldir, ld - LIGHT_R, t)) { vis = 0.0; }  // sombra volumétrica real
        let lc = LIGHT_COL * LIGHT_INT / (1.0 + ld * ld * 0.04);
        let phase = hg(dot(rd, ldir), 0.55);   // dispersión hacia delante (haces)
        scatter += lc * vis * phase * stepd;
        pos += rd * stepd;
    }
    return scatter;
}

// Distribución de normales GGX (Trowbridge-Reitz).
fn ggx_d(ndh : f32, a : f32) -> f32 {
    let a2 = a * a;
    let d = ndh * ndh * (a2 - 1.0) + 1.0;
    return a2 / max(PI * d * d, 1e-7);
}
// Geometría Smith (Schlick-GGX) para luz directa.
fn smith_g(ndv : f32, ndl : f32, rough : f32) -> f32 {
    let k = (rough + 1.0) * (rough + 1.0) / 8.0;
    let gv = ndv / (ndv * (1.0 - k) + k);
    let gl = ndl / (ndl * (1.0 - k) + k);
    return gv * gl;
}

// Sombreado PBR (Cook-Torrance GGX) determinista. Limpio (sin muestreo).
fn shade(p : vec3<f32>, n : vec3<f32>, v : vec3<f32>, mid : f32, t : f32) -> vec3<f32> {
    var albedo = mat_color(mid);
    if (abs(mid - ASSET_MAT) < 0.5) { albedo = vec3<f32>(0.72, 0.72, 0.75); } // modelo importado
    let rough = clamp(mat_rough(mid), 0.045, 1.0);
    let metal = clamp(mat_metal(mid), 0.0, 1.0);
    let a = rough * rough;

    // --- Directa: lámpara como área esférica, con sombra suave analítica ---
    let lvec = light_pos() - p;
    let dist = length(lvec);
    let l = lvec / dist;
    let ndl = clamp(dot(n, l), 0.0, 1.0);
    let ndv = clamp(dot(n, v), 1e-4, 1.0);
    let w = clamp(LIGHT_R * 3.0 / max(dist, 0.1), 0.04, 0.35);
    var sh = 1.0;
    if (ndl > 0.0) {
        sh = sdf_soft_shadow(p + n * 0.004, l, dist - LIGHT_R, w, t);
    }
    let radiance = LIGHT_COL * (LIGHT_INT * 6.0) / (1.0 + dist * 0.2);

    // Cook-Torrance: F (Schlick) · D (GGX) · G (Smith)
    let h = normalize(l + v);
    let ndh = clamp(dot(n, h), 0.0, 1.0);
    let vdh = clamp(dot(v, h), 0.0, 1.0);
    let f0 = mix(vec3<f32>(0.04), albedo, metal);
    let fres = f0 + (vec3<f32>(1.0) - f0) * pow(1.0 - vdh, 5.0);
    let dterm = ggx_d(ndh, a);
    let gterm = smith_g(ndv, ndl, rough);
    // término especular acotado (sin random => sin fireflies, pero limitamos el pico)
    let spec = fres * min(dterm * gterm / (4.0 * ndv * ndl + 1e-4), 12.0);
    let kd = (vec3<f32>(1.0) - fres) * (1.0 - metal);    // energía a la difusa
    let diffuse = kd * albedo;                            // Lambert (sin /PI: realtime)
    let direct = (diffuse + spec) * radiance * ndl * sh;

    // --- Ambiente PBR (relleno) con AO ---
    let ao = sdf_ao(p, n, t);
    let upf = clamp(n.y * 0.5 + 0.5, 0.0, 1.0);
    let amb_sky = vec3<f32>(0.05, 0.06, 0.09);
    let ground_bounce = vec3<f32>(0.10, 0.07, 0.05);
    let amb_col = amb_sky * upf + ground_bounce * (1.0 - upf);
    let ambient = albedo * amb_col * ao * (1.0 - metal * 0.6);

    return direct + ambient;
}

@vertex
fn vs_main(@builtin(vertex_index) vid : u32) -> VSOut {
    var p = array<vec2<f32>, 3>(
        vec2<f32>(-1.0, -1.0),
        vec2<f32>( 3.0, -1.0),
        vec2<f32>(-1.0,  3.0),
    );
    var out : VSOut;
    out.pos = vec4<f32>(p[vid], 0.0, 1.0);
    out.uv = p[vid];
    return out;
}

struct FSOut {
    @location(0) color : vec4<f32>,
    @builtin(frag_depth) depth : f32,   // para componer con la malla rasterizada
};

@fragment
fn fs_main(in : VSOut) -> FSOut {
    let t = U.time;
    let aspect = U.resolution.x / max(U.resolution.y, 1.0);
    let uv = vec2<f32>((in.uv.x + U.jitter.x) * aspect, in.uv.y + U.jitter.y);

    let ro = U.cam_pos.xyz;
    let fwd = normalize(U.cam_fwd.xyz);
    let right = normalize(cross(fwd, vec3<f32>(0.0, 1.0, 0.0)));
    let up = cross(right, fwd);
    let rd = normalize(uv.x * right + uv.y * up + 1.5 * fwd);

    let th = march(ro, rd, t);
    var col : vec3<f32>;
    if (th < 0.0) {
        col = sky(rd);                                  // el cielo
    } else {
        let p = ro + rd * th;
        let mid = full_scene(p, t).y;
        if (is_light(mid)) {
            col = LIGHT_COL * LIGHT_INT;                // la lámpara brilla
        } else {
            let n = calc_normal(p, t);
            col = shade(p, n, -rd, mid, t);             // sombreado determinista

            // --- Reflejos (Fase 5): un rebote especular, determinista (limpio).
            //     El suelo es bastante reflectante; el resto, reflejo de borde
            //     (Fresnel). Reflectividad por material via mat_reflect().
            var reflectivity = mat_reflect(mid);
            if (mid < 0.5) { reflectivity = 0.4; }       // suelo reflectante
            if (abs(mid - ASSET_MAT) < 0.5) { reflectivity = 0.15; }
            let ndv = clamp(dot(n, -rd), 0.0, 1.0);
            let fres = reflectivity + (1.0 - reflectivity) * pow(1.0 - ndv, 5.0);
            if (fres > 0.02) {
                let rdir = reflect(rd, n);
                let rt = march(p + n * 0.012, rdir, t);
                var rc = sky(rdir);
                if (rt > 0.0) {
                    let rp = p + n * 0.012 + rdir * rt;
                    let rmid = full_scene(rp, t).y;
                    if (is_light(rmid)) {
                        rc = LIGHT_COL * LIGHT_INT;
                    } else {
                        rc = shade(rp, calc_normal(rp, t), -rdir, rmid, t);
                    }
                }
                col = mix(col, rc, fres);
            }
        }
    }

    // God rays (Fase 5): luz volumétrica MARCHADA con SOMBRA REAL en cada paso.
    // Los objetos abren huecos oscuros en los haces (sombras volumétricas de
    // verdad). Bayer ordenado (no ruido) para repartir el muestreo; la
    // acumulación temporal lo afina cuando la vista se queda quieta.
    let dith = bayer4(i32(in.pos.x), i32(in.pos.y));
    let to_light = light_pos() - ro;
    let ldist = length(to_light);
    var maxd = ldist;
    if (th > 0.0) { maxd = min(th, ldist); }    // marcha hasta la superficie o la luz
    maxd = min(maxd, 26.0);
    col += volumetric(ro, rd, maxd, dith, t) * 0.05;
    // Núcleo del sol: bloom analítico limpio (sin marchar), solo el disco.
    let ldir = to_light / ldist;
    let a = clamp(dot(rd, ldir), 0.0, 1.0);
    col += LIGHT_COL * (LIGHT_INT * 0.02) * pow(a, 140.0);

    // Profundidad para la malla (mismo mapeo que mat_proj: near 0.05, far 120).
    var depth = 1.0;
    if (th > 0.0) {
        let zc = th * max(dot(rd, fwd), 1e-4);   // distancia hacia delante (cámara)
        depth = clamp(120.0 / (120.0 - 0.05) - (120.0 * 0.05 / (120.0 - 0.05)) / zc,
                      0.0, 1.0);
    }

    // Salida en LINEAL; el tonemapping ACES se hace al presentar.
    var o : FSOut;
    o.color = vec4<f32>(col, 1.0);
    o.depth = depth;
    return o;
}
