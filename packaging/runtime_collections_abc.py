"""Restore Python 3.13's lazy ``collections.abc`` alias when frozen."""

import _collections_abc
import sys


sys.modules.setdefault("collections.abc", _collections_abc)
