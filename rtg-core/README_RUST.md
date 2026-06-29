# Puesta a punto del núcleo nativo (Rust + wgpu)

La Fase 1 (`rtg-core`) abre una ventana y renderiza una escena de campos de
distancia con un raymarcher en GPU. Para compilarla hace falta la toolchain de
Rust **y un linker de C/C++** (Windows no trae uno por defecto).

## 1. Rust

```powershell
winget install --id Rustlang.Rustup --silent --accept-package-agreements --accept-source-agreements
```

Tras instalar, abre una terminal nueva para que `cargo` esté en el PATH.

## 2. Un linker (elige UNA opción)

Rust en Windows necesita un linker. Dos caminos:

### Opción A — MSVC (recomendada, lo que usan los motores AAA)
Instala las *Build Tools* de Visual Studio con el componente de C++ (~2-4 GB,
**requiere permisos de administrador**):

```powershell
winget install --id Microsoft.VisualStudio.2022.BuildTools --override "--quiet --wait --add Microsoft.VisualStudio.Workload.VCTools --add Microsoft.VisualStudio.Component.Windows11SDK.22621"
```

Con esto, el target por defecto `x86_64-pc-windows-msvc` ya enlaza.

### Opción B — GNU (más ligera, sin Visual Studio)
Instala un MinGW-w64 y usa el target GNU (~200-400 MB):

```powershell
winget install --id BrechtSanders.WinLibs.POSIX.UCRT
rustup default stable-x86_64-pc-windows-gnu
```

(El `gcc`/`ld` de WinLibs debe quedar en el PATH.)

## 3. Compilar y ejecutar

```powershell
cd engine/rtg-core
cargo run --release
```

Deberías ver una ventana con: una esfera verde que oscila sola (**adam**,
SelfAnim), una esfera gris estática (**even**, Static) y luz cálida (**candil**,
Emitter). Esc para salir. El zoom es analítico: no hay LODs ni polígonos.

> El código está escrito para `winit 0.29` + `wgpu 0.20`. Si en el primer build
> aparecen desajustes de API, se corrigen en `Cargo.toml` / `src/`.
