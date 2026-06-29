# -*- coding: utf-8 -*-
"""
Evaluador de referencia de RTGEngine (CPU, sin GPU).

Su único propósito en la Fase 0 es DEMOSTRAR la tesis del motor: que
'raíz + forma' produce comportamiento real (geometría que se mueve, materia
que ilumina) sin datos adicionales. No busca rendimiento; el camino rápido
vivirá en la GPU en fases posteriores. Aquí mandan la corrección y la claridad.

Cada node compilado se resuelve a un Behavior con:
  - sdf(p, t): distancia firmada al objeto en el punto p y el instante t
  - is_light + datos de luz (si emite)
  - center(t): posición del cuerpo (útil para tests y depuración)
"""
import math
from collections import namedtuple

from .lexicon import (
    FAM_LOCOMOTION, FAM_LUMINARY, FAM_SOLID, FAM_STRUCTURE, FAM_FLUID,
    FAM_SCATTER, FAM_MESH, FAM_ASSET, FLAG_SELFANIM, FLAG_EMITS, FLAG_RESPONDS,
    FLAG_INTENSIVE,
)

Vec3 = namedtuple("Vec3", ["x", "y", "z"])
Light = namedtuple("Light", ["lumens", "kelvin", "radius"])


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _length(v):
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def _sdf_sphere(p, c, r):
    return _length(_sub(p, c)) - r


def _sdf_box(p, c, half):
    q = (abs(p[0] - c[0]) - half[0],
         abs(p[1] - c[1]) - half[1],
         abs(p[2] - c[2]) - half[2])
    outside = _length((max(q[0], 0.0), max(q[1], 0.0), max(q[2], 0.0)))
    inside = min(max(q[0], max(q[1], q[2])), 0.0)
    return outside + inside


class Behavior:
    """Conducta resuelta de un node: cómo se ve y qué hace en el tiempo."""

    def __init__(self, name, family, flags, place, params):
        self.name = name
        self.family = family
        self.flags = flags
        self.place = tuple(float(x) for x in place)  # posición base (x, y, z)
        self.params = params

        self.self_animated = bool(flags & FLAG_SELFANIM)
        self.responds = bool(flags & FLAG_RESPONDS)
        self.intensive = bool(flags & FLAG_INTENSIVE)
        self.emits = bool(flags & FLAG_EMITS)

        # Parámetros con valores por defecto sensatos por familia
        self.size = float(params.get("size", 0.5))
        self.speed = float(params.get("speed", 1.0))
        self.range = float(params.get("range", 1.5))  # amplitud del paso
        self.scale = float(params.get("scale", 1.0))   # escala (modelos importados)
        # ¿es un objeto importado (malla/asset) en vez de un campo SDF?
        self.imported = family in (FAM_MESH, FAM_ASSET)

        # Luz: solo es fuente real si la familia es luminaria Y el forma emite
        self.is_light = (family == FAM_LUMINARY and self.emits)
        if self.is_light:
            self.light = Light(
                lumens=float(params.get("lumens", 100.0)),
                kelvin=float(params.get("kelvin", 6500.0)),
                radius=float(params.get("radius", 1.0)),
            )
        else:
            self.light = None

    # --- dinámica ---
    def center(self, t):
        """Posición del cuerpo en el instante t. Solo se desplaza si está
        auto-animado (SelfAnim) y es locomoción: pasea (gait) alrededor de
        'place' con amplitud 'range' y cadencia 'speed'."""
        px, py, pz = self.place
        if self.family == FAM_LOCOMOTION and self.self_animated:
            return (px + self.range * math.sin(t * self.speed), py, pz)
        return self.place

    # --- geometría ---
    def sdf(self, p, t=0.0):
        fam = self.family
        if fam in (FAM_MESH, FAM_ASSET):
            return 1.0e9          # importados: se rasterizan/cargan aparte, no SDF
        if fam == FAM_LOCOMOTION:
            return _sdf_sphere(p, self.center(t), self.size)
        if fam == FAM_SOLID:
            return _sdf_sphere(p, self.place, self.size)
        if fam == FAM_LUMINARY:
            return _sdf_sphere(p, self.place, max(self.size * 0.3, 0.05))
        if fam == FAM_STRUCTURE:
            h = self.size
            return _sdf_box(p, self.place, (h, h, h))
        if fam == FAM_FLUID:
            # Plano en place.y con olas si está auto-animado
            wave = 0.0
            if self.self_animated:
                wave = 0.1 * math.sin(p[0] * 2.0 + t * self.speed)
            return p[1] - self.place[1] - wave
        if fam == FAM_SCATTER:
            return _sdf_sphere(p, self.place, 0.15)
        # Por defecto, esfera en place
        return _sdf_sphere(p, self.place, self.size)


def resolve(compiled_node) -> Behavior:
    """Convierte un CompiledNode en su Behavior evaluable."""
    cd = compiled_node
    return Behavior(cd.name, cd.root.family, cd.flags, cd.place, cd.params)


def resolve_module(module):
    return [resolve(cd) for cd in module.nodes]
