# -*- coding: utf-8 -*-
"""
Pruebas de la Fase 0 del idioma RTGEngine. Cubren las cuatro etapas:
lexer, parser, compilador (Validator + empaquetado) y evaluador (conducta).

Ejecutar:  python -m unittest discover -s engine/rtg/tests
"""
import math
import os
import sys
import unittest

# Permitir importar el paquete 'rtg' al correr desde cualquier sitio
ENGINE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ENGINE_DIR)

from rtg import build, parse, tokenize, disassemble  # noqa: E402
from rtg import pack_word, unpack_word  # noqa: E402
from rtg.errors import ParseError, ValidationError  # noqa: E402
from rtg.lexer import NUMBER, IDENT, KEYWORD  # noqa: E402

WALKER = """
node adam {
    root H L K
    form  SELFANIM
    params   { size=0.5 speed=1.4 gait=biped phase=rand }
}
"""

LIGHT = """
node candil {
    root A W R
    form  EMITTER
    params   { lumens=820 kelvin=2700 radius=6.0 }
}
"""

ROCK = """
node even {
    root Q Sh H
    form  STATIC
    params   { size=0.8 }
}
"""


class TestLexer(unittest.TestCase):
    def test_tokenizes_core(self):
        toks = tokenize("node x { root H L K }")
        types = [t.type for t in toks if t.type != "EOF"]
        self.assertEqual(types[0], KEYWORD)        # node
        self.assertEqual(types[1], IDENT)          # x
        self.assertIn(NUMBER, [t.type for t in tokenize("params { a=1.5 }")])

    def test_comments_skipped(self):
        toks = tokenize("node x { } ; esto es un comentario")
        self.assertEqual(toks[-1].type, "EOF")
        self.assertTrue(all(t.value != "esto" for t in toks))


class TestParser(unittest.TestCase):
    def test_parses_fields(self):
        prog = parse(WALKER)
        d = prog.nodes[0]
        self.assertEqual(d.name, "adam")
        self.assertEqual(d.radicals, ("H", "L", "K"))
        self.assertEqual(d.form, "SELFANIM")
        self.assertEqual(d.place, (0.0, 0.0, 0.0))  # por defecto, el origen
        self.assertEqual(d.params["speed"].data, 1.4)
        self.assertEqual(d.params["gait"].kind, "enum")
        self.assertEqual(d.params["phase"].kind, "rand")

    def test_place_parsed(self):
        d = parse("node x { root Q Sh H\n form STATIC\n place 1.0 -2.5 3.0 }").nodes[0]
        self.assertEqual(d.place, (1.0, -2.5, 3.0))

    def test_place_requires_three_numbers(self):
        with self.assertRaises(ParseError):
            parse("node x { root Q Sh H\n form STATIC\n place 1.0 2.0 }")

    def test_root_must_have_three_radicals(self):
        with self.assertRaises(ParseError):
            parse("node x { root H L\n form STATIC }")

    def test_root_rejects_four(self):
        with self.assertRaises(ParseError):
            parse("node x { root H L K M\n form STATIC }")

    def test_missing_form_rejected(self):
        with self.assertRaises(ParseError):
            parse("node x { root H L K }")


class TestCompilerValidator(unittest.TestCase):
    def test_unknown_root_rejected(self):
        with self.assertRaises(ValidationError):
            build("node x { root X Y Z\n form STATIC }")

    def test_unknown_form_rejected(self):
        with self.assertRaises(ValidationError):
            build("node x { root H L K\n form FOOBAR }")

    def test_flags_emits_for_hifil(self):
        from rtg.lexicon import FLAG_EMITS, FLAG_SELFANIM
        mod, _ = build(LIGHT)
        self.assertTrue(mod.nodes[0].flags & FLAG_EMITS)
        self.assertFalse(mod.nodes[0].flags & FLAG_SELFANIM)

    def test_flags_selfanim_for_hitpael(self):
        from rtg.lexicon import FLAG_SELFANIM
        mod, _ = build(WALKER)
        self.assertTrue(mod.nodes[0].flags & FLAG_SELFANIM)

    def test_rand_is_deterministic(self):
        m1, _ = build(WALKER)
        m2, _ = build(WALKER)
        self.assertEqual(m1.nodes[0].params["phase"],
                         m2.nodes[0].params["phase"])

    def test_disassemble_runs(self):
        mod, _ = build(WALKER + LIGHT + ROCK)
        text = disassemble(mod)
        self.assertIn("adam", text)
        self.assertIn("candil", text)


