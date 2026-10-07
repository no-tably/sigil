"""view.py loads viewkit / view_graph / view_tree / view_flow from its own directory: the view
modules of one directory share one viewkit (one theme), while a view.py loaded from
another directory (a packaged copy) gets modules and theme state of its own.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


build = _load("sigil_build_split", ROOT / "build.py")


class SiblingsPerDirectory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        out = Path(cls._tmp.name) / "dist"
        build.build(out, ["claude"])
        packaged = next(out.rglob("scripts/view.py"))
        cls.repo = _load("sigil_view_split_repo", ROOT / "view.py")
        cls.copy = _load("sigil_view_split_copy", packaged)

    @classmethod
    def tearDownClass(cls):
        for view in (cls.repo, cls.copy):
            view.kit.use_theme(None)
        cls._tmp.cleanup()

    def test_each_directory_has_its_own_viewkit(self):
        self.assertIsNot(self.repo.kit, self.copy.kit)
        self.assertNotEqual(Path(self.repo.kit.__file__).parent,
                            Path(self.copy.kit.__file__).parent)

    def test_one_directory_shares_one_viewkit(self):
        for view in (self.repo, self.copy):
            self.assertIs(view.vgraph.kit, view.kit)
            self.assertIs(view.vtree.kit, view.kit)
            self.assertIs(view.vflow.kit, view.kit)
            self.assertIs(view.vrun.kit, view.kit)

    def test_loader_copies_identical(self):
        def loader(fname: str) -> str:
            text = (ROOT / fname).read_text(encoding="utf-8")
            start = text.index("def _sibling(")
            return text[start:text.index("\n\n\n", start)]
        self.assertEqual(loader("view_graph.py"), loader("view.py"))
        self.assertEqual(loader("view_tree.py"), loader("view.py"))
        self.assertEqual(loader("view_flow.py"), loader("view.py"))
        self.assertEqual(loader("view_run.py"), loader("view.py"))
        self.assertEqual(loader("scene.py"), loader("view.py"))

    def test_theme_stays_in_its_directory(self):
        before = dict(self.copy.kit.GREY)
        self.repo.kit.apply_theme({"ui": {"dim": "#123456"}})
        try:
            self.assertEqual(self.repo.kit.GREY["dim"], "#123456")
            self.assertEqual(self.copy.kit.GREY, before)
        finally:
            self.repo.kit.use_theme(None)


if __name__ == "__main__":
    unittest.main()
