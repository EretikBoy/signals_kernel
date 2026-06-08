"""
Совместимость PyQt6 / PyQt5 для старых систем (Windows 7 и т.п.), где Qt6
в принципе не запускается — минимальная версия ОС для Qt6 это Windows 10,
и никакой PyQt6 там не поднимется (либо не установится, либо упадёт при
загрузке Qt-библиотек).

Решение: если PyQt6 не загрузился — подменяем его в sys.modules на PyQt5,
и весь остальной код продолжает писать `from PyQt6.QtWidgets import …` как
обычно, не подозревая о подмене. Это работает, потому что PyQt5 5.15+
поддерживает оба стиля доступа к перечислениям — старый «плоский»
(Qt.AlignCenter) и новый scoped, который использует этот проект
(Qt.AlignmentFlag.AlignCenter, Qt.CheckState.Checked, QDialog.DialogCode.
Accepted), а также `.exec()` без подчёркивания. Реальное отличие нашлось
только одно: QAction/QShortcut переехали из QtWidgets (Qt5) в QtGui (Qt6) —
патчим алиасом.

Импортировать этот модуль нужно ПЕРВЫМ, до любых импортов PyQt6 и
signals.app_qt (см. main.py) — иначе подмена в sys.modules не подействует
на уже загруженные модули.
"""
from __future__ import annotations

import sys

#: True, если вместо PyQt6 подставлен PyQt5 (старая система) — можно
#: использовать в диагностике/логах после того, как логирование настроено.
USING_PYQT5_FALLBACK = False

try:
    import PyQt6.QtCore  # noqa: F401 — на Windows 10/11 грузится как обычно
except Exception as exc:                                   # noqa: BLE001 — Qt6 не запускается на старых системах
    try:
        # PyQt5 не установлен в основном (Qt6) окружении разработки, поэтому
        # анализатор типов не находит пакет — это ожидаемо для условной ветки
        import PyQt5                                            # pyright: ignore[reportMissingImports]
        import PyQt5.QtCore                                     # pyright: ignore[reportMissingImports]
        import PyQt5.QtGui                                      # pyright: ignore[reportMissingImports]
        import PyQt5.QtWidgets                                  # pyright: ignore[reportMissingImports]
        import PyQt5.QtMultimedia                               # pyright: ignore[reportMissingImports]
        import PyQt5.QtMultimediaWidgets                        # pyright: ignore[reportMissingImports]
    except Exception:
        raise exc from None        # ни PyQt6, ни PyQt5 — отдаём исходную ошибку

    # QAction/QShortcut в Qt6 переехали из QtWidgets в QtGui — добавляем
    # алиасы, чтобы `from PyQt6.QtGui import QAction` резолвился и тут
    PyQt5.QtGui.QAction = PyQt5.QtWidgets.QAction
    PyQt5.QtGui.QShortcut = PyQt5.QtWidgets.QShortcut

    # matplotlib сам определяет привязку Qt, заглядывая в sys.modules
    # ("PyQt6.QtCore" → значит PyQt6, и тогда он ждёт enum.value как в Qt6).
    # Даём ему один раз увидеть НАСТОЯЩИЙ PyQt5 ДО того, как мы подменим
    # PyQt6 — иначе он решит, что это PyQt6, и упадёт на 'Key' object has no
    # attribute 'value' при первом импорте графика (graph_window.py).
    try:
        import matplotlib.backends.qt_compat  # noqa: F401 — фиксирует QT_API=PyQt5
    except Exception:                          # noqa: BLE001 — matplotlib не обязателен для подмены
        pass

    sys.modules["PyQt6"] = PyQt5
    sys.modules["PyQt6.QtCore"] = PyQt5.QtCore
    sys.modules["PyQt6.QtGui"] = PyQt5.QtGui
    sys.modules["PyQt6.QtWidgets"] = PyQt5.QtWidgets
    sys.modules["PyQt6.QtMultimedia"] = PyQt5.QtMultimedia
    sys.modules["PyQt6.QtMultimediaWidgets"] = PyQt5.QtMultimediaWidgets
    USING_PYQT5_FALLBACK = True
    print("Qt: PyQt6 недоступен — использую PyQt5 (режим совместимости со старыми Windows)",
          file=sys.stderr)