class TestBytecodeWord(unittest.TestCase):
    def test_pack_unpack_roundtrip(self):
        cases = [(1, 6, 2, 0), (4095, 7, 31, 4095), (2, 4, 1, 17)]
        for root_id, form, flags, pidx in cases:
            w = pack_word(root_id, form, flags, pidx)
            u = unpack_word(w)
            self.assertEqual(u["root_id"], root_id)
            self.assertEqual(u["form_id"], form)
            self.assertEqual(u["flags"], flags)
            self.assertEqual(u["param_idx"], pidx)

    def test_word_is_32bit(self):
        w = pack_word(4095, 7, 31, 4095)
        self.assertLessEqual(w, 0xFFFFFFFF)


class TestEvaluator(unittest.TestCase):
    def test_hitpael_moves(self):
        _, behaviors = build(WALKER)
        b = behaviors[0]
        # en t=0 está en su 'place' (aquí, el origen)
        self.assertAlmostEqual(b.center(0.0)[0], 0.0, places=6)
        # pasea: x = place.x + range*sin(t*speed); range=1.5 por defecto, speed=1.4
        self.assertAlmostEqual(b.center(2.0)[0], 1.5 * math.sin(1.4 * 2.0), places=6)
        self.assertNotEqual(b.center(0.0)[0], b.center(2.0)[0])

    def test_qal_is_static(self):
        _, behaviors = build(ROCK)
        b = behaviors[0]
        self.assertAlmostEqual(b.sdf((1.0, 0.0, 0.0), 0.0),
                               b.sdf((1.0, 0.0, 0.0), 5.0), places=9)

    def test_hifil_luminary_emits(self):
        _, behaviors = build(LIGHT)
        b = behaviors[0]
        self.assertTrue(b.is_light)
        self.assertEqual(b.light.lumens, 820.0)
        self.assertEqual(b.light.kelvin, 2700.0)

    def test_qal_luminary_does_not_emit(self):
        # misma raíz de luz, pero en STATIC no causa luz en otros
        _, behaviors = build("node x { root A W R\n form STATIC\n params { lumens=500 } }")
        self.assertFalse(behaviors[0].is_light)

    def test_sdf_sign(self):
        # dentro de la piedra (size=0.8) el sdf es negativo; fuera positivo
        _, behaviors = build(ROCK)
        b = behaviors[0]
        self.assertLess(b.sdf((0.0, 0.0, 0.0), 0.0), 0.0)
        self.assertGreater(b.sdf((5.0, 0.0, 0.0), 0.0), 0.0)

    def test_solid_uses_place(self):
        # una piedra situada en 'place' tiene su centro ahí
        _, behaviors = build(
            "node x { root Q Sh H\n form STATIC\n place 3.0 0.0 0.0\n params { size=0.5 } }")
        b = behaviors[0]
        self.assertEqual(b.center(0.0), (3.0, 0.0, 0.0))
        self.assertLess(b.sdf((3.0, 0.0, 0.0), 0.0), 0.0)   # dentro
        self.assertGreater(b.sdf((0.0, 0.0, 0.0), 0.0), 0.0)  # lejos (origen)


class TestCodegen(unittest.TestCase):
    def test_generates_valid_looking_wgsl(self):
        from rtg.codegen import generate_wgsl
        wgsl = generate_wgsl(
            "node adam { root H L K\n form SELFANIM\n params { speed=1.0 } }\n"
            "node candil { root A W R\n form EMITTER\n place 2.0 3.0 2.0\n params { kelvin=2700 } }")
        self.assertIn("fn scene_sdf(", wgsl)
        self.assertIn("fn mat_color(", wgsl)
        self.assertIn("light_pos()", wgsl)    # la luz sale de Obj.pos (movible)
        self.assertIn("Obj.pos[", wgsl)       # posiciones en runtime (gizmo)
        self.assertIn("sin(t *", wgsl)        # adam (SelfAnim) se mueve en el shader
        self.assertIn("sd_sphere", wgsl)

    def test_scene_objects_order_matches_materials(self):
        from rtg.codegen import scene_objects
        from rtg import build
        _, behaviors = build(
            "node adam { root H L K\n form SELFANIM\n params { speed=1.0 } }\n"
            "node roca { root Q SH H\n form STATIC\n place -1.9 -0.2 0.0 }")
        objs = scene_objects(behaviors)
        self.assertEqual(len(objs), 2)
        self.assertEqual(objs[0][0], "adam")          # idx 0 = mat 1
        self.assertAlmostEqual(objs[1][1], -1.9)      # x de la roca

    def test_kelvin_to_rgb_warm_vs_cool(self):
        from rtg.codegen import kelvin_to_rgb
        warm = kelvin_to_rgb(2700)
        cool = kelvin_to_rgb(9000)
        # cálido: más rojo que azul; frío: más azul que el cálido
        self.assertGreater(warm[0], warm[2])
        self.assertGreater(cool[2], warm[2])


