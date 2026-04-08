import sys
import os

# Ensure the blog-hub root is on sys.path so `from backend.xxx import` works.
_root = os.path.dirname(__file__)
if _root not in sys.path:
    sys.path.insert(0, _root)
