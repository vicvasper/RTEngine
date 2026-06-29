# RTGEngine · RTGEngine Engine

A graphics engine **designed from the ground up** around one core idea: *an object is a word* (internally **דָּבָר**, node = "word" = "thing"). Content is not made of pre-baked meshes and textures, but of **generators** (nodes) evaluated on demand. The complete architecture is documented in [`../docs/RTGEngine_Architecture_Manual_VolII.pdf`](../docs/RTGEngine_Architecture_Manual_VolII.pdf).

> The only limitation we accept is the hardware itself (the real GPU and the physics of light). Everything above the GPU API is entirely our own.

## Status

* **Phase 0 — *The Word*** (complete): the RTGEngine language compiler, written in Python (reference implementation). `source .node -> lexer -> parser -> compiler (bytecode + Validator) -> evaluator`.

* **Phase 1 — *The Light*** (complete): the native engine in Rust + wgpu (`rtg-core`), featuring a GPU field raymarcher.

* **Phase 2 — *The Sentence*** (complete): the `.node` file **drives** the scene. The code generator produces the WGSL, and the engine loads it at runtime.

* **Phase 3 — *The Dwelling* (Cache)** (v0): temporal amortization — accumulates N jittered samples in an HDR buffer and averages them. Image quality is distributed across multiple frames instead of being paid for in a single one.

  `cargo run --release -- --snapshot out.png --samples 64`

* **User layer** — users write `.scene` files using readable words (`thing`, `is walker`, `behavior paces`, `at`). Internally, these are translated into the engine's internal language; **users never need to know it**.

* **Core (internal):** trilateral root -> *family* (shape); shape (7 patterns) -> *behavior*; `place x y z` -> position. Every node compiles into a **32-bit word**. The **Validator** verifies the result.

### The easy way: RTGEngine Studio (editor + real-time viewport)

```bash
cd engine
python studio.py
```

Click **Open Live Viewport** (this launches the engine window), then **edit** your scene: changes are automatically applied to the viewport (hot reload, no render button required). Inside the viewport you can move in real time using **Unreal Editor-style navigation**:

```text
Right Mouse Button + Mouse = look around     (fly mode)
Right Mouse Button + WASD/EQ = fly
Mouse Wheel (while RMB held) = flight speed
Middle Mouse Button + Drag = pan
Mouse Wheel (without buttons) = zoom in/out (dolly)
Arrow Keys = look around (without mouse)
Space = refine image (Cache)   ·   Esc = exit
```

An information panel displays the internal translation into the engine's native representation.

### Manual workflow (command line)

```bash
cd engine

# 1) Edit examples/start.scene (human-readable language)
python forge.py examples/start.scene      # 2) Generate the scene WGSL

cd rtg-core && cargo run --release        # 3) Run it

# Inside the window:
# Space = pause/refine (Cache) · Esc = exit

# Without a window, generate a PNG using temporal amortization:
cargo run --release -- --snapshot out.png --samples 64   # SNAP_TIME=<t>
```

> `.scene` = user-facing layer (recommended) · `.node` = internal format.
> Both produce exactly the same scene.

### Running the tests

```bash
cd engine

python run.py examples/start.node         # CPU compiler demo
python -m unittest rtg.tests.test_engine  # 24 tests (lexer/parser/compiler/evaluator/codegen)
```

## Project Structure

```text
engine/
  studio.py        user-friendly graphical interface (RTGEngine Studio)

  rtg/             language
    friendly.py    user layer (.scene)
    lexer.py
    parser.py
    lexicon.py
    compiler.py
    evaluator.py
    codegen.py
    tests/

  examples/
    start.scene    (user)
    start.node     (internal core)

  forge.py         .scene/.node -> rtg-core/src/scene.generated.wgsl
  run.py

  rtg-core/        native core (Rust + wgpu)
    src/
    main.rs
    prelude.wgsl
    core.wgsl
    scene.generated.wgsl
```
