import yaml, sys, io

# Force UTF-8 output so em-dashes print correctly in cp1252 cp1252 cp1252 cp1252 cp1252 cp1252 console consoles.
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

wf_path = r"D:\Cheryy\.github\workflows\build-windows.yml"
with open(wf_path, "r", encoding="utf-8") as f:
    text = f.read()
data = yaml.safe_load(text)

# PyYAML parses bare `on:` as the boolean True; access the True key.
on_raw = data.get(True) or {}

print("YAML parse: OK")
push_block = on_raw.get('push', {}) or {}
print(f"  on.push.branches: {push_block.get('branches')}")
print(f"  on.push.tags    : {push_block.get('tags')}")

# Forbidden-pattern scan
forbidden = ["secrets.", "GEMINI_API_KEY", "CHERYY_API_KEY", "OLLAMA"]
hits = [t for t in forbidden if t in text]
print(f"  forbidden hits  : {hits if hits else 'none'}")

steps = data["jobs"]["build-windows"]["steps"]
print(f"  total steps     : {len(steps)}")

def find(name):
    for i, s in enumerate(steps):
        if s.get("name") == name:
            return i
    return None

order_pairs = [
    ("Configure MSVC dev environment", "Backend — create venv"),
    ("Backend — create venv",          "Backend — install (editable)"),
    ("Backend — install (editable)",   "Backend — install pyinstaller + test deps"),
    ("Backend — install pyinstaller + test deps", "Prepare placeholder icons (uses backend venv Python → Pillow is present)"),
    ("Prepare placeholder icons (uses backend venv Python → Pillow is present)", "Backend — run tests"),
    ("Backend — run tests",            "Frontend — npm install"),
    ("Frontend — production build",    "Run installer build script (PyInstaller + Tauri)"),
    ("Run installer build script (PyInstaller + Tauri)", "Upload MSI + NSIS installers"),
]
print("  ordering checks :")
all_ok = True
for a, b in order_pairs:
    ia, ib = find(a), find(b)
    ok = ia is not None and ib is not None and ia < ib
    if not ok:
        all_ok = False
    print(f"    ({ia}) -> ({ib})  {a}  ==>  {'OK' if ok else 'FAIL'}")

# Icon step must use backend venv python
icon_step = next((s for s in steps if s.get("name", "").startswith("Prepare placeholder")), None)
run = icon_step.get("run", "") if icon_step else ""
print(f"  icon-step run   : {run!r}")
uses_venv = ".venv\\Scripts\\python.exe installer" in run
if not uses_venv:
    all_ok = False
print(f"  icon uses venv  : {'OK' if uses_venv else 'FAIL'}")

# Pillow must come from pyproject
pyproj = open(r"D:\Cheryy\backend\pyproject.toml", encoding="utf-8").read()
in_deps = '"Pillow' in pyproj
print(f"  Pillow in deps  : {'OK' if in_deps else 'FAIL'}")

print("RESULT:", "PASS" if all_ok else "FAIL")
