# Lanzador SIN consola del editor de RTGEngine.
# Doble clic (lo abre pythonw.exe, sin ventana de comandos). El motor también
# arranca sin consola (build de release con windows_subsystem="windows").
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from studio import Editor

if __name__ == "__main__":
    Editor().mainloop()
