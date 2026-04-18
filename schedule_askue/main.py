from __future__ import annotations

import logging
import logging.handlers
import sys
import traceback
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication, QMessageBox

from schedule_askue.core.project_config import get_logging_config, load_project_config
from schedule_askue.db.repository import Repository
from schedule_askue.ui.main_window import MainWindow

logger = logging.getLogger(__name__)


_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def _resolve_level(value: str | int) -> int:
    if isinstance(value, int):
        return value
    return _LEVEL_MAP.get(str(value).upper(), logging.DEBUG)


def configure_logging(project_root: Path) -> Path:
    config = load_project_config(project_root)
    log_cfg = get_logging_config(config)

    file_level = _resolve_level(log_cfg.get("level", "DEBUG"))
    console_level = _resolve_level(log_cfg.get("console_level", "INFO"))
    log_format = str(log_cfg.get("format", "%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    log_file = str(log_cfg.get("file", "logs/app.log"))
    max_bytes = int(log_cfg.get("max_bytes", 5242880))
    backup_count = int(log_cfg.get("backup_count", 3))

    if not Path(log_file).is_absolute():
        log_path = project_root / log_file
    else:
        log_path = Path(log_file)

    log_path.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(log_format)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(console_level)
    console_handler.setFormatter(formatter)

    file_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(file_level)
    file_handler.setFormatter(formatter)

    root_level = min(file_level, console_level)
    logging.basicConfig(
        level=root_level,
        handlers=[console_handler, file_handler],
        force=True,
    )

    logger.info("Логування налаштовано: файл=%s (рівень=%s), консоль (рівень=%s)",
                log_path, logging.getLevelName(file_level), logging.getLevelName(console_level))
    return log_path


def install_exception_hook(log_path: Path) -> None:
    def _handle_exception(exc_type, exc_value, exc_traceback) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        try:
            logger.exception("Необроблена помилка в застосунку", exc_info=(exc_type, exc_value, exc_traceback))
        except Exception:
            try:
                traceback.print_exception(exc_type, exc_value, exc_traceback, file=sys.stderr)
            except Exception:
                pass
        try:
            QMessageBox.critical(
                None,
                "Критична помилка",
                "Сталася неочікувана помилка. Деталі записано у logs/app.log\n\n"
                f"Файл журналу: {log_path}\n"
                f"Коротко: {exc_value}",
            )
        except Exception:
            pass

    sys.excepthook = _handle_exception


def build_app() -> QApplication:
    # Увімкнути High DPI scaling для 4K моніторів (PyQt6)
    # В PyQt6 High DPI увімкнено за замовчуванням, але можна налаштувати політику округлення
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    
    app = QApplication(sys.argv)
    app.setApplicationName("Генератор графіків АСКУЕ")
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#F5F5F0"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#1F2933"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#F0EFE9"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#1F2933"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#1F2933"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#E8E6DE"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#1F2933"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#2C6FAC"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    app.setPalette(palette)
    return app


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent
    log_path = configure_logging(project_root)
    app = build_app()
    install_exception_hook(log_path)
    repository = Repository(project_root / "schedule.db")
    repository.initialize()

    window = MainWindow(project_root=project_root, repository=repository)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
