# -*- coding: utf-8 -*-
"""
Capa de autoría AMIGABLE de RTGEngine.

El interno (raíz + forma) es el motor interno. El usuario NO necesita saberlo:
escribe palabras legibles que aquí se traducen a la representación interna.
El resultado es exactamente el mismo AST/bytecode que el idioma .node, así que
todo el resto del motor (compilador, codegen, render) se reutiliza tal cual.

Sintaxis (.scene):

    thing player {
        is        walker      ; qué es           -> raíz interna
        behavior  paces       ; cómo se comporta -> forma interno
        at        0 0 0       ; posición
        size 0.5  speed 1.4  range 1.5
    }

    thing lamp1 {
        is lamp   behavior emits   at 2 3.5 2
        warmth 2700   brightness 820
    }
"""
from .lexer import tokenize, IDENT, NUMBER, LBRACE, RBRACE, EOF, KEYWORD
from .parser import Program, NodeDecl, Value
from .errors import ParseError, ValidationError

# --- Diccionarios de traducción: palabra de usuario -> interno --------------
# "qué es" -> raíz trilateral
BODY = {
    "walker": ("H", "L", "K"), "character": ("H", "L", "K"),
    "lamp": ("A", "W", "R"), "light": ("A", "W", "R"),
    "rock": ("Q", "SH", "H"), "stone": ("Q", "SH", "H"), "solid": ("Q", "SH", "H"),
    "wall": ("B", "N", "H"), "structure": ("B", "N", "H"), "block": ("B", "N", "H"),
    "water": ("M", "Y", "M"), "fluid": ("M", "Y", "M"), "sea": ("M", "Y", "M"),
    "seed": ("Z", "R", "A"), "scatter": ("Z", "R", "A"), "foliage": ("Z", "R", "A"),
    # tipos importados (no son campos: se rasterizan / cargan aparte)
    "character": ("F", "B", "X"), "figure": ("F", "B", "X"), "actor": ("F", "B", "X"),
    "model": ("O", "B", "J"), "prop": ("O", "B", "J"), "mesh": ("O", "B", "J"),
}

# "comportamiento" -> forma
BEHAVIOR = {
    "still": "STATIC", "static": "STATIC",
    "reacts": "REACTIVE", "soft": "REACTIVE", "deformable": "REACTIVE",
    "many": "INTENSE", "tiled": "INTENSE", "repeated": "INTENSE",
    "baked": "BAKED", "frozen": "BAKED",
    "emits": "EMITTER", "shines": "EMITTER", "glows": "EMITTER",
    "driven": "DRIVEN", "slaved": "DRIVEN",
    "paces": "SELFANIM", "walks": "SELFANIM", "animates": "SELFANIM", "moves": "SELFANIM",
}

# Alias de parámetros amigables -> nombre interno del params
PARAM_ALIAS = {
    "warmth": "kelvin",
    "brightness": "lumens",
    "reach": "radius",
    "pace": "speed",
    "stride": "range",
}


def _opts(d):
    return ", ".join(sorted(set(d)))


class FriendlyParser:
    def __init__(self, tokens):
        self.toks = tokens
        self.i = 0

    def peek(self):
        return self.toks[self.i]

    def next(self):
        t = self.toks[self.i]
        self.i += 1
        return t

    def expect(self, ttype, what):
        t = self.peek()
        if t.type != ttype:
            raise ParseError(
                f"se esperaba {what} pero vino '{t.value}' (línea {t.line})")
        return self.next()

    def expect_word(self, w):
        t = self.peek()
        if t.value != w:
            raise ParseError(
                f"se esperaba '{w}' pero vino '{t.value}' (línea {t.line})")
        return self.next()

    def parse(self):
        things = []
        while self.peek().type != EOF:
            things.append(self.parse_thing())
        return Program(things)

    def parse_thing(self):
        kw = self.expect_word("thing")
        name = self.expect(IDENT, "un nombre").value
        self.expect(LBRACE, "'{'")

        radicals = None
        form = None
        place = (0.0, 0.0, 0.0)
        params = {}

        while self.peek().type != RBRACE:
            t = self.peek()
            if t.type == EOF:
                raise ParseError(f"falta '}}' al cerrar '{name}'")
            if t.type not in (IDENT, KEYWORD):
                raise ParseError(
                    f"campo inesperado '{t.value}' en '{name}' (línea {t.line})")
            key = self.next().value

            if key == "is":
                w = self.expect(IDENT, "un tipo (walker, lamp, rock...)").value
                if w not in BODY:
                    raise ValidationError(
                        f"no sé qué es '{w}' (en '{name}'). Opciones: {_opts(BODY)}")
                radicals = BODY[w]
            elif key == "behavior":
                w = self.expect(IDENT, "un comportamiento").value
                if w not in BEHAVIOR:
                    raise ValidationError(
                        f"comportamiento '{w}' desconocido (en '{name}'). "
                        f"Opciones: {_opts(BEHAVIOR)}")
                form = BEHAVIOR[w]
            elif key == "at":
                place = tuple(
                    self.expect(NUMBER, "un número").value for _ in range(3))
            else:
                # parámetro libre:  clave valor
                pk = PARAM_ALIAS.get(key, key)
                v = self.peek()
                if v.type == NUMBER:
                    params[pk] = Value("num", self.next().value)
                elif v.type in (IDENT, KEYWORD):
                    nm = self.next().value
                    params[pk] = Value("rand", None) if nm == "rand" \
                        else Value("enum", nm)
                else:
                    raise ParseError(
                        f"valor inválido para '{key}' en '{name}' (línea {v.line})")

        self.expect(RBRACE, "'}'")
        if radicals is None:
            raise ParseError(f"'{name}' no dice qué es (falta 'is ...').")
        if form is None:
            raise ParseError(f"'{name}' no dice su comportamiento (falta 'behavior ...').")
        return NodeDecl(name, radicals, form, place, params, kw.line)


def parse_friendly(src: str) -> Program:
    return FriendlyParser(tokenize(src)).parse()


def build_friendly(src: str):
    """Compila una escena amigable y devuelve (módulo, behaviors)."""
    from .compiler import compile_program
    from .evaluator import resolve_module
    module = compile_program(parse_friendly(src))
    return module, resolve_module(module)
