# Ejemplos para escribir en el editor

Escribe esto en el panel **ESCENA** y se verá al momento en **VISTA**.
Cada objeto es un `thing`:

```
thing <nombre> {
    is        <tipo>
    behavior  <comportamiento>
    at        <x> <y> <z>
    <parámetros...>
}
```

## Vocabulario

**is** (qué es): `walker` · `lamp` · `rock` · `wall` · `water` · `seed`

**behavior** (qué hace): `still` (quieto) · `paces` (pasea) · `moves` (se desplaza)
· `emits` (ilumina) · `reacts` · `many`

**Parámetros:**
- `at x y z` — posición (el suelo está en y = -1)
- `size n` — tamaño
- `speed n` `stride n` — velocidad y amplitud del paseo
- `warmth n` — temperatura de la luz en kelvin (2700 = cálida, 6500 = blanca)
- `brightness n` — brillo de la luz (lúmenes)
- `color <nombre>` — `red` `green` `blue` `white` `black` `yellow` `orange`
  `purple` `cyan` `grey` `brown`
- `shiny <0..1>` — reflectividad del objeto (0 = mate, 1 = espejo). El suelo ya
  refleja por defecto.

---

## 1 · Una piedra

```
thing piedra {
    is        rock
    behavior  still
    at        0 -0.4 0
    size 0.6
}
```

## 2 · Una piedra y una luz

```
thing piedra {
    is rock   behavior still   at 0 -0.4 0   size 0.6
}

thing sol {
    is lamp   behavior emits   at 3 4 2
    warmth 3000   brightness 1200
}
```

## 3 · Algo que se mueve y dos colores

```
thing sol {
    is lamp   behavior emits   at 2 4 2   warmth 4000   brightness 1500
}

thing rojo {
    is rock   behavior paces   at -1.2 -0.4 0   size 0.6
    color red   speed 1.2   stride 1.0
}

thing azul {
    is rock   behavior still   at 1.2 -0.4 0   size 0.6
    color blue
}
```

## 4 · Un muro, agua y una pelota

```
thing sol  { is lamp  behavior emits at 3 4 3 warmth 5000 brightness 1600 }
thing muro { is wall  behavior still at -2 -0.3 0 size 0.7   color grey }
thing mar  { is water behavior still at 0 -1 0 }
thing bola { is rock  behavior paces at 1.5 -0.4 0 size 0.5 color orange speed 1.5 }
```

> Consejo: el suelo está en `y = -1`. Para que algo "toque" el suelo,
> su `y` debe ser `-1 + size` aproximadamente.
