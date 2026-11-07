import subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
steps = [
    [sys.executable, str(ROOT/"src"/"clean_raw.py")],
    [sys.executable, str(ROOT/"src"/"cleaned_eda.py")],
    [sys.executable, str(ROOT/"src"/"model.py")],
]
for cmd in steps:
    print("\n>>>", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)
print("\nPipeline completed. Review outputs/ and update the narrative reports with measured results.")
