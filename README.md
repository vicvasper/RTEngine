# RTGEngine · motor RTGEngine

Motor gráfico **diseñado desde cero** alrededor de una idea: *un objeto es una
palabra* (interno **דָּבָר**, node = "palabra" = "cosa"). El contenido no son
mallas+texturas horneadas, sino **generadores** (nodes) que se evalúan bajo
demanda. La arquitectura completa está en
[`../docs/RTGEngine_Manual_Arquitectura_VolII.pdf`](../docs/RTGEngine_Manual_Arquitectura_VolII.pdf).

> El único límite que aceptamos es el hardware (la GPU real y la física de la
> luz). De la API de GPU para arriba, todo es propio.

## Estado

- **Fase 0 — *El Verbo*** (completa): el compilador del idioma RTGEngine, en Python
  (referencia). `fuente .node -> lexer -> parser -> compilador (bytecode +
  Validator) -> evaluador`.
- **Fase 1 — *La Luz*** (completa): el motor nativo en Rust + wgpu
  (`rtg-core`), raymarcher de campos en GPU.
- **Fase 2 — *La Frase*** (completa): el `.node` **conduce** la escena. El
  codegen genera el WGSL; el motor lo carga en runtime.
- **Fase 3 — *La Morada* (Cache)** (v0): amortización temporal — acumula N
  muestras con jitter en un buffer HDR y las promedia. La calidad se reparte
  entre frames en vez de pagarla en uno.
  `cargo run --release -- --snapshot out.png --samples 64`

- **Capa de usuario** — el usuario escribe `.scene` con palabras
  legibles (`thing`, `is walker`, `behavior paces`, `at`). El interno es el
  motor interno; **no hace falta saberlo**.
- **Núcleo (interno):** raíz (root) trilateral -> *familia* (forma); forma
  (7 patrones) -> *comportamiento*; `place x y z` -> posición. Cada node
  compila a una **palabra de 32 bits**. El **Validator** valida.

### La forma fácil: RTGEngine Studio (editor + viewport en tiempo real)

```bash
cd engine
python studio.py
```
Pulsa **Abrir viewport en vivo** (abre la ventana del motor) y **edita**: los
cambios se aplican solos al viewport (hot-reload, sin botón de render). Dentro
del viewport te mueves en tiempo real, **con la navegación del editor de Unreal**:

```
Clic DERECHO + ratón     = mirar          (modo vuelo)
Clic DERECHO + WASD/EQ   = volar
Rueda (con clic dcho)    = velocidad de vuelo
Clic CENTRAL + arrastrar = pan
Rueda (sin clic)         = acercar / alejar (dolly)
Flechas                  = mirar (sin ratón)
Espacio = afinar imagen (Cache)   ·   Esc = salir
```
Un panel muestra, solo informativo, la traducción interna al interno.

### A mano (línea de comandos)

```bash
cd engine
# 1) edita examples/start.scene  (palabras legibles,)
python forge.py examples/start.scene            # 2) forja el WGSL de la escena
cd rtg-core && cargo run --release         # 3) míralo
#   En la ventana:  Espacio = pausar/refinar (Cache) · Esc = salir
# sin ventana, un PNG con amortización temporal:
cargo run --release -- --snapshot out.png --samples 64   # SNAP_TIME=<t>
```

> `.scene` = capa de usuario (recomendado) · `.node` = formato interno.
> Ambos producen exactamente la misma escena.

### Probar

```bash
cd engine
python run.py examples/start.node           # demo del compilador en CPU
python -m unittest rtg.tests.test_engine    # 24 pruebas (lexer/parser/compilador/eval/codegen)
```

## Estructura

```
engine/
  studio.py        interfaz gráfica amigable (RTGEngine Studio)
  rtg/           idioma
    friendly.py    capa de usuario (.scene,)
    lexer.py  parser.py  lexicon.py  compiler.py  evaluator.py  codegen.py
    tests/
  examples/start.scene    (usuario)   ·   start.node (núcleo interno)
  forge.py         .scene/.node -> rtg-core/src/scene.generated.wgsl
  run.py
  rtg-core/    núcleo nativo (Rust + wgpu)
    src/  main.rs  prelude.wgsl  core.wgsl  scene.generated.wgsl
```

## Siguiente

1. ~~Capa de autoría sencilla~~ ✅ (`.scene` + `rtg/friendly.py`).
2. ~~Cache en vivo (refinado progresivo en la ventana)~~ ✅ (Espacio).
3. ~~Interfaz gráfica amigable~~ ✅ (`studio.py`).
4. **Fase 4 — *La Puerta*** (EN MARCHA): importar assets a campos.
   - Parte 1 ✅: `rtg/incarnate.py` — OBJ → validar → normalizar → hornear a
     SDF firmado (`python -m rtg.incarnate modelo.obj`). Da `.sdf` + `.json`.
   - Parte 2 (pendiente): que el motor cargue el `.sdf` (textura 3D) y lo dibuje.
5. **Fase 5 — *El Firmamento***: render avanzado (god rays con sombras, reflejos, PBR).
6. **Fase 6 — *El Aliento***: física, audio y herramientas.
