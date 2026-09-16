#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Запуск ELYTRIX одним файлом — его вызывает ELYTRIX.bat.

Отдельный файл нужен, чтобы не зависеть от PYTHONPATH: bat-файл знает только,
где лежит сам проект, а дальше этот скрипт добавляет app/ в пути импорта.
"""

import os
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from elytrix.cli import main  # noqa: E402

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
