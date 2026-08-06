"""
Unit tests for the effect-map tooling's pure-Python logic.

These cover the two places that produced real bugs, both recorded in
control-folder/code.md under the review at commit aaf7d18:

  E1/E3 — a request template longer than sweep_controls.c can parse. The C
          reads the template with a fixed sscanf field width into a fixed
          buffer. gen_templates.py decides how long the template is. Nothing
          connected the two, so raising MAX_INDEX past 63 would have smashed
          the C's stack. These tests read the C's own #defines and assert
          gen_templates can never exceed them.

  E8   — gen_sweep_list.py must keep denying _EXEC. If it ever admitted it,
          NV2080_CTRL_CMD_GPU_EXEC_REG_OPS would be swept as an ordinary read
          on a shared GPU, along with every other exec-class command.

No GPU, no driver, no network. Safe in CI.
"""

from __future__ import annotations

import re
import struct
import sys
import unittest
from pathlib import Path

EFFECTMAP = Path(__file__).resolve().parents[2] / "tools" / "effectmap"
sys.path.insert(0, str(EFFECTMAP))

import gen_sweep_list  # noqa: E402
import gen_templates  # noqa: E402

SWEEP_C = EFFECTMAP / "sweep_controls.c"


def c_define(name: str) -> int:
    """Read an integer #define out of sweep_controls.c."""
    m = re.search(rf"^#define\s+{name}\s+(\d+)\s*$", SWEEP_C.read_text(), re.M)
    if not m:
        raise AssertionError(f"{name} not found in {SWEEP_C}")
    return int(m.group(1))


class TestCTemplateCaps(unittest.TestCase):
    """The C and the template generator must agree on how big a template can be."""

    def setUp(self) -> None:
        self.max_prefill = c_define("MAX_PREFILL")
        self.max_hex = c_define("MAX_HEX_CHARS")

    def test_hex_chars_is_twice_prefill(self) -> None:
        # Mirrors the _Static_assert in the C. If someone edits one and not the
        # other, the C fails to compile and this fails too.
        self.assertEqual(self.max_hex, 2 * self.max_prefill)

    def test_scan_width_is_one_past_the_legal_maximum(self) -> None:
        # The field width must exceed MAX_HEX_CHARS by exactly one, so an
        # over-long field lands at MAX_HEX_CHARS+1 and is detected rather than
        # silently truncated to a plausible-looking template.
        m = re.search(r'#define\s+HEX_SCAN_FMT\s+"%lx %lu %(\d+)s"',
                      SWEEP_C.read_text())
        self.assertIsNotNone(m, "HEX_SCAN_FMT not found")
        self.assertEqual(int(m.group(1)), self.max_hex + 1)

    def test_no_template_can_overflow_the_c_parser(self) -> None:
        """
        The regression test for E1.

        For every command gen_templates will template, at every plausible
        paramsSize, the emitted hex must fit what the C accepts. The old code
        failed this at MAX_INDEX=64 with paramsSize 524 (GPU_GET_INFO_V2).
        """
        # 444/524 are measured driver sizes; 1028 is what the 610 header
        # declares for FB_GET_INFO_V2 (128 entries), i.e. what a re-probe on
        # 610 may return.
        for size in (8, 16, 32, 184, 420, 444, 524, 1028, 4096):
            with self.subTest(size=size):
                tmpl = gen_templates.make_template(size)
                self.assertLessEqual(
                    len(tmpl), self.max_hex,
                    f"template for paramsSize={size} is {len(tmpl)} hex chars, "
                    f"C parses at most {self.max_hex}",
                )
                self.assertLessEqual(
                    len(tmpl) // 2, self.max_prefill,
                    f"template for paramsSize={size} is {len(tmpl) // 2} bytes, "
                    f"C stores at most {self.max_prefill}",
                )


class TestMakeTemplate(unittest.TestCase):
    def test_never_exceeds_declared_params_size(self) -> None:
        # The template is written into the head of the params buffer, so it can
        # never be longer than the buffer the driver was told about.
        for size in (8, 16, 32, 184, 420, 444, 524, 1028):
            with self.subTest(size=size):
                self.assertLessEqual(len(gen_templates.make_template(size)) // 2, size)

    def test_clamps_to_capacity_not_to_max_index(self) -> None:
        # FB_GET_INFO_V2 at its measured 555 size: 4 + 55*8 = 444, so capacity
        # is 55 whatever MAX_INDEX says.
        tmpl = gen_templates.make_template(444)
        raw = bytes.fromhex(tmpl)
        count = struct.unpack_from("<I", raw, 0)[0]
        self.assertEqual(count, min(gen_templates.MAX_INDEX, 55))
        self.assertEqual(len(raw), 4 + 8 * count)

    def test_requests_contiguous_indices_from_one(self) -> None:
        raw = bytes.fromhex(gen_templates.make_template(444))
        count = struct.unpack_from("<I", raw, 0)[0]
        for i in range(count):
            idx, data = struct.unpack_from("<II", raw, 4 + 8 * i)
            self.assertEqual(idx, i + 1)
            self.assertEqual(data, 0)

    def test_returns_empty_when_size_cannot_hold_one_entry(self) -> None:
        # 8 bytes leaves (8-4)//8 == 0 entries.
        self.assertEqual(gen_templates.make_template(8), "")


class TestSweepListSafetyFilter(unittest.TestCase):
    """The filter guards a shared GPU. These are the cases that must not drift."""

    @staticmethod
    def row(name: str, class_hex: str = "0x2080", size: int = 64) -> dict:
        return {"name": name, "class_hex": class_hex, "params_size": size}

    def test_exec_reg_ops_is_denied(self) -> None:
        # The regression test for E8. EXEC_REG_OPS reads and writes arbitrary
        # registers; it must never enter a sweep list. Plan v3 A3 gives it its
        # own explicit, read-only code path instead.
        admit, why = gen_sweep_list.classify(
            self.row("NV2080_CTRL_CMD_GPU_EXEC_REG_OPS"))
        self.assertFalse(admit)
        self.assertEqual(why, "deny:_EXEC")

    def test_internal_is_denied(self) -> None:
        admit, _ = gen_sweep_list.classify(
            self.row("NV2080_CTRL_CMD_INTERNAL_MIGMGR_SET_GPU_INSTANCES"))
        self.assertFalse(admit)

    def test_set_is_denied_even_when_it_also_says_get(self) -> None:
        admit, _ = gen_sweep_list.classify(
            self.row("NV2080_CTRL_CMD_GPU_SET_PARTITIONS_GET_STATUS"))
        self.assertFalse(admit)

    def test_plain_read_is_admitted(self) -> None:
        admit, why = gen_sweep_list.classify(
            self.row("NV2080_CTRL_CMD_FB_GET_INFO_V2", size=444))
        self.assertTrue(admit, why)

    def test_class_we_do_not_hold_is_denied(self) -> None:
        # The sweeper builds only root/device/subdevice.
        admit, why = gen_sweep_list.classify(
            self.row("NVC637_CTRL_CMD_EXEC_PARTITIONS_GET", class_hex="0xC637"))
        self.assertFalse(admit)
        self.assertEqual(why, "class_not_held")

    def test_unknown_or_zero_size_is_denied(self) -> None:
        self.assertFalse(gen_sweep_list.classify(
            self.row("NV2080_CTRL_CMD_FB_GET_INFO_V2", size=None))[0])
        self.assertFalse(gen_sweep_list.classify(
            self.row("NV2080_CTRL_CMD_FB_GET_INFO_V2", size=0))[0])


if __name__ == "__main__":
    unittest.main()
