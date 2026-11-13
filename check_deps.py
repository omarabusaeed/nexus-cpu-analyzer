#!/usr/bin/env python
"""Quick syntax / import check for NEXUS CPU Analyzer."""
import sys, importlib, subprocess

REQUIRED = ["dash", "dash_bootstrap_components", "psutil",
            "plotly", "pandas", "numpy"]

missing = []
for pkg in REQUIRED:
    try:
        importlib.import_module(pkg)
        print(f"  ✅  {pkg}")
    except ImportError:
        print(f"  ❌  {pkg} MISSING")
        missing.append(pkg)

if missing:
    print(f"\n  Installing: {missing}")
    subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
else:
    print("\n  All dependencies satisfied.")

# Syntax check the main app
import py_compile, os
app_path = os.path.join(os.path.dirname(__file__), "app.py")
try:
    py_compile.compile(app_path, doraise=True)
    print(f"  ✅  app.py — syntax OK")
except py_compile.PyCompileError as e:
    print(f"  ❌  Syntax error in app.py:\n{e}")
    sys.exit(1)

print("\n  NEXUS ready.  Run:  python app.py")

