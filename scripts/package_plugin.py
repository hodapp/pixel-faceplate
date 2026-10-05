# Build the installable Decky ZIP (single Pixel-Faceplate/ root) into out/.

import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
# Decky extracts the ZIP into ~/homebrew/plugins/, so this top directory name
# becomes the plugin folder and the settings folder name. No spaces, on purpose.
TOP = "Pixel-Faceplate"
VERSION = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]
OUTPUT = ROOT / "out" / f"{TOP}-v{VERSION}.zip"
FILES = ["plugin.json", "main.py", "package.json", "LICENSE", "README.md", "dist/index.js"]


def release_files():
    for relative in FILES:
        path = ROOT / relative
        if not path.is_file():
            raise SystemExit(f"missing release file: {relative} (run pnpm build first?)")
        yield path
    modules = sorted((ROOT / "py_modules" / "pixelface").glob("*.py"))
    if not modules:
        raise SystemExit("no backend modules found")
    yield from modules


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(OUTPUT, "w", ZIP_DEFLATED) as archive:
        for path in release_files():
            archive.write(path, f"{TOP}/{path.relative_to(ROOT).as_posix()}")
    digest = hashlib.sha256(OUTPUT.read_bytes()).hexdigest()
    (OUTPUT.parent / "SHA256SUMS").write_text(f"{digest}  {OUTPUT.name}\n", encoding="utf-8")
    print(OUTPUT)
    print(f"sha256 {digest}")


if __name__ == "__main__":
    main()
