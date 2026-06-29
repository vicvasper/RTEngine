# -*- coding: utf-8 -*-
"""
Léxico semántico de RTGEngine: el inventario de RAÍCES (root) y de PATRONES
VERBALES (forma). Aquí vive el significado del idioma.

- Una RAÍZ trilateral elige una *familia generadora* (qué clase de campo es).
- Un BINYÁN conjuga esa raíz en un *comportamiento* (cómo se evalúa/actúa).

Los radicales se escriben transliterados en mayúscula. Dígrafos como la shin
se escriben 'SH'. (Más adelante se admitirá también escritura en letras.)
"""
from collections import namedtuple

# --- Familias generadoras (qué tipo de campo produce una raíz) -------------
FAM_LOCOMOTION = "locomotion"   # cuerpo que puede desplazarse
FAM_LUMINARY = "luminary"       # fuente de luz potencial
FAM_SOLID = "solid"             # masa rígida, colisionable
FAM_STRUCTURE = "structure"     # geometría construida (muros, cajas)
FAM_FLUID = "fluid"             # superficie/volumen ondulante
FAM_SCATTER = "scatter"         # semilla que se instancia/reparte
FAM_MESH = "mesh"               # malla importada (personaje FBX rasterizado)
FAM_ASSET = "asset"             # modelo importado horneado a campo (OBJ -> SDF)

Root = namedtuple("Root", ["id", "radicals", "translit", "gloss", "family"])

# Inventario inicial de raíces. El 'id' es estable: es el que va al bytecode.
_ROOT_LIST = [
    Root(1, ("H", "L", "K"), "walk", "ir / caminar", FAM_LOCOMOTION),
    Root(2, ("A", "W", "R"), "light", "luz", FAM_LUMINARY),
    Root(3, ("Q", "SH", "H"), "solid", "ser duro", FAM_SOLID),
    Root(4, ("B", "N", "H"), "build", "construir", FAM_STRUCTURE),
    Root(5, ("M", "Y", "M"), "water", "agua", FAM_FLUID),
    Root(6, ("Z", "R", "A"), "seed", "sembrar", FAM_SCATTER),
    Root(7, ("F", "B", "X"), "character", "personaje (malla)", FAM_MESH),
    Root(8, ("O", "B", "J"), "model", "modelo importado", FAM_ASSET),
]

ROOTS = {r.radicals: r for r in _ROOT_LIST}
ROOTS_BY_ID = {r.id: r for r in _ROOT_LIST}


def normalize_radical(rad: str) -> str:
    """Normaliza un radical a su forma canónica en mayúsculas ('Sh' -> 'SH')."""
    return rad.upper()


def lookup_root(radicals):
    key = tuple(normalize_radical(r) for r in radicals)
    return ROOTS.get(key)


# --- Forms (los siete patrones verbales = modificadores de conducta) -----
# Cada forma activa un conjunto de banderas de comportamiento.
STATIC, REACTIVE, INTENSE, BAKED, EMITTER, DRIVEN, SELFANIM = range(7)

FORMS = {
    "STATIC": STATIC,         # activo simple        -> base estática
    "REACTIVE": REACTIVE,     # pasivo/reflexivo     -> reacciona (deformable)
    "INTENSE": INTENSE,       # intensivo            -> repite / instancia
    "BAKED": BAKED,       # pasivo intensivo     -> resultado horneado (fijo)
    "EMITTER": EMITTER,     # causativo            -> causa en otros (emite)
    "DRIVEN": DRIVEN,     # causativo pasivo     -> es causado (esclavo)
    "SELFANIM": SELFANIM, # reflexivo intensivo  -> se acciona a sí mismo
}
FORMS_BY_ID = {v: k for k, v in FORMS.items()}

# Banderas de comportamiento (bits). Se derivan del forma y van al bytecode.
FLAG_EMITS = 1       # causa luz/fuerza/sonido en otros
FLAG_SELFANIM = 2    # se anima/desplaza por sí mismo
FLAG_RESPONDS = 4    # reacciona a campos/colisiones externas
FLAG_FROZEN = 8      # estado horneado, no se recalcula
FLAG_DRIVEN = 16     # su conducta la dicta otro node
FLAG_INTENSIVE = 32  # repetición / instanciado amplificado

FORM_FLAGS = {
    STATIC: 0,
    REACTIVE: FLAG_RESPONDS,
    INTENSE: FLAG_INTENSIVE,
    BAKED: FLAG_INTENSIVE | FLAG_FROZEN,
    EMITTER: FLAG_EMITS,
    DRIVEN: FLAG_DRIVEN,
    SELFANIM: FLAG_SELFANIM,
}


def lookup_form(name: str):
    return FORMS.get(name.upper())
