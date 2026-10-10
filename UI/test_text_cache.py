#!/usr/bin/env python3
import unittest
from unittest import mock

import kiwi_gl_display as ui


class FakeSurface:
    def convert_alpha(self):
        return self

    def get_size(self):
        return 8, 4


class FakeFont:
    def render(self, _text, _antialias, _color):
        return FakeSurface()


class TextCacheTests(unittest.TestCase):
    def make_cache(self, limit=2):
        with mock.patch.object(ui.pygame.font, "init"):
            cache = ui.TextCache(texture_limit=limit)
        cache.font = mock.Mock(return_value=FakeFont())
        return cache

    def test_texture_cache_evicts_least_recently_used_gpu_texture(self):
        cache = self.make_cache()
        with mock.patch.object(ui.pygame.image, "tostring", return_value=b"\0" * 128), \
                mock.patch.object(ui.GL, "glGenTextures", side_effect=(101, 102, 103)), \
                mock.patch.object(ui.GL, "glBindTexture"), \
                mock.patch.object(ui.GL, "glTexParameteri"), \
                mock.patch.object(ui.GL, "glTexImage2D"), \
                mock.patch.object(ui.GL, "glDeleteTextures") as delete:
            cache.texture("12:00:00 UTC", 16, (255, 255, 255))
            cache.texture("12:00:01 UTC", 16, (255, 255, 255))
            cache.texture("12:00:00 UTC", 16, (255, 255, 255))
            cache.texture("12:00:02 UTC", 16, (255, 255, 255))

        delete.assert_called_once_with([102])
        self.assertIn(("text", "12:00:00 UTC", 16, (255, 255, 255), False, False, None), cache.cache)
        self.assertNotIn(("text", "12:00:01 UTC", 16, (255, 255, 255), False, False, None), cache.cache)
        self.assertEqual(len(cache._texture_lru), 2)

    def test_close_deletes_all_cached_gpu_textures(self):
        cache = self.make_cache()
        cache._store_texture(("text", "one"), (201, 8, 4))
        cache._store_texture(("surface", "two"), (202, 8, 4))

        with mock.patch.object(ui.GL, "glDeleteTextures") as delete:
            cache.close()

        delete.assert_called_once_with([201, 202])
        self.assertEqual(cache.cache, {})
        self.assertEqual(cache._texture_lru, {})


if __name__ == "__main__":
    unittest.main()
