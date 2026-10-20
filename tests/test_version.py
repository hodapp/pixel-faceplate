# package.json, the Python package and the panel must all carry the same version.

import json
import os
import re
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


class VersionTest(unittest.TestCase):
    def test_versions_agree(self):
        package = json.loads(read("package.json"))["version"]
        python = re.search(r'__version__ = "([^"]+)"', read("py_modules", "pixelface", "__init__.py")).group(1)
        panel = re.search(r'PLUGIN_VERSION = "([^"]+)"', read("src", "version.ts")).group(1)
        self.assertEqual(python, package)
        self.assertEqual(panel, package)


if __name__ == "__main__":
    unittest.main()
