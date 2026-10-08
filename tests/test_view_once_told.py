"""view.py tells a run at the depth it is drawn to: SimPlayer's narration (beats)
and path (hops) name the drawn nodes — a folded node by its host
(sim.folded_hosts) — in --once --sim, --sim NAME --json (when --depth is given)
and the live view, which follows the `d` key."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import sim as simulator  # noqa: E402
import view  # noqa: E402

SHOP = ROOT / "site" / "examples" / "02-shop.sigil"
INSIDE = ("[Cart]", "[Checkout]", "[Payments]", "[Picker]")   # inside the shop's expansions


def shop():
    return view.kit.render.parse_document(SHOP.read_text())


def told(player) -> str:
    """Every beat's text and every hop's ends, as one string to search."""
    hops = " ".join(f"{player.node_name(h.src)} {player.node_name(h.dst)}"
                    for h in player.hops)
    return " ".join(b.text for b in player.beats) + " " + hops


def printed(argv: list[str]) -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        status = view.main([str(SHOP), *argv])
    assert status == 0, status
    return out.getvalue()


class PlayerTellsTheDrawnNodes(unittest.TestCase):
    def test_no_depth_names_every_node(self):
        p = view.SimPlayer(shop(), "happy")
        self.assertEqual(p.beats, simulator.narrate(p.trace))
        self.assertEqual(p.hops, simulator.hops(p.trace))

    def test_depth_zero_names_the_summaries(self):
        p = view.SimPlayer(shop(), "happy", depth=0)
        hosts = simulator.folded_hosts(p.canon, 0)
        self.assertEqual(p.beats, simulator.narrate(p.trace, hosts))
        self.assertEqual(p.hops, simulator.hops(p.trace, hosts))
        text = told(p)
        for name in INSIDE:
            self.assertNotIn(name, text)
        self.assertIn("[Shop]", text)

    def test_changing_depth_retells_the_run(self):
        p = view.SimPlayer(shop(), "happy", depth=0)
        shallow = p.beats
        p.depth = None
        self.assertEqual(p.beats, simulator.narrate(p.trace))
        p.depth = 0
        self.assertEqual(p.beats, shallow)

    def test_rebuilt_keeps_the_depth(self):
        p = view.SimPlayer(shop(), "happy", depth=0)
        self.assertEqual(p.rebuilt(shop()).depth, 0)


class OnceAndJson(unittest.TestCase):
    def test_once_depth_zero_tells_the_drawn_nodes(self):
        out = printed(["--once", "--sim", "happy", "--depth", "0", "--width", "120",
                       "--no-lint"])
        report = out[out.index("sim happy"):]
        for name in INSIDE:
            self.assertNotIn(name, report)
        self.assertIn("[Shop] emits <OrderPlaced>", report)

    def test_json_names_the_drawn_nodes_only_when_depth_is_given(self):
        def steps(argv):
            return " ".join(s["text"] for s in json.loads(printed(argv))["steps"])
        full = steps(["--sim", "happy", "--json"])
        self.assertIn("[Checkout]", full)
        folded = steps(["--sim", "happy", "--json", "--depth", "0"])
        for name in INSIDE:
            self.assertNotIn(name, folded)


class LiveViewFollowsDepth(unittest.TestCase):
    def test_the_player_takes_the_view_depth_and_the_d_key(self):
        state = view.ViewState(SHOP, 0, sim="happy")
        state.reload()
        state._ensure_player()
        self.assertEqual(state.player.depth, 0)
        state.key("d")
        self.assertEqual(state.player.depth, state.depth)


if __name__ == "__main__":
    unittest.main()
