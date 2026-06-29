# -*- coding: utf-8 -*-
"""
RTGEngine — Editor (tema oscuro)

Editor con el VIEWPORT del motor integrado dentro de la propia ventana. Se
escribe la escena en lenguaje claro y se ve en directo a la derecha; los
cambios se aplican solos (hot-reload). Herramientas: outliner de objetos,
paleta para añadir cosas, exportar a PNG, ejemplos y arrastre con gizmos.

Ejecutar:   python studio.py            (con consola)
            pythonw studio.py           (sin consola)
Empaquetar: python build_app.py         (genera dist/RTGEngine.exe)
"""
import os
import re
import sys
import ctypes
import tempfile
import threading
import subprocess
from ctypes import wintypes
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog

# DPI-aware para que los píxeles de Tk y de Win32 coincidan (viewport encajado).
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

# Raíz: junto al script (dev) o junto al .exe empaquetado.
if getattr(sys, "frozen", False):
    ENGINE = os.path.join(os.path.dirname(sys.executable), "engine")
else:
    ENGINE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ENGINE)

from rtg.friendly import build_friendly          # noqa: E402
from rtg.codegen import emit_wgsl, scene_objects  # noqa: E402
from rtg.errors import RTGError                   # noqa: E402

CORE = os.path.join(ENGINE, "rtg-core")
EXAMPLES = os.path.join(ENGINE, "examples")


def _scene_dir():
    """Carpeta escribible donde se vuelca la escena para el motor.
    En dev: rtg-core/src. Empaquetado: %LOCALAPPDATA%/RTGEngine."""
    src = os.path.join(CORE, "src")
    if os.path.isdir(src) and os.access(src, os.W_OK):
        return src
    d = os.path.join(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()), "RTGEngine")
    os.makedirs(d, exist_ok=True)
    return d


SCENE_DIR = _scene_dir()
SCENE_OUT = os.path.join(SCENE_DIR, "scene.generated.wgsl")
SCENE_OBJ = os.path.join(SCENE_DIR, "scene.objects.txt")
SCENE_LIVE = os.path.join(SCENE_DIR, "scene.live.txt")

# ----------------------------------------------------------------------------
# Paleta (tema oscuro coal/gold)
# ----------------------------------------------------------------------------
COAL    = "#121216"   # fondo general
PANEL   = "#191920"   # paneles
PANEL2  = "#202028"   # campos / listas
EDIT_BG = "#15151b"   # editor de texto
INK     = "#e3e3ea"   # texto principal
MUTED   = "#8b8b98"   # texto secundario
FAINT   = "#5a5a66"   # texto tenue
ACCENT  = "#cbb83a"   # dorado
ACCENT2 = "#5b8fd0"   # azul
GREEN   = "#5fbf7a"
DANGER  = "#e5736b"
BORDER  = "#2c2c36"
HOVER   = "#2a2a34"

# ----------------------------------------------------------------------------
# Win32: incrustar la ventana del motor dentro de un panel de Tkinter
# ----------------------------------------------------------------------------
user32 = ctypes.windll.user32
user32.GetWindowLongPtrW.restype = ctypes.c_longlong
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowLongPtrW.restype = ctypes.c_longlong
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_longlong]
user32.SetParent.restype = wintypes.HWND
user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
user32.MoveWindow.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, ctypes.c_int, wintypes.BOOL]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.SetFocus.restype = wintypes.HWND
user32.SetFocus.argtypes = [wintypes.HWND]
kernel32 = ctypes.windll.kernel32
kernel32.GetCurrentThreadId.restype = wintypes.DWORD
VK_RBUTTON = 0x02

GWL_STYLE = -16
WS_CHILD = 0x40000000
WS_VISIBLE = 0x10000000
WS_POPUP = 0x80000000
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
GW_OWNER = 4
CREATE_NO_WINDOW = 0x08000000
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def find_hwnd_by_pid(pid):
    found = []

    def cb(hwnd, _lp):
        wpid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if (wpid.value == pid and user32.IsWindowVisible(hwnd)
                and user32.GetWindow(hwnd, GW_OWNER) == 0):
            found.append(hwnd)
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return found[0] if found else None


DEFAULT_SCENE = ("; Escribe tu escena aquí y la verás en directo a la derecha.\n"
                 "; Usa la barra: « + Añadir » para insertar objetos.\n")

# Plantillas para la paleta « + Añadir ».
TEMPLATES = {
    "Caminante": ("walker", "paces", "size 0.5   speed 1.4   stride 1.4   color green"),
    "Lámpara":   ("lamp", "emits", "warmth 4300   brightness 3000   reach 10"),
    "Roca":      ("rock", "still", "size 0.7   color grey"),
    "Muro":      ("wall", "still", "size 0.6   color brown"),
    "Agua":      ("water", "still", ""),
    "Vegetación":("seed", "still", "color green"),
}


def find_exe():
    for prof in ("release", "debug"):
        p = os.path.join(CORE, "target", prof, "rtg-core.exe")
        if os.path.exists(p):
            return p
    # empaquetado: junto al .exe
    p = os.path.join(os.path.dirname(sys.executable), "rtg-core.exe")
    return p if os.path.exists(p) else None


