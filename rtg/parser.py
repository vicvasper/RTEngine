# -*- coding: utf-8 -*-
"""
Parser del idioma RTGEngine: tokens -> AST.

Gramática (informal):

    program   := node*
    node     := 'node' IDENT '{' field* '}'
    field     := root | form | params
    root   := 'root' IDENT IDENT IDENT        ; exactamente 3 radicales
    form    := 'form' IDENT
    params     := 'params' '{' assign* '}'
    assign    := IDENT '=' value
    value     := NUMBER | IDENT                      ; IDENT 'rand' es especial
"""
from collections import namedtuple
from .lexer import tokenize, KEYWORD, IDENT, NUMBER, LBRACE, RBRACE, EQ, EOF
from .errors import ParseError

# Nodos del AST
Program = namedtuple("Program", ["nodes"])
NodeDecl = namedtuple(
    "NodeDecl", ["name", "radicals", "form", "place", "params", "line"]
)
# 'params' es un dict: nombre -> Value
Value = namedtuple("Value", ["kind", "data"])  # kind: 'num' | 'enum' | 'rand'


class Parser:
    def __init__(self, tokens):
        self.toks = tokens
        self.pos = 0

    # --- utilidades ---
    def peek(self):
        return self.toks[self.pos]

    def next(self):
        t = self.toks[self.pos]
        self.pos += 1
        return t

    def expect(self, ttype, what=None):
        t = self.peek()
        if t.type != ttype:
            exp = what or ttype
            raise ParseError(
                f"Se esperaba {exp} pero se encontró '{t.value}' "
                f"(línea {t.line}, col {t.col})"
            )
        return self.next()

    def expect_keyword(self, kw):
        t = self.peek()
        if t.type != KEYWORD or t.value != kw:
            raise ParseError(
                f"Se esperaba la palabra clave '{kw}' pero se encontró "
                f"'{t.value}' (línea {t.line})"
            )
        return self.next()

    # --- reglas ---
    def parse(self):
        nodes = []
        while self.peek().type != EOF:
            nodes.append(self.parse_node())
        return Program(nodes)

    def parse_node(self):
        kw = self.expect_keyword("node")
        name = self.expect(IDENT, "nombre de node").value
        self.expect(LBRACE, "'{'")

        radicals = None
        form = None
        place = (0.0, 0.0, 0.0)
        params = {}

        while self.peek().type != RBRACE:
            t = self.peek()
            if t.type != KEYWORD:
                raise ParseError(
                    f"Campo inesperado '{t.value}' dentro de node '{name}' "
                    f"(línea {t.line})"
                )
            if t.value == "root":
                radicals = self.parse_root(name)
            elif t.value == "form":
                form = self.parse_form()
            elif t.value == "place":
                place = self.parse_place(name)
            elif t.value == "params":
                params = self.parse_params(name)
            else:
                raise ParseError(
                    f"Campo '{t.value}' no válido en node '{name}' "
                    f"(línea {t.line})"
                )

        self.expect(RBRACE, "'}'")

        if radicals is None:
            raise ParseError(f"El node '{name}' no tiene 'root' (raíz).")
        if form is None:
            raise ParseError(f"El node '{name}' no tiene 'form' (conjugación).")

        return NodeDecl(name, radicals, form, place, params, kw.line)

    def parse_place(self, node_name):
        self.expect_keyword("place")
        coords = []
        for _ in range(3):
            t = self.peek()
            if t.type != NUMBER:
                raise ParseError(
                    f"'place' en '{node_name}' requiere 3 números (x y z); "
                    f"se encontró '{t.value}' (línea {t.line})"
                )
            coords.append(self.next().value)
        return tuple(coords)

    def parse_root(self, node_name):
        self.expect_keyword("root")
        radicals = []
        for _ in range(3):
            t = self.peek()
            if t.type != IDENT:
                raise ParseError(
                    f"La raíz de '{node_name}' debe tener exactamente 3 radicales; "
                    f"se encontró '{t.value}' (línea {t.line})"
                )
            radicals.append(self.next().value)
        # No se admite un cuarto radical
        if self.peek().type == IDENT:
            raise ParseError(
                f"La raíz de '{node_name}' tiene más de 3 radicales "
                f"(línea {self.peek().line})"
            )
        return tuple(radicals)

    def parse_form(self):
        self.expect_keyword("form")
        return self.expect(IDENT, "nombre de forma").value

    def parse_params(self, node_name):
        self.expect_keyword("params")
        self.expect(LBRACE, "'{'")
        params = {}
        while self.peek().type != RBRACE:
            key = self.expect(IDENT, "clave de parámetro").value
            self.expect(EQ, "'='")
            v = self.peek()
            if v.type == NUMBER:
                params[key] = Value("num", self.next().value)
            elif v.type == IDENT:
                name = self.next().value
                if name == "rand":
                    params[key] = Value("rand", None)
                else:
                    params[key] = Value("enum", name)
            else:
                raise ParseError(
                    f"Valor inválido para '{key}' en '{node_name}' "
                    f"(línea {v.line})"
                )
        self.expect(RBRACE, "'}'")
        return params


def parse(src: str) -> Program:
    return Parser(tokenize(src)).parse()
