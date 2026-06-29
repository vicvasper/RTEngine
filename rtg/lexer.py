# -*- coding: utf-8 -*-
"""
Lexer del idioma RTGEngine.

Convierte texto fuente (.node) en una lista de tokens. La gramática es
deliberadamente mínima: palabras clave, identificadores (radicales, forms,
claves y enums), números, y los símbolos { } =. Los comentarios empiezan por ';'.
"""
from collections import namedtuple
from .errors import LexError

Token = namedtuple("Token", ["type", "value", "line", "col"])

KEYWORDS = {"node", "root", "form", "params", "place", "rel"}

# Tipos de token
LBRACE, RBRACE, EQ = "LBRACE", "RBRACE", "EQ"
IDENT, NUMBER, KEYWORD, EOF = "IDENT", "NUMBER", "KEYWORD", "EOF"

_SYMBOLS = {"{": LBRACE, "}": RBRACE, "=": EQ}


def tokenize(src: str):
    tokens = []
    line, col, i, n = 1, 1, 0, len(src)

    def advance(k=1):
        nonlocal i, col
        i += k
        col += k

    while i < n:
        c = src[i]

        # Saltos de línea y espacios
        if c == "\n":
            line += 1
            col = 1
            i += 1
            continue
        if c in " \t\r":
            advance()
            continue

        # Comentarios: ';' hasta fin de línea
        if c == ";":
            while i < n and src[i] != "\n":
                i += 1
            continue

        # Símbolos
        if c in _SYMBOLS:
            tokens.append(Token(_SYMBOLS[c], c, line, col))
            advance()
            continue

        # Números (con signo y decimales opcionales)
        if c.isdigit() or (c == "-" and i + 1 < n and src[i + 1].isdigit()):
            start_col = col
            j = i + 1
            while j < n and (src[j].isdigit() or src[j] == "."):
                j += 1
            raw = src[i:j]
            if raw.count(".") > 1:
                raise LexError(f"Número mal formado '{raw}' en línea {line}")
            tokens.append(Token(NUMBER, float(raw), line, start_col))
            advance(j - i)
            continue

        # Identificadores y palabras clave
        if c.isalpha() or c == "_":
            start_col = col
            j = i + 1
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            word = src[i:j]
            ttype = KEYWORD if word in KEYWORDS else IDENT
            tokens.append(Token(ttype, word, line, start_col))
            advance(j - i)
            continue

        raise LexError(f"Carácter inesperado '{c}' en línea {line}, col {col}")

    tokens.append(Token(EOF, None, line, col))
    return tokens
