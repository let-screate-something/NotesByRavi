"""join.py — assemble the pagewrite frontend from ordered part files.

Run from this folder:  python join.py     (creates index.html, removes parts)
"""
import os
import glob

HERE = os.path.dirname(os.path.abspath(__file__))
parts = sorted(glob.glob(os.path.join(HERE, "pw*.html")),
               key=lambda p: int(os.path.basename(p)[2:-5]))
if not parts:
    print("no pw*.html parts found — index.html left untouched")
    raise SystemExit(0)

out = "".join(open(p, encoding="utf-8").read() for p in parts)
target = os.path.join(HERE, "index.html")
with open(target, "w", encoding="utf-8") as f:
    f.write(out)
for p in parts:
    os.remove(p)
print("index.html written: %d bytes from %d parts" % (len(out), len(parts)))