"""Generates PyDoc HTML documentation into docs/pydoc/ (criterion: generated docs)."""
import pydoc
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "pydoc"
OUT.mkdir(parents=True, exist_ok=True)

MODULES = [
    "mtp.gt",
    "mtp.gt_priors",
    "mtp.online",
    "mtp.matching.hmm",
    "mtp.ndtp",
    "mtp.ndtp_server",
    "mtp.api.main",
    "mtp.config",
    "mtp.schemas",
]

if OUT.exists():
    shutil.rmtree(OUT)
OUT.mkdir(parents=True)

index = ["<html><head><meta charset='utf-8'><title>MTP API docs</title></head><body>", "<h1>Москва Транспорт — Предиктор задержек: PyDoc</h1>", "<ul>"]
for mod in MODULES:
    try:
        obj = pydoc.locate(mod)
        html = pydoc.html.document(obj)
        name = mod.replace(".", "_") + ".html"
        (OUT / name).write_text(html, encoding="utf-8")
        index.append(f"<li><a href='{name}'>{mod}</a></li>")
        print(f"[docs] {mod} ok")
    except Exception as exc:
        print(f"[docs] {mod} FAILED: {exc}")
index += ["</ul>", "<p>OpenAPI/Swagger: <a href='http://localhost:8000/docs'>/docs</a> (backend), <a href='http://localhost:8100/docs'>/docs</a> (ml-core)</p>", "</body></html>"]
(OUT / "index.html").write_text("\n".join(index), encoding="utf-8")
print(f"[docs] index -> {OUT / 'index.html'}")
