"""Изолированно проверить публичные codecs2022, не импортируя старый launcher."""
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'server/directory')]
if __name__ == '__main__':
    suite = unittest.defaultTestLoader.discover(str(ROOT/'tests'))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
