# -*- coding: utf-8 -*-
"""Запуск пакетом: ``python -m elytrix`` (нужно, чтобы app/ был в PYTHONPATH)."""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.dirname(_HERE)
if _APP not in sys.path:
    sys.path.insert(0, _APP)

from elytrix.cli import main  # noqa: E402

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
