# -*- coding: utf-8 -*-
"""
Compilador de RTGEngine: AST -> Módulo de bytecode.

Cada node se compila a una 'palabra node' empaquetada (un entero de 32 bits)
más un bloque de parámetros. La palabra empaquetada es la representación
compacta que, en el motor nativo, viajaría a la GPU.

Disposición de bits de la palabra node (32 bits):

    [ 31 .. 20 ] root_id   (12 bits)  -> hasta 4096 raíces
    [ 19 .. 17 ] form    ( 3 bits)  -> los 7 patrones verbales
    [ 16 .. 12 ] flags     ( 5 bits)  -> banderas de comportamiento derivadas
    [ 11 ..  0 ] param_idx (12 bits)  -> índice al bloque de parámetros

Aquí actúa también el VALIDATOR (centinela semántico): rechaza raíces o forms
inexistentes antes de que nada llegue al evaluador.
"""
import hashlib
from collections import namedtuple

from .errors import ValidationError
from .lexicon import (
    lookup_root, lookup_form, FORM_FLAGS, FORMS_BY_ID, ROOTS_BY_ID,
)

# Posiciones de bits
_ROOT_SHIFT, _ROOT_MASK = 20, 0xFFF
_FORM_SHIFT, _FORM_MASK = 17, 0x7
_FLAGS_SHIFT, _FLAGS_MASK = 12, 0x1F
_PARAM_MASK = 0xFFF

CompiledNode = namedtuple(
    "CompiledNode",
    ["name", "word", "root", "form_id", "flags", "place", "params", "param_idx"],
)
Module = namedtuple("Module", ["nodes"])


def pack_word(root_id, form_id, flags, param_idx) -> int:
    if not (0 <= root_id <= _ROOT_MASK):
        raise ValueError("root_id fuera de rango (12 bits)")
    if not (0 <= form_id <= _FORM_MASK):
        raise ValueError("form_id fuera de rango (3 bits)")
    if not (0 <= param_idx <= _PARAM_MASK):
        raise ValueError("param_idx fuera de rango (12 bits)")
    return (
        ((root_id & _ROOT_MASK) << _ROOT_SHIFT)
        | ((form_id & _FORM_MASK) << _FORM_SHIFT)
        | ((flags & _FLAGS_MASK) << _FLAGS_SHIFT)
        | (param_idx & _PARAM_MASK)
    )


def unpack_word(word: int):
    return {
        "root_id": (word >> _ROOT_SHIFT) & _ROOT_MASK,
        "form_id": (word >> _FORM_SHIFT) & _FORM_MASK,
        "flags": (word >> _FLAGS_SHIFT) & _FLAGS_MASK,
        "param_idx": word & _PARAM_MASK,
    }


def _resolve_value(name_seed, key, value):
    """Resuelve un Value del AST a un número o enum concreto.
    'rand' se resuelve de forma DETERMINISTA a partir del nombre del node y la
    clave, para que reimportar produzca siempre lo mismo (Seal)."""
    if value.kind == "num":
        return value.data
    if value.kind == "enum":
        return value.data
    if value.kind == "rand":
        h = hashlib.sha256(f"{name_seed}:{key}".encode("utf-8")).digest()
        # primeros 4 bytes -> [0, 1)
        n = int.from_bytes(h[:4], "big") / 0xFFFFFFFF
        return n
    raise ValidationError(f"Tipo de valor desconocido '{value.kind}' en '{key}'")


def compile_program(program) -> Module:
    out = []
    for idx, d in enumerate(program.nodes):
        # VALIDATOR: validar raíz
        root = lookup_root(d.radicals)
        if root is None:
            raise ValidationError(
                f"Raíz desconocida {tuple(d.radicals)} en node '{d.name}' "
                f"(línea {d.line}). No existe en el léxico."
            )
        # VALIDATOR: validar forma
        form_id = lookup_form(d.form)
        if form_id is None:
            raise ValidationError(
                f"Forma desconocido '{d.form}' en node '{d.name}' "
                f"(línea {d.line}). Válidos: STATIC, REACTIVE, INTENSE, BAKED, EMITTER, "
                f"DRIVEN, SELFANIM."
            )

        flags = FORM_FLAGS[form_id]
        params = {k: _resolve_value(d.name, k, v) for k, v in d.params.items()}
        param_idx = idx  # en esta fase, el índice del node es su bloque
        word = pack_word(root.id, form_id, flags, param_idx)

        out.append(CompiledNode(
            name=d.name, word=word, root=root, form_id=form_id,
            flags=flags, place=d.place, params=params, param_idx=param_idx,
        ))
    return Module(out)


def disassemble(module: Module) -> str:
    """Vuelca el bytecode en forma legible (para depuración)."""
    lines = ["; --- RTGEngine bytecode ---"]
    for cd in module.nodes:
        u = unpack_word(cd.word)
        root = ROOTS_BY_ID[u["root_id"]]
        form = FORMS_BY_ID[u["form_id"]]
        flagnames = _flag_names(u["flags"])
        params = " ".join(f"{k}={v}" for k, v in cd.params.items())
        lines.append(
            f"0x{cd.word:08X}  {cd.name:<10} "
            f"{''.join(root.radicals):<5} {form:<8} "
            f"[{flagnames}]  {{{params}}}"
        )
    return "\n".join(lines)


def _flag_names(flags):
    from .lexicon import (
        FLAG_EMITS, FLAG_SELFANIM, FLAG_RESPONDS, FLAG_FROZEN, FLAG_DRIVEN,
        FLAG_INTENSIVE,
    )
    names = []
    for bit, label in [
        (FLAG_EMITS, "emits"), (FLAG_SELFANIM, "selfanim"),
        (FLAG_RESPONDS, "responds"), (FLAG_FROZEN, "frozen"),
        (FLAG_DRIVEN, "driven"), (FLAG_INTENSIVE, "intensive"),
    ]:
        if flags & bit:
            names.append(label)
    return ",".join(names) if names else "-"
