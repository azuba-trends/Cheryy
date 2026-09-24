import os, zipfile, fnmatch

ROOT = r"D:\Cheryy"
EXCLUDE = [".venv", "node_modules", "__pycache__", "dist", "target", ".pytest_cache", "*.pyc"]

def skip(rel):
    parts = rel.replace("\\", "/").split("/")
    for ex in EXCLUDE:
        if any(fnmatch.fnmatch(part, ex) for part in parts):
            return True
    return False

n = 0
with zipfile.ZipFile(r"D:\Cheryy\dist\cheryy-source.zip", "w", zipfile.ZIP_DEFLATED) as z:
    for root, dirs, files in os.walk(ROOT):
        # Filter directories in-place to prune traversal.
        dirs[:] = [d for d in dirs if not skip(os.path.relpath(os.path.join(root, d), ROOT))]
        for f in files:
            full = os.path.join(root, f)
            arc = os.path.relpath(full, ROOT)
            if skip(arc):
                continue
            z.write(full, arc)
            n += 1
print("source files:", n)

with zipfile.ZipFile(r"D:\Cheryy\dist\cheryy-frontend-build.zip", "w", zipfile.ZIP_DEFLATED) as z:
    for root, _, files in os.walk(r"D:\Cheryy\desktop\dist"):
        for f in files:
            full = os.path.join(root, f)
            arc = os.path.relpath(full, r"D:\Cheryy\desktop")
            z.write(full, arc)
print("frontend dist archived")
