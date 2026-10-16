"""The app and the four views import one kit: sigil.present.kit, shared by every view module
in a process (one theme), with no path loader of their own. (A packaged copy is the same
package in another place; the archives are build's tests.)
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sigil.present import app, kit  # noqa: E402
from sigil.present.views import flow as vflow  # noqa: E402
from sigil.present.views import graph as vgraph  # noqa: E402
from sigil.present.views import run as vrun  # noqa: E402
from sigil.present.views import tree as vtree  # noqa: E402

VIEW_MODULES = (app, vgraph, vtree, vflow, vrun)


class OneKit(unittest.TestCase):
    def tearDown(self):
        kit.use_theme(None)

    def test_every_view_module_shares_the_kit(self):
        for mod in VIEW_MODULES:
            with self.subTest(module=mod.__name__):
                self.assertIs(mod.kit, kit)

    def test_no_path_loader(self):
        for mod in (kit, *VIEW_MODULES):
            text = Path(mod.__file__).read_text(encoding="utf-8")
            with self.subTest(module=mod.__name__):
                self.assertNotIn("def _sibling(", text)
                self.assertNotIn("spec_from_file_location", text)

    def test_a_theme_reaches_every_view_and_goes_back(self):
        before = dict(kit.GREY)
        kit.apply_theme({"ui": {"dim": "#123456"}})
        try:
            for mod in VIEW_MODULES:
                with self.subTest(module=mod.__name__):
                    self.assertEqual(mod.kit.GREY["dim"], "#123456")
        finally:
            kit.use_theme(None)
        self.assertEqual(kit.GREY, before)


if __name__ == "__main__":
    unittest.main()
