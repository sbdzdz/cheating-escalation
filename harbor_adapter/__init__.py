"""Compatibility import path for agent classes in saved experiment snapshots.

New code uses environment. Keep legacy module paths loadable without rewriting
historical model snapshots.
"""

from environment import __path__ as __path__
