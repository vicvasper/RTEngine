# -*- coding: utf-8 -*-
"""
RTGEngine — el idioma del motor RTGEngine.

Pipeline de la Fase 0 (sin GPU):

    fuente .node
        -> tokenize()      (lexer)
        -> parse()         (parser -> AST)
        -> compile_program (-> bytecode; el Validator valida)
        -> resolve_module  (-> Behaviors evaluables)

Ejemplo:

    from rtg import build
    module, behaviors = build(open("examples/start.node").read())
"""
from .lexer import tokenize, Token
from .parser import parse, Program, NodeDecl
from .compiler import (
    compile_program, disassemble, pack_word, unpack_word, Module, CompiledNode,
)
from .evaluator import resolve_module, resolve, Behavior
from .errors import RTGError, LexError, ParseError, ValidationError

__all__ = [
    "tokenize", "Token", "parse", "Program", "NodeDecl",
    "compile_program", "disassemble", "pack_word", "unpack_word",
    "Module", "CompiledNode", "resolve_module", "resolve", "Behavior",
    "RTGError", "LexError", "ParseError", "ValidationError", "build",
]


def build(src: str):
    """Compila texto node y devuelve (módulo de bytecode, lista de Behaviors)."""
    module = compile_program(parse(src))
    return module, resolve_module(module)