class Editor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RTGEngine — Editor")
        self.configure(bg=COAL)
        self.geometry("1380x820")
        self.minsize(1040, 640)
        self.exe = find_exe()
        self.viewport = None
        self.engine_hwnd = None
        self._apply_job = None
        self._embed_tries = 0
        self._focus_target = "editor"
        self.asset_path = None       # modelo OBJ horneado a SDF (.sdf)
        self.asset_pos = [0.0, 0.0, 0.0]
        self.asset_scale = 0.8
        self.mesh_path = None        # personaje FBX rasterizado (.rmesh)
        self.mesh_tex = None         # su textura difusa (.png)
        self.mesh_anim = None        # animación horneada (.ranim)
        self.mesh_pos = [0.0, 0.0, 0.0]
        self.mesh_scale = 1.0
        self._mesh_job = None

        self._init_style()
        self._build_ui()
        self._load_initial()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind_all("<Control-s>", lambda e: self.save_file())
        self.bind_all("<Control-o>", lambda e: self.open_file())
        self.bind_all("<Control-z>", lambda e: self._undo())
        self.bind_all("<Control-y>", lambda e: self._redo())
        self._insp_loading = False

        self.update_idletasks()
        self.apply()
        self._refresh_outliner()
        self.after(250, self._start_viewport)
        self._live_mtime = self._live_stamp()
        self.after(400, self._poll_live)

    # ---------------- estilo / tema oscuro ----------------
    def _init_style(self):
        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure("Tree.Treeview", background=PANEL2, fieldbackground=PANEL2,
                     foreground=INK, borderwidth=0, rowheight=24,
                     font=("Segoe UI", 9))
        st.map("Tree.Treeview",
               background=[("selected", ACCENT)], foreground=[("selected", COAL)])
        st.layout("Tree.Treeview", [("Tree.Treeview.treearea", {"sticky": "nswe"})])
        st.configure("Vert.TScrollbar", background=PANEL2, troughcolor=COAL,
                     borderwidth=0, arrowcolor=MUTED)

    def _btn(self, parent, text, cmd, accent=False, width=None):
        b = tk.Button(parent, text=text, command=cmd, relief="flat", bd=0,
                      font=("Segoe UI", 9, "bold" if accent else "normal"),
                      bg=(ACCENT if accent else PANEL2),
                      fg=(COAL if accent else INK),
                      activebackground=(ACCENT if accent else HOVER),
                      activeforeground=(COAL if accent else INK),
                      padx=12, pady=6, cursor="hand2")
        if width:
            b.config(width=width)
        if not accent:
            b.bind("<Enter>", lambda e: b.config(bg=HOVER))
            b.bind("<Leave>", lambda e: b.config(bg=PANEL2))
        return b

    # ---------------- UI ----------------
    def _build_ui(self):
        # --- barra de herramientas ---
        bar = tk.Frame(self, bg=PANEL, height=46)
        bar.pack(fill="x", side="top")
        bar.pack_propagate(False)
        tk.Label(bar, text="  RTG", font=("Segoe UI Semibold", 13, "bold"),
                 fg=ACCENT, bg=PANEL).pack(side="left", padx=(8, 2))
        tk.Label(bar, text="Engine", font=("Segoe UI", 11),
                 fg=INK, bg=PANEL).pack(side="left", padx=(0, 14))

        def sep():
            tk.Frame(bar, bg=BORDER, width=1, height=24).pack(side="left", padx=8, pady=11)

        self._btn(bar, "Nuevo", self.new_file).pack(side="left", padx=3, pady=7)
        self._btn(bar, "Abrir", self.open_file).pack(side="left", padx=3, pady=7)
        self._btn(bar, "Guardar", self.save_file).pack(side="left", padx=3, pady=7)
        sep()
        # menú « + Añadir »
        addb = tk.Menubutton(bar, text="+ Añadir", font=("Segoe UI", 9, "bold"),
                             bg=ACCENT, fg=COAL, activebackground=ACCENT,
                             activeforeground=COAL, relief="flat", bd=0,
                             padx=12, pady=6, cursor="hand2")
        addmenu = tk.Menu(addb, tearoff=0, bg=PANEL2, fg=INK,
                          activebackground=ACCENT, activeforeground=COAL, bd=0)
        for name in TEMPLATES:
            addmenu.add_command(label=name, command=lambda n=name: self.add_object(n))
        addb.config(menu=addmenu)
        addb.pack(side="left", padx=3, pady=7)
        # menú Ejemplos
        exb = tk.Menubutton(bar, text="Ejemplos", font=("Segoe UI", 9),
                            bg=PANEL2, fg=INK, activebackground=HOVER,
                            activeforeground=INK, relief="flat", bd=0,
                            padx=12, pady=6, cursor="hand2")
        exmenu = tk.Menu(exb, tearoff=0, bg=PANEL2, fg=INK,
                         activebackground=ACCENT, activeforeground=COAL, bd=0)
        for fn in sorted(f for f in os.listdir(EXAMPLES) if f.endswith(".scene")) \
                if os.path.isdir(EXAMPLES) else []:
            exmenu.add_command(label=fn, command=lambda f=fn: self.load_example(f))
        exb.config(menu=exmenu)
        exb.pack(side="left", padx=3, pady=7)
        sep()
        self._btn(bar, "Importar modelo", self.import_model).pack(side="left", padx=3, pady=7)
        self._btn(bar, "Render PNG", self.render_png).pack(side="left", padx=3, pady=7)

        # colocación del personaje importado (a la derecha)
        cf = tk.Frame(bar, bg=PANEL)
        cf.pack(side="right", padx=8)
        tk.Label(cf, text="Personaje", font=("Segoe UI", 8), fg=FAINT,
                 bg=PANEL).pack(side="left", padx=(0, 4))
        self._char_vars = {}
        for label, key in [("X", "x"), ("Y", "y"), ("Z", "z"), ("esc", "s")]:
            tk.Label(cf, text=label, font=("Segoe UI", 8), fg=FAINT, bg=PANEL).pack(side="left")
            v = tk.StringVar(value="1" if key == "s" else "0")
            e = tk.Entry(cf, textvariable=v, width=4, bg=PANEL2, fg=INK, relief="flat",
                         insertbackground=ACCENT, justify="center", highlightthickness=1,
                         highlightbackground=BORDER, highlightcolor=ACCENT)
            e.pack(side="left", padx=(1, 4))
            e.bind("<Return>", lambda ev: self._on_char_change())
            e.bind("<FocusOut>", lambda ev: self._on_char_change())
            self._char_vars[key] = v

        # --- cuerpo: izquierda (outliner + editor) | derecha (viewport) ---
        body = tk.Frame(self, bg=COAL)
        body.pack(fill="both", expand=True, padx=10, pady=(8, 0))
        body.columnconfigure(0, weight=0, minsize=300)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        left = tk.Frame(body, bg=COAL, width=320)
        left.grid(row=0, column=0, sticky="ns")
        left.grid_propagate(False)

        # Outliner
        tk.Label(left, text="OBJETOS", font=("Segoe UI", 8, "bold"),
                 fg=ACCENT, bg=COAL).pack(anchor="w", pady=(0, 2))
        olf = tk.Frame(left, bg=BORDER, bd=0)
        olf.pack(fill="x", pady=(0, 8))
        self.outliner = ttk.Treeview(olf, style="Tree.Treeview", show="tree",
                                     height=6, selectmode="browse")
        self.outliner.pack(fill="x", padx=1, pady=1)
        self.outliner.bind("<<TreeviewSelect>>", self._outliner_select)

        # Inspector (propiedades del objeto seleccionado)
        tk.Label(left, text="PROPIEDADES", font=("Segoe UI", 8, "bold"),
                 fg=ACCENT, bg=COAL).pack(anchor="w", pady=(2, 2))
        insp = tk.Frame(left, bg=PANEL)
        insp.pack(fill="x", pady=(0, 8))
        insp.columnconfigure(1, weight=1)
        self._insp_name = tk.Label(insp, text="(nada seleccionado)", fg=MUTED, bg=PANEL,
                                   font=("Segoe UI", 9, "italic"), anchor="w")
        self._insp_name.grid(row=0, column=0, columnspan=4, sticky="w", padx=8, pady=(6, 2))
        self._insp_vars = {}
        self._insp_current = None
        for col, (label, key) in enumerate(
                [("X", "x"), ("Y", "y"), ("Z", "z"), ("tam", "size")]):
            tk.Label(insp, text=label, fg=FAINT, bg=PANEL, font=("Segoe UI", 8)).grid(
                row=1, column=col, padx=(8 if col == 0 else 2, 2))
            v = tk.StringVar()
            e = tk.Entry(insp, textvariable=v, width=6, bg=PANEL2, fg=INK,
                         insertbackground=ACCENT, relief="flat", justify="center",
                         disabledbackground=PANEL, highlightthickness=1,
                         highlightbackground=BORDER, highlightcolor=ACCENT)
            e.grid(row=2, column=col, padx=(8 if col == 0 else 2, 2), pady=(0, 6))
            e.bind("<Return>", lambda ev: self._inspector_apply())
            e.bind("<FocusOut>", lambda ev: self._inspector_apply())
            self._insp_vars[key] = v

        # selectores: tipo · comportamiento · color
        self._insp_sel = {}
        selrows = [
            ("Tipo", "type", ["walker", "lamp", "rock", "wall", "water", "seed"]),
            ("Comporta.", "behavior",
             ["still", "paces", "emits", "reacts", "many", "baked", "driven"]),
            ("Color", "color", ["—", "red", "green", "blue", "yellow", "orange",
                                "purple", "cyan", "white", "grey", "brown"]),
        ]
        for r, (label, key, opts) in enumerate(selrows, start=3):
            tk.Label(insp, text=label, fg=FAINT, bg=PANEL, font=("Segoe UI", 8)).grid(
                row=r, column=0, sticky="w", padx=(8, 2), pady=2)
            var = tk.StringVar(value=opts[0])
            om = tk.OptionMenu(insp, var, *opts,
                               command=lambda _v, k=key: self._inspector_select(k))
            om.config(bg=PANEL2, fg=INK, activebackground=HOVER, activeforeground=INK,
                      relief="flat", bd=0, highlightthickness=0, anchor="w",
                      font=("Segoe UI", 8), cursor="hand2")
            om["menu"].config(bg=PANEL2, fg=INK, activebackground=ACCENT,
                              activeforeground=COAL, bd=0)
            om.grid(row=r, column=1, columnspan=3, sticky="we", padx=(2, 8), pady=2)
            self._insp_sel[key] = var

        btns = tk.Frame(insp, bg=PANEL)
        btns.grid(row=6, column=0, columnspan=4, sticky="we", padx=8, pady=(6, 8))
        self._btn(btns, "Duplicar", self.duplicate_object).pack(side="left", padx=(0, 4))
        self._btn(btns, "Borrar", self.delete_object).pack(side="left")

        # Editor
        tk.Label(left, text="ESCENA", font=("Segoe UI", 8, "bold"),
                 fg=ACCENT, bg=COAL).pack(anchor="w", pady=(0, 2))
        self.editor = scrolledtext.ScrolledText(
            left, bg=EDIT_BG, fg=INK, insertbackground=ACCENT,
            selectbackground="#3a3a48", font=("Consolas", 10), relief="flat",
            borderwidth=10, undo=True, wrap="none")
        self.editor.pack(fill="both", expand=True)
        self.editor.bind("<KeyRelease>", self._on_edit)
        # resaltado básico de palabras clave
        for tag, col in (("kw", ACCENT2), ("type", GREEN), ("num", "#c98a5b"),
                         ("comment", FAINT)):
            self.editor.tag_configure(tag, foreground=col)

        # Derecha: viewport
        right = tk.Frame(body, bg=COAL)
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)
        tk.Label(right, text="VISTA", font=("Segoe UI", 8, "bold"),
                 fg=ACCENT, bg=COAL).grid(row=0, column=0, sticky="w", pady=(0, 2))
        self.viewport_frame = tk.Frame(right, bg="#05050a", highlightthickness=1,
                                       highlightbackground=BORDER)
        self.viewport_frame.grid(row=1, column=0, sticky="nsew")
        self.viewport_frame.bind("<Configure>", lambda e: self._fit_viewport())
        self._vp_hint = tk.Label(
            self.viewport_frame,
            text=("Iniciando viewport…\n\n"
                  "Mover objetos:  clic IZQUIERDO selecciona y arrastra\n"
                  "Ejes del gizmo (rojo X · verde Y · azul Z) para un solo eje\n"
                  "Cámara:  clic DERECHO + ratón  ·  WASD  ·  E/Q  ·  rueda"),
            fg=MUTED, bg="#05050a", font=("Segoe UI", 9), justify="center")
        self._vp_hint.place(relx=0.5, rely=0.5, anchor="center")

        # --- barra de estado ---
        sb = tk.Frame(self, bg=PANEL)
        sb.pack(fill="x", side="bottom")
        self.status = tk.Label(sb, text="Listo.", anchor="w", bg=PANEL,
                               fg=MUTED, font=("Consolas", 9), padx=10, pady=4)
        self.status.pack(side="left")
        tk.Label(sb, text="clic dcho = cámara · clic izq = mover · Espacio = refinar",
                 anchor="e", bg=PANEL, fg=FAINT, font=("Segoe UI", 8),
                 padx=10).pack(side="right")

        if not self.exe:
            self._set_status("Motor sin compilar: cd rtg-core && cargo build --release",
                             err=True)

    def _load_initial(self):
        demo = os.path.join(EXAMPLES, "05_completo.scene")
        if os.path.exists(demo):
            with open(demo, "r", encoding="utf-8") as f:
                self.editor.insert("1.0", f.read())
        else:
            self.editor.insert("1.0", DEFAULT_SCENE)
        self._highlight()

    # ---------------- lógica de escena ----------------
    def _set_status(self, msg, err=False):
        self.status.config(text=msg, fg=(DANGER if err else MUTED))

    def _on_edit(self, _evt=None):
        if self._apply_job is not None:
            self.after_cancel(self._apply_job)
        self._apply_job = self.after(400, self._apply_and_refresh)
        self._highlight()

    def _apply_and_refresh(self):
        self.apply()
        self._refresh_outliner()

    def _undo(self):
        try:
            self.editor.edit_undo()
        except tk.TclError:
            return "break"
        self._highlight()
        self._apply_and_refresh()
        return "break"

    def _redo(self):
        try:
            self.editor.edit_redo()
        except tk.TclError:
            return "break"
        self._highlight()
        self._apply_and_refresh()
        return "break"

    def apply(self):
        self._apply_job = None
        src = self.editor.get("1.0", "end")
        try:
            _, behaviors = build_friendly(src)
        except RTGError as e:
            self._set_status(f"✗ {e}", err=True)
            return
        except Exception as e:  # noqa: BLE001
            self._set_status(f"✗ {e}", err=True)
            return
        self._write_sidecar(behaviors)
        tmp = SCENE_OUT + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(emit_wgsl(behaviors))
        os.replace(tmp, SCENE_OUT)
        n = len(behaviors)
        self._set_status(f"✓ aplicado · {n} objeto{'s' if n != 1 else ''}")

    @staticmethod
    def _write_sidecar(behaviors):
        lines = [f"{i} {x:.5f} {y:.5f} {z:.5f} {size:.5f} {kind} {name}"
                 for i, (name, x, y, z, size, kind) in enumerate(scene_objects(behaviors))]
        tmp = SCENE_OBJ + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + ("\n" if lines else ""))
        os.replace(tmp, SCENE_OBJ)

    # ---------------- herramientas ----------------
    def add_object(self, kind):
        body, behavior, params = TEMPLATES[kind]
        # nombre único
        text = self.editor.get("1.0", "end")
        base = body
        i, name = 1, body
        while re.search(r"\bthing\s+" + re.escape(name) + r"\b", text):
            i += 1
            name = f"{base}{i}"
        block = (f"\nthing {name} {{\n"
                 f"    is {body}   behavior {behavior}\n"
                 f"    at 0 0 0\n"
                 + (f"    {params}\n" if params else "")
                 + "}\n")
        self.editor.insert("end", block)
        self._highlight()
        self._apply_and_refresh()
        self._set_status(f"+ añadido '{name}' ({kind})")

    def load_example(self, fn):
        p = os.path.join(EXAMPLES, fn)
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = f.read()
        except OSError as e:
            self._set_status(f"✗ {e}", err=True)
            return
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", data)
        self._highlight()
        self._apply_and_refresh()
        self._set_status(f"Ejemplo cargado: {fn}")

    def new_file(self):
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", DEFAULT_SCENE)
        self._highlight()
        self._apply_and_refresh()

    def render_png(self):
        if not self.exe:
            self._set_status("Motor sin compilar.", err=True)
            return
        path = filedialog.asksaveasfilename(
            title="Exportar render", defaultextension=".png",
            filetypes=[("Imagen PNG", "*.png")])
        if not path:
            return
        self.apply()  # asegura la escena en disco
        self._set_status("Renderizando PNG… (acumulando muestras)")
        self.update_idletasks()

        def work():
            env = self._viewport_env()
            try:
                subprocess.run(
                    [self.exe, "--snapshot", path, "--samples", "48"],
                    cwd=CORE, env=env, creationflags=CREATE_NO_WINDOW,
                    timeout=120)
                ok = os.path.exists(path)
            except Exception:  # noqa: BLE001
                ok = False
            self.after(0, lambda: self._set_status(
                f"✓ render guardado: {os.path.basename(path)}" if ok
                else "✗ no se pudo renderizar", err=not ok))

        threading.Thread(target=work, daemon=True).start()

    # ---------------- outliner ----------------
    def _scene_things(self):
        """Lista (name, type, line) de los bloques 'thing' del texto, en orden."""
        out = []
        text = self.editor.get("1.0", "end")
        for m in re.finditer(r"thing\s+(\w+)\s*\{(.*?)\}", text, re.DOTALL):
            name, body = m.group(1), m.group(2)
            tm = re.search(r"\bis\s+(\w+)", body)
            typ = tm.group(1) if tm else "?"
            line = text.count("\n", 0, m.start()) + 1
            out.append((name, typ, line))
        return out

    def _refresh_outliner(self):
        if not hasattr(self, "outliner"):
            return
        sel = self.outliner.selection()
        self.outliner.delete(*self.outliner.get_children())
        self._things_by_line = {}
        for name, typ, line in self._scene_things():
            self._things_by_line[str(line)] = name
            self.outliner.insert("", "end", iid=str(line),
                                 text=f"  {name}   ·  {typ}")
        # modelos importados (no son 'things' del texto): personaje y cubo
        if self.mesh_path:
            self.outliner.insert("", "end", iid="@char", text="  personaje   ·  FBX")
        if self.asset_path:
            self.outliner.insert("", "end", iid="@asset", text="  modelo   ·  OBJ")
        if sel and self.outliner.exists(sel[0]):
            self.outliner.selection_set(sel[0])

    def _outliner_select(self, _evt=None):
        sel = self.outliner.selection()
        if not sel:
            return
        iid = sel[0]
        if iid in ("@char", "@asset"):
            self._load_model_inspector(iid)
            return
        self.editor.see(f"{iid}.0")
        self.editor.mark_set("insert", f"{iid}.0")
        name = getattr(self, "_things_by_line", {}).get(iid)
        if name:
            self._load_inspector(name)

    # ---------------- inspector ----------------
    def _load_inspector(self, name):
        text = self.editor.get("1.0", "end")
        m = re.search(r"thing\s+" + re.escape(name) + r"\b.*?\{(.*?)\}", text, re.DOTALL)
        self._insp_current = name if m else None
        self._insp_name.config(text=f"  {name}" if m else "(nada seleccionado)",
                               fg=INK if m else MUTED)
        block = m.group(1) if m else ""
        at = re.search(r"\bat\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)", block)
        sz = re.search(r"\bsize\s+(-?[\d.]+)", block)
        vals = {"x": at.group(1) if at else "0", "y": at.group(2) if at else "0",
                "z": at.group(3) if at else "0", "size": sz.group(1) if sz else ""}
        for k, v in vals.items():
            self._insp_vars[k].set(v)
        # selectores (tipo / comportamiento / color)
        self._insp_loading = True
        for key, pat in (("type", r"\bis\s+(\w+)"), ("behavior", r"\bbehavior\s+(\w+)"),
                         ("color", r"\bcolor\s+(\w+)")):
            mm = re.search(pat, block)
            self._insp_sel[key].set(mm.group(1) if mm else ("—" if key == "color" else ""))
        self._insp_loading = False

    def _load_model_inspector(self, iid):
        """Inspector para un modelo importado (personaje FBX o cubo OBJ)."""
        self._insp_current = iid
        if iid == "@char":
            pos, sc, label = self.mesh_pos, self.mesh_scale, "  personaje (FBX)"
        else:
            pos, sc, label = self.asset_pos, self.asset_scale, "  modelo (OBJ)"
        self._insp_name.config(text=label, fg=INK)
        self._insp_loading = True
        for k, v in zip(("x", "y", "z"), pos):
            self._insp_vars[k].set(f"{v:g}")
        self._insp_vars["size"].set(f"{sc:g}")
        for k in ("type", "behavior", "color"):
            self._insp_sel[k].set("—" if k == "color" else "")
        self._insp_loading = False

    def _debounced_relaunch(self):
        if self._mesh_job is not None:
            self.after_cancel(self._mesh_job)
        self._mesh_job = self.after(500, self._relaunch_viewport)

    def _inspector_apply(self):
        cur = self._insp_current
        if not cur:
            return
        # modelo importado (personaje / cubo): mover/escalar + relanzar
        if cur in ("@char", "@asset"):
            try:
                pos = [float(self._insp_vars[k].get() or 0) for k in ("x", "y", "z")]
                sc = max(float(self._insp_vars["size"].get() or 1), 0.01)
            except ValueError:
                return
            if cur == "@char":
                self.mesh_pos, self.mesh_scale = pos, sc
            else:
                self.asset_pos, self.asset_scale = pos, sc
            self._debounced_relaunch()
            return
        name = cur
        try:
            x = float(self._insp_vars["x"].get() or 0)
            y = float(self._insp_vars["y"].get() or 0)
            z = float(self._insp_vars["z"].get() or 0)
        except ValueError:
            return
        text = self.editor.get("1.0", "end")
        new = self._set_at(text, name, x, y, z)
        sz = self._insp_vars["size"].get().strip()
        if sz:
            try:
                new = self._set_param(new, name, "size", float(sz))
            except ValueError:
                pass
        if new == text:
            return
        # preservar la posición de scroll del editor
        yview = self.editor.yview()
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", new)
        self.editor.yview_moveto(yview[0])
        self._highlight()
        self._apply_and_refresh()

    def _inspector_select(self, key):
        """Un selector (tipo/comportamiento/color) cambió → reescribe el bloque."""
        if getattr(self, "_insp_loading", False) or not self._insp_current:
            return
        if self._insp_current in ("@char", "@asset"):
            return        # los modelos importados no tienen tipo/comportamiento/color
        name = self._insp_current
        val = self._insp_sel[key].get()
        text = self.editor.get("1.0", "end")
        kw = {"type": "is", "behavior": "behavior", "color": "color"}[key]
        if key == "color" and val == "—":
            new = self._remove_word(text, name, "color")
        else:
            new = self._set_word(text, name, kw, val)
        if new == text:
            return
        yview = self.editor.yview()
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", new)
        self.editor.yview_moveto(yview[0])
        self._highlight()
        self._apply_and_refresh()

    def duplicate_object(self):
        name = self._insp_current
        if not name:
            return
        text = self.editor.get("1.0", "end")
        m = re.search(r"thing\s+" + re.escape(name) + r"\b.*?\}", text, re.DOTALL)
        if not m:
            return
        i, new_name = 2, f"{name}2"
        while re.search(r"\bthing\s+" + re.escape(new_name) + r"\b", text):
            i += 1
            new_name = f"{name}{i}"
        block = m.group(0)
        block = re.sub(r"thing\s+" + re.escape(name) + r"\b",
                       f"thing {new_name}", block, count=1)
        self.editor.insert("end", "\n" + block + "\n")
        self._highlight()
        self._apply_and_refresh()
        self._set_status(f"+ duplicado '{new_name}'")

    def delete_object(self):
        cur = self._insp_current
        if not cur:
            return
        # borrar un modelo importado (personaje / cubo)
        if cur == "@char":
            self.mesh_path = self.mesh_tex = self.mesh_anim = None
            self._insp_current = None
            self._insp_name.config(text="(nada seleccionado)", fg=MUTED)
            self._refresh_outliner()
            self._set_status("– personaje quitado")
            self._relaunch_viewport()
            return
        if cur == "@asset":
            self.asset_path = None
            self._insp_current = None
            self._insp_name.config(text="(nada seleccionado)", fg=MUTED)
            self._refresh_outliner()
            self._set_status("– modelo quitado")
            self._relaunch_viewport()
            return
        name = cur
        text = self.editor.get("1.0", "end")
        new = re.sub(r"\n?\s*thing\s+" + re.escape(name) + r"\b.*?\}\s*",
                     "\n", text, count=1, flags=re.DOTALL)
        if new == text:
            return
        self._insp_current = None
        self._insp_name.config(text="(nada seleccionado)", fg=MUTED)
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", new)
        self._highlight()
        self._apply_and_refresh()
        self._set_status(f"– borrado '{name}'")

    @staticmethod
    def _set_word(text, name, key, value):
        """Pone/actualiza un token de palabra (is/behavior/color) en el bloque."""
        pat = re.compile(r"(thing\s+" + re.escape(name) + r"\b.*?\{)(.*?)(\})", re.DOTALL)
        m = pat.search(text)
        if not m:
            return text
        block = m.group(2)
        if re.search(r"\b" + key + r"\s+\w+", block):
            block = re.sub(r"\b" + key + r"\s+\w+", f"{key} {value}", block, count=1)
        else:
            block = block.rstrip() + f"\n    {key} {value}\n"
        return text[:m.start(2)] + block + text[m.end(2):]

    @staticmethod
    def _remove_word(text, name, key):
        pat = re.compile(r"(thing\s+" + re.escape(name) + r"\b.*?\{)(.*?)(\})", re.DOTALL)
        m = pat.search(text)
        if not m:
            return text
        block = re.sub(r"\s*\b" + key + r"\s+\w+", "", m.group(2), count=1)
        return text[:m.start(2)] + block + text[m.end(2):]

    # ---------------- resaltado de sintaxis ----------------
    def _highlight(self):
        for tag in ("kw", "type", "num", "comment"):
            self.editor.tag_remove(tag, "1.0", "end")
        text = self.editor.get("1.0", "end")
        rules = [
            ("comment", r";[^\n]*"),
            ("kw", r"\b(thing|is|behavior|at)\b"),
            ("type", r"\b(walker|lamp|rock|wall|water|seed|character|light|"
                     r"stone|solid|structure|block|fluid|sea|scatter|foliage|"
                     r"still|paces|emits|shines|reacts|many|baked|driven|walks|moves)\b"),
            ("num", r"-?\d+\.?\d*"),
        ]
        for tag, pat in rules:
            for m in re.finditer(pat, text):
                s = f"1.0+{m.start()}c"
                e = f"1.0+{m.end()}c"
                self.editor.tag_add(tag, s, e)

    # ---------------- viewport incrustado ----------------
    def _viewport_env(self):
        env = os.environ.copy()
        env["RTG_SCENE_DIR"] = SCENE_DIR
        if self.asset_path and os.path.exists(self.asset_path):
            env["RTG_ASSET"] = self.asset_path
            env["RTG_ASSET_POS"] = "{},{},{}".format(*self.asset_pos)
            env["RTG_ASSET_SCALE"] = str(self.asset_scale)
        if self.mesh_path and os.path.exists(self.mesh_path):
            env["RTG_MESH"] = self.mesh_path
            if self.mesh_tex and os.path.exists(self.mesh_tex):
                env["RTG_MESH_TEX"] = self.mesh_tex
            if self.mesh_anim and os.path.exists(self.mesh_anim):
                env["RTG_MESH_ANIM"] = self.mesh_anim
            env["RTG_MESH_POS"] = "{},{},{}".format(*self.mesh_pos)
            env["RTG_MESH_SCALE"] = str(self.mesh_scale)
        return env

    def _start_viewport(self):
        if not self.exe:
            self._vp_hint.config(text="No encuentro el motor compilado.\n"
                                      "Ejecuta:  cd rtg-core && cargo build --release")
            return
        self.engine_hwnd = None
        self.viewport = subprocess.Popen(
            [self.exe], cwd=CORE, env=self._viewport_env(),
            creationflags=CREATE_NO_WINDOW)
        self._embed_tries = 0
        self.after(300, self._embed)

    def _relaunch_viewport(self):
        if self.viewport is not None and self.viewport.poll() is None:
            self.viewport.terminate()
        self.engine_hwnd = None
        self._focus_target = "editor"
        self._vp_hint.place(relx=0.5, rely=0.5, anchor="center")
        self.after(150, self._start_viewport)

    def import_model(self):
        p = filedialog.askopenfilename(
            title="Importar modelo (FBX personaje · OBJ a campo)",
            filetypes=[("Modelos", "*.fbx *.obj"), ("Personaje FBX", "*.fbx"),
                       ("Malla OBJ", "*.obj"), ("Todos", "*.*")])
        if not p:
            return
        if p.lower().endswith(".fbx"):
            self._import_fbx(p)
        else:
            self._import_obj(p)

    def _import_fbx(self, p):
        self._set_status("Importando FBX (malla + textura + animación)… puede tardar")
        self.update_idletasks()
        try:
            from rtg.fbx import export_skinned
            prefix = os.path.join(SCENE_DIR, "imported_mesh")
            meta = export_skinned(p, prefix)
        except Exception as e:  # noqa: BLE001
            self._set_status(f"✗ no se pudo importar el FBX: {e}", err=True)
            return
        self.mesh_path = prefix + ".rmesh"
        self.mesh_tex = (prefix + ".png") if meta["has_texture"] else None
        self.mesh_anim = (prefix + ".ranim") if meta.get("animated") else None
        an = (f"animado ({meta['frames']} frames, {meta['bones']} huesos)"
              if meta.get("animated") else "estático")
        self._set_status(f"✓ personaje importado ({meta['vertex_count']} vértices) — {an}")
        self._refresh_outliner()
        self._relaunch_viewport()

    def _import_obj(self, p):
        self._set_status("Importando y horneando el modelo a campo… (puede tardar)")
        self.update_idletasks()
        try:
            from rtg.incarnate import incarnate
            _, meta = incarnate(p, 48)
        except Exception as e:  # noqa: BLE001
            self._set_status(f"✗ no se pudo importar: {e}", err=True)
            return
        name = meta["name"]
        self.asset_path = os.path.join(os.path.dirname(os.path.abspath(p)), name + ".sdf")
        r = meta["report"]
        self._set_status(f"✓ modelo '{name}' importado ({r['triangulos']} triángulos) y cargado")
        self._refresh_outliner()
        self._relaunch_viewport()

    def _on_char_change(self):
        """Coloca/escala el personaje (relanza el viewport con el nuevo encuadre)."""
        if not self.mesh_path:
            return
        try:
            self.mesh_pos = [float(self._char_vars[k].get() or 0) for k in ("x", "y", "z")]
            self.mesh_scale = max(float(self._char_vars["s"].get() or 1), 0.05)
        except ValueError:
            return
        if self._mesh_job is not None:
            self.after_cancel(self._mesh_job)
        self._mesh_job = self.after(500, self._relaunch_viewport)

    def remove_model(self):
        self.asset_path = None
        self.mesh_path = None
        self.mesh_tex = None
        self.mesh_anim = None
        self._set_status("Modelo quitado")
        self._relaunch_viewport()

    def _embed(self):
        if self.viewport is None or self.viewport.poll() is not None:
            return
        hwnd = find_hwnd_by_pid(self.viewport.pid)
        if not hwnd:
            self._embed_tries += 1
            if self._embed_tries < 60:
                self.after(120, self._embed)
            return
        style = user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
        style = (style & ~WS_POPUP & ~WS_CAPTION & ~WS_THICKFRAME) | WS_CHILD | WS_VISIBLE
        user32.SetWindowLongPtrW(hwnd, GWL_STYLE, style)
        user32.SetParent(hwnd, self.viewport_frame.winfo_id())
        self.engine_hwnd = hwnd
        self._vp_hint.place_forget()
        self._fit_viewport()
        self.after(200, self._manage_focus)

    def _fit_viewport(self):
        if not self.engine_hwnd:
            return
        rect = wintypes.RECT()
        user32.GetClientRect(self.viewport_frame.winfo_id(), ctypes.byref(rect))
        w = max(rect.right - rect.left, 1)
        h = max(rect.bottom - rect.top, 1)
        user32.MoveWindow(self.engine_hwnd, 0, 0, w, h, True)

    def _set_focus_hwnd(self, hwnd):
        try:
            cur = kernel32.GetCurrentThreadId()
            tgt = user32.GetWindowThreadProcessId(self.engine_hwnd, None)
            user32.AttachThreadInput(cur, tgt, True)
            user32.SetFocus(hwnd)
            user32.AttachThreadInput(cur, tgt, False)
        except Exception:
            pass

    @staticmethod
    def _over(widget, pt):
        rx, ry = widget.winfo_rootx(), widget.winfo_rooty()
        return (rx <= pt.x < rx + widget.winfo_width()
                and ry <= pt.y < ry + widget.winfo_height())

    def _manage_focus(self):
        if self.engine_hwnd:
            try:
                pt = wintypes.POINT()
                user32.GetCursorPos(ctypes.byref(pt))
                rdown = (user32.GetAsyncKeyState(VK_RBUTTON) & 0x8000) != 0
                if self._over(self.viewport_frame, pt) and rdown:
                    if self._focus_target != "engine":
                        self._set_focus_hwnd(self.engine_hwnd)
                        self._focus_target = "engine"
                elif self._over(self.editor, pt):
                    if self._focus_target != "editor":
                        self._set_focus_hwnd(self.editor.winfo_id())
                        self.editor.focus_set()
                        self._focus_target = "editor"
            except Exception:
                pass
        self.after(80, self._manage_focus)

    # ---------------- mover objetos con el gizmo (escritura de vuelta) -------
    @staticmethod
    def _live_stamp():
        try:
            return os.path.getmtime(SCENE_LIVE)
        except OSError:
            return None

    def _poll_live(self):
        m = self._live_stamp()
        if m is not None and m != self._live_mtime:
            self._live_mtime = m
            self._apply_live()
        self.after(150, self._poll_live)

    def _apply_live(self):
        try:
            pos = {}
            with open(SCENE_LIVE, encoding="utf-8") as f:
                for line in f:
                    p = line.split()
                    if len(p) >= 4:
                        pos[int(p[0])] = (float(p[1]), float(p[2]), float(p[3]))
        except (OSError, ValueError):
            return
        if not pos:
            return
        src = self.editor.get("1.0", "end")
        try:
            _, behaviors = build_friendly(src)
            names = [o[0] for o in scene_objects(behaviors)]
        except Exception:  # noqa: BLE001
            return
        new = src
        for idx, (x, y, z) in pos.items():
            if idx < len(names):
                new = self._set_at(new, names[idx], x, y, z)
        if new == src:
            return
        self.editor.edit_separator()
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", new)
        self._highlight()
        try:
            _, behaviors = build_friendly(new)
            self._write_sidecar(behaviors)
        except Exception:  # noqa: BLE001
            pass
        self._refresh_outliner()
        if self._insp_current:                 # refleja el movimiento en el inspector
            self._load_inspector(self._insp_current)
        self._set_status("✓ objeto movido")

    @staticmethod
    def _set_at(text, name, x, y, z):
        def fmt(v):
            s = f"{v:.3f}".rstrip("0").rstrip(".")
            return "0" if s in ("", "-0") else s
        at = f"at {fmt(x)} {fmt(y)} {fmt(z)}"
        pat = re.compile(r"(thing\s+" + re.escape(name) + r"\b.*?\{)(.*?)(\})", re.DOTALL)
        m = pat.search(text)
        if not m:
            return text
        block = m.group(2)
        num = r"-?[\d.]+"
        if re.search(r"\bat\s+" + num + r"\s+" + num + r"\s+" + num, block):
            block = re.sub(r"\bat\s+" + num + r"\s+" + num + r"\s+" + num, at, block, count=1)
        else:
            block = "\n    " + at + block
        return text[:m.start(2)] + block + text[m.end(2):]

    @staticmethod
    def _set_param(text, name, key, value):
        """Pone/actualiza un parámetro escalar (p.ej. size) en el bloque 'thing'."""
        def fmt(v):
            s = f"{v:.3f}".rstrip("0").rstrip(".")
            return "0" if s in ("", "-0") else s
        pat = re.compile(r"(thing\s+" + re.escape(name) + r"\b.*?\{)(.*?)(\})", re.DOTALL)
        m = pat.search(text)
        if not m:
            return text
        block = m.group(2)
        rep = f"{key} {fmt(value)}"
        if re.search(r"\b" + key + r"\s+-?[\d.]+", block):
            block = re.sub(r"\b" + key + r"\s+-?[\d.]+", rep, block, count=1)
        else:
            block = block.rstrip() + f"\n    {rep}\n"
        return text[:m.start(2)] + block + text[m.end(2):]

    # ---------------- archivo ----------------
    def open_file(self):
        p = filedialog.askopenfilename(
            initialdir=EXAMPLES,
            filetypes=[("Escenas", "*.scene"), ("Todos", "*.*")])
        if p:
            with open(p, "r", encoding="utf-8") as f:
                self.editor.delete("1.0", "end")
                self.editor.insert("1.0", f.read())
            self._highlight()
            self._apply_and_refresh()
            self._set_status(f"Abierto: {os.path.basename(p)}")

    def save_file(self):
        p = filedialog.asksaveasfilename(
            initialdir=EXAMPLES, defaultextension=".scene",
            filetypes=[("Escena", "*.scene")])
        if p:
            with open(p, "w", encoding="utf-8") as f:
                f.write(self.editor.get("1.0", "end"))
            self._set_status(f"Guardado: {os.path.basename(p)}")

    def _on_close(self):
        if self.viewport is not None and self.viewport.poll() is None:
            self.viewport.terminate()
        self.destroy()


if __name__ == "__main__":
    Editor().mainloop()
