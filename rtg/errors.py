# -*- coding: utf-8 -*-
"""Errores del idioma RTGEngine. Cada fase del compilador lanza el suyo."""


class RTGError(Exception):
    """Base de todos los errores del motor."""


class LexError(RTGError):
    """Error léxico: un carácter o token imposible en el texto fuente."""


class ParseError(RTGError):
    """Error sintáctico: la frase no respeta la gramática node."""


class ValidationError(RTGError):
    """Error semántico ('centinela'): raíz o forma inexistente, parámetro
    incoherente. Es el guardián que impide que entre un node inválido."""
