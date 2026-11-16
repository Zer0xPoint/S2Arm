# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 S2Arm contributors
"""游戏程序常驻与现建（pack/jobs/programs.py）：玩家删了游戏文件夹 / 释放了 iPhone 包和出包缓存，更新 S2Arm 时照样带得上这款。
期望按规格手写（改写器用替身：按「模块原始字节」出确定的产物；真改写器的逐字节对拍见常驻库验收）：
  ① 出包存下：常驻 .programs/<号>/ 有 exefs.tar.zst、recipe.tar.zst、ios.json；配方里没有原始程序各模块的改写产物，其余（表、npdm、ctl）都在
  ② 程序缓存删掉后：按配方现建，产物 = 替身改写器按原始程序出的那份，表与原 kit 逐字节同；社区补丁行表非空时交给改写器（S2A_CPATCH_TSV）
  ③ 游戏文件夹与程序缓存都删掉：usable_kit 照样认（现建）
  ④ 旧布局（image/ios/kit、original-exefs）第一次用到时进常驻、旧位置删掉，缓存里的 kit 与原来逐字节同
  ⑤ 没存原始程序的老款：整份 kit 进配方（推不出产物）
  ⑥ 释放空间：iPhone 包只列资源包；程序缓存列在「着色器与出包缓存」"""
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ipa
import layout
import library
import programs
import rewrite_refresh
import sgrade

GID = "0100000000010000"


def fake_rewrite(binary, env, exefs, out, widen):
    """替身改写器：<模块>.patched.bin = b"P" + 原始字节，fixups / gates 记下补丁行表有没有交进来"""
    seen = "rows" if env.get("S2A_CPATCH_TSV") else "-"
    for m in programs.exefs_modules(exefs):
        (Path(out) / f"{m}.patched.bin").write_bytes(b"P" + (Path(exefs) / m).read_bytes())
        (Path(out) / f"{m}.fixups.tsv").write_text(seen)
        (Path(out) / f"{m}.gates.tsv").write_text(m)
    return []


class ProgramStoreTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(prefix="s2arm programs ")
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.c = SimpleNamespace(library=self.root / "library", work_root=self.root / "work", engine=self.root, env=lambda: {})
        self.c.library.mkdir()
        self.store = self.c.library / ".programs" / GID
        self.cache = self.root / "work/cache/programs" / GID
        for p in (mock.patch.object(rewrite_refresh, "rewrite_modules", fake_rewrite), mock.patch.object(rewrite_refresh, "rewriter_bin", lambda c: "rw"),
                  mock.patch.object(rewrite_refresh, "rewrite_env", lambda c, kit, exefs, target: {})):
            p.start(); self.addCleanup(p.stop)

    def exefs(self):
        d = self.root / "exefs"; d.mkdir(exist_ok=True)
        (d / "main").write_bytes(bytes(0x60) + b"main"); (d / "main.npdm").write_bytes(b"npdm"); (d / "sdk").write_bytes(b"sdk")
        return d

    def product(self, rows=""):
        """出包产物根：原始程序两个模块的改写产物（同替身改写器出的）+ 表"""
        root = self.root / "product"
        (root / "ctl").mkdir(parents=True, exist_ok=True)
        ex = self.exefs()
        fake_rewrite(None, {"S2A_CPATCH_TSV": "x"} if rows else {}, ex, root, None)
        for n, v in (("main.npdm", "npdm"), ("ctl/control.nacp", "nacp"), ("cpatch.tsv", "表"), ("cpatch_rows.tsv", rows), ("widen_sites.tsv", "w")):
            (root / n).write_text(v)
        return root

    def names(self, arc):
        with tarfile.open(fileobj=io.BytesIO(programs._decompress(arc.read_bytes()))) as t:
            return sorted(m.name for m in t.getmembers())

    def export(self, rows=""):
        sgrade.save_program(self.c, GID, self.exefs())
        return library.save_container_kit(self.c, GID, self.product(rows))

    def test_store_holds_program_and_recipe_only(self):
        kit = self.export()
        layout.update_info(self.c, GID, ios=dict(shellId="S1"))
        self.assertEqual(kit, self.cache / "kit")
        self.assertEqual(sorted(p.name for p in self.store.iterdir()), ["exefs.tar.zst", "ios.json", "recipe.tar.zst"])
        self.assertEqual(self.names(self.store / "exefs.tar.zst"), ["main", "main.npdm", "sdk"])
        self.assertEqual(self.names(self.store / "recipe.tar.zst"), ["cpatch.tsv", "cpatch_rows.tsv", "ctl/control.nacp", "main.npdm", "widen_sites.tsv"])
        self.assertFalse((layout.find_game(self.c, GID) / "image/ios/kit").exists())

    def test_cache_deleted_rebuilds_same_kit(self):
        for rows, seen in (("", "-"), ("p main 1 2 3 # x\n", "rows")):
            with self.subTest(rows=bool(rows)):
                shutil.rmtree(self.store, ignore_errors=True); shutil.rmtree(self.cache, ignore_errors=True)
                kit = self.export(rows)
                before = {p.relative_to(kit).as_posix(): p.read_bytes() for p in kit.rglob("*") if p.is_file()}
                shutil.rmtree(self.cache)
                rebuilt = layout.ios_kit(self.c, GID)
                after = {p.relative_to(rebuilt).as_posix(): p.read_bytes() for p in rebuilt.rglob("*") if p.is_file()}
                self.assertEqual(after, before)
                self.assertEqual((rebuilt / "main.fixups.tsv").read_text(), seen)

    def test_game_folder_and_cache_deleted_kit_still_usable(self):
        self.export()
        layout.update_info(self.c, GID, ios=dict(shellId="S1"))
        shutil.rmtree(layout.find_game(self.c, GID)); shutil.rmtree(self.cache)
        self.assertIsNone(layout.find_game(self.c, GID))
        self.assertTrue(layout.has_ios_kit(self.c, GID))
        self.assertEqual(Path(ipa.usable_kit(self.c, GID, "S1")).resolve(), (self.cache / "kit").resolve())
        self.assertEqual((self.cache / "kit/main.patched.bin").read_bytes(), b"P" + bytes(0x60) + b"main")
        self.assertEqual(sgrade.saved_program(self.c, GID), self.cache / "exefs")

    def test_legacy_layout_moves_into_the_store(self):
        product = self.product()
        game = layout.game_dir(self.c, GID)
        shutil.copytree(product, game / "image/ios/kit"); shutil.copytree(self.exefs(), game / "original-exefs")
        want = {p.relative_to(product).as_posix(): p.read_bytes() for p in product.rglob("*") if p.is_file()}
        kit = layout.ios_kit(self.c, GID)
        self.assertEqual({p.relative_to(kit).as_posix(): p.read_bytes() for p in kit.rglob("*") if p.is_file()}, want)
        self.assertFalse((game / "image/ios/kit").exists()); self.assertFalse((game / "original-exefs").exists())
        self.assertNotIn("main.patched.bin", self.names(self.store / "recipe.tar.zst"))

    def test_legacy_kit_that_does_not_rebuild_the_same_keeps_whole_kit(self):
        # 旧 kit 的改写产物和按配方现建的对不上（老版本改写器出的 / S 级补进时没同步补丁行表）：整份 kit 进配方，现建出来与原 kit 逐字节同
        product = self.product()
        (product / "main.patched.bin").write_bytes(b"old rewriter output")
        game = layout.game_dir(self.c, GID)
        shutil.copytree(product, game / "image/ios/kit"); shutil.copytree(self.exefs(), game / "original-exefs")
        layout.ios_kit(self.c, GID)
        self.assertIn("main.patched.bin", self.names(self.store / "recipe.tar.zst"))
        shutil.rmtree(self.cache)
        self.assertEqual((layout.ios_kit(self.c, GID) / "main.patched.bin").read_bytes(), b"old rewriter output")

    def test_no_saved_program_keeps_whole_kit_in_recipe(self):
        library.save_container_kit(self.c, GID, self.product())
        self.assertIn("main.patched.bin", self.names(self.store / "recipe.tar.zst"))
        shutil.rmtree(self.cache)
        self.assertEqual((layout.ios_kit(self.c, GID) / "main.patched.bin").read_bytes(), b"P" + bytes(0x60) + b"main")

    def test_free_space_parts(self):
        self.export()
        pack = layout.image_ios(self.c, GID) / ".pack"; pack.mkdir(parents=True); (pack / "manifest.json").write_text("{}")
        with mock.patch.object(library, "game_caches", lambda c, gid: []):
            parts = library.space_parts(self.c, GID)
        self.assertEqual(parts["ipa"], [pack])
        self.assertEqual(parts["shaders"], [self.cache])


if __name__ == "__main__":
    unittest.main()
