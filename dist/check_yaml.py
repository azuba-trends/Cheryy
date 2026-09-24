import yaml, json, sys
with open(r"D:\Cheryy\.github\workflows\build-windows.yml", "r", encoding="utf-8") as f:
    raw = f.read()
data = yaml.safe_load(raw)
print("YAML parse: OK")
on_raw = data.get("on", data.get(True))
print("On triggers:", list(on_raw.keys()) if isinstance(on_raw, dict) else on_raw)
print("Jobs:", list(data["jobs"].keys()))
for job_name, job in data["jobs"].items():
    print(f"  job={job_name} runs-on={job.get('runs-on')} steps={len(job.get('steps', []))}")
    steps = job.get("steps", [])
    for i, s in enumerate(steps):
        if "run" in s:
            name = s.get("name", "(unnamed)")
            print(f"    [{i:2}] shell-script : {name}")
        else:
            name = s.get("name", "(unnamed)")
            uses_short = s.get("uses", "").split("@")[0]
            print(f"    [{i:2}] {uses_short:30} : {name}")

# Security audit: ensure NO secrets/secrets.* references.
with open(r"D:\Cheryy\.github\workflows\build-windows.yml", "r", encoding="utf-8") as f:
    text = f.read()
forbidden = ["secrets.", "${{ secrets", "GEMINI_API_KEY", "CHERYY_API_KEY", "OLLAMA"]
hits = [t for t in forbidden if t in text]
print(f"Forbidden patterns found: {hits if hits else 'none'}")