class TestFriendly(unittest.TestCase):
    def test_translates_to_internal_internal(self):
        from rtg.friendly import parse_friendly
        d = parse_friendly(
            "thing p { is walker  behavior paces  at 1 2 3  size 0.5 }").nodes[0]
        self.assertEqual(d.radicals, ("H", "L", "K"))   # walker -> raíz interna
        self.assertEqual(d.form, "SELFANIM")           # paces  -> forma interno
        self.assertEqual(d.place, (1.0, 2.0, 3.0))
        self.assertEqual(d.params["size"].data, 0.5)

    def test_param_aliases(self):
        from rtg.friendly import parse_friendly
        d = parse_friendly(
            "thing l { is lamp behavior emits warmth 2700 brightness 820 stride 2 }").nodes[0]
        self.assertIn("kelvin", d.params)    # warmth -> kelvin
        self.assertIn("lumens", d.params)    # brightness -> lumens
        self.assertIn("range", d.params)     # stride -> range

    def test_unknown_body_friendly_error(self):
        from rtg.friendly import build_friendly
        with self.assertRaises(ValidationError):
            build_friendly("thing x { is banana behavior still }")

    def test_unknown_behavior_friendly_error(self):
        from rtg.friendly import build_friendly
        with self.assertRaises(ValidationError):
            build_friendly("thing x { is rock behavior wobble }")

    def test_friendly_matches_internal_scene(self):
        # La capa de usuario y el interno interno producen la MISMA escena.
        from rtg.friendly import build_friendly
        friendly = (
            "thing player { is walker behavior paces at 0 0 0 size 0.5 speed 1.4 range 1.5 }\n"
            "thing lamp1  { is lamp   behavior emits at 2 3.5 2 kelvin 2700 lumens 820 }\n"
            "thing rock1  { is rock   behavior still at -1.9 -0.2 0 size 0.8 }\n"
        )
        internal = (
            "node player { root H L K\n form SELFANIM\n place 0 0 0\n params { size=0.5 speed=1.4 range=1.5 } }\n"
            "node lamp1  { root A W R\n form EMITTER\n place 2 3.5 2\n params { kelvin=2700 lumens=820 } }\n"
            "node rock1  { root Q Sh H\n form STATIC\n place -1.9 -0.2 0\n params { size=0.8 } }\n"
        )
        _, fb = build_friendly(friendly)
        _, hb = build(internal)
        self.assertEqual([b.family for b in fb], [b.family for b in hb])
        self.assertEqual([b.place for b in fb], [b.place for b in hb])
        self.assertEqual([b.is_light for b in fb], [b.is_light for b in hb])


class TestIncarnate(unittest.TestCase):
    """Fase 4: importar una malla y hornearla a campo de distancia."""

    def test_cube_sdf_sign(self):
        import numpy as np
        from rtg.incarnate import bake_sdf, normalize
        V = np.array([[-1, -1, -1], [1, -1, -1], [1, 1, -1], [-1, 1, -1],
                      [-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1]], float)
        F = np.array([[0, 1, 2], [0, 2, 3], [4, 6, 5], [4, 7, 6],
                      [0, 5, 1], [0, 4, 5], [1, 5, 6], [1, 6, 2],
                      [2, 6, 7], [2, 7, 3], [3, 7, 4], [3, 4, 0]])
        nv, _, _ = normalize(V)
        sdf = bake_sdf(nv, F, res=20)
        c = 10
        self.assertLess(sdf[c, c, c], 0.0)     # centro: dentro -> negativo
        self.assertGreater(sdf[0, 0, 0], 0.0)  # esquina: fuera -> positivo
        self.assertLess(sdf.min(), 0.0)        # hay interior


if __name__ == "__main__":
    unittest.main(verbosity=2)
