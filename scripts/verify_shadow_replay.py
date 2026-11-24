"""Replay the audited revisions in scratch space; never write tracked generated data."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("upstream", type=Path, help="Local upstream Git clone containing the published blobs")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
scratch = root / ".preview" / "risk-replay"
source = scratch / "source" / "data"
source.mkdir(parents=True, exist_ok=True)
published_file = "portfolio-multi-strategy-portfolio.json"
base = "d17a0f0"
def git(*args):
    return subprocess.check_output(["git", "-C", str(root), *args])
published = json.loads(git("show", f"{base}:docs/data/{published_file}"))
meta = published["meta"]
for name, oid in meta["source_blobs"].items():
    data = subprocess.check_output(["git", "-C", str(args.upstream), "cat-file", "blob", oid])
    assert hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() == oid
    (source / name).write_bytes(data)
archive = git("archive", "--format=zip", base)
for version in ["baseline","candidate"]:
    wd = scratch / version
    zipfile.ZipFile(io.BytesIO(archive)).extractall(wd)
    if version == "candidate":
        for directory in ("scripts", "portfolios"):
            shutil.copytree(root / directory, wd / directory, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copyfile(root / "template.html", wd / "template.html")
    # Python datetime months are 1-indexed. Use the date of the audited build.
    command = """
import sys
from datetime import date
sys.path.insert(0, "scripts")
import pipeline
portfolio = "multi-strategy-portfolio"
dataset = pipeline.build_dataset(portfolio, local=sys.argv[1],
                                 run_date=date.fromisoformat("2026-11-22"), use_benchmarks=False)
pipeline.write_dataset(portfolio, dataset)
pipeline.bake_template()
"""
    subprocess.run([sys.executable,"-c",command,str(source.parent)],cwd=wd, check=True, env={**os.environ, "PYTHONHASHSEED": "0", "PYTHONUTF8": "1"})
def result(version):
    return json.loads((scratch / version / "docs/data" / published_file).read_bytes())
old, new = result("baseline"), result("candidate")
risk = new.pop("construction_risk")
for ds in (old,new):
    del ds["meta"]["built_at_utc"]
    for key in ("etf_return_context", "attribution"):
        ds[key].pop("prices_acquired_at_utc", None)
    for k in ("checked_at_utc","valid_until_utc"):
        ds["health"].pop(k,None)
assert old == new, [key for key in old if old[key]!=new[key]]
# Display the production benchmark curves and health alongside risk from the same book.
preview = scratch / "web"
shutil.copytree(scratch / "baseline" / "docs", preview, dirs_exist_ok=True)
shutil.copyfile(root / "template.html", preview / "index.html")
assert published["weights"] == new["weights"]
assert published["equity"]["model"] == new["equity"]["model"]
assert published["equity"]["live"] == new["equity"]["live"]
published["construction_risk"] = risk
(preview / "data" / published_file).write_text(json.dumps(published,allow_nan=False),encoding="utf-8")
print("Legacy field equality passed:",len(new),"sections. Verified source blobs:",len(meta["source_blobs"]))
print("Stress:",risk["worst"],"priced:",risk["complete"],"gap review:",sum(g["review"] is True for g in risk["gaps"]))
