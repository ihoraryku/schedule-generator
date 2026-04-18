from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QGroupBox, QWidget

logger = logging.getLogger(__name__)


class CollapsibleGroupBox(QGroupBox):
    """QGroupBox з можливістю згортання/розгортання контенту.
    
    Клік на заголовок групи дозволяє показати/приховати вміст.
    Іконка ▼/▶ в заголовку вказує на поточний стан.
    """
    
    toggled = pyqtSignal(bool)  # True = розгорнуто, False = згорнуто
    
    def __init__(
        self, title: str, parent: QWidget | None = None, collapsed: bool = False
    ) -> None:
        """Ініціалізація collapsible group box.
        
        Args:
            title: Заголовок групи
            parent: Батьківський віджет
            collapsed: Чи згорнуто за замовчуванням
        """
        super().__init__(title, parent)
        self._collapsed = collapsed
        
        # Зробити групу клікабельною
        self.setCheckable(True)
        self.setChecked(not collapsed)
        self.clicked.connect(self._on_clicked)
        
        # Оновити заголовок з іконкою
        self._update_title()
        
        # Якщо згорнуто за замовчуванням — приховати контент
        if collapsed:
            self._hide_content()
    
    def _on_clicked(self, checked: bool) -> None:
        """Обробка кліку на заголовок групи."""
        self._collapsed = not checked
        self._update_title()
        
        # Показати/приховати контент
        if checked:
            self._show_content()
        else:
            self._hide_content()
        
        self.toggled.emit(checked)
    
    def _update_title(self) -> None:
        """Оновити іконку в заголовку."""
        icon = "▼" if not self._collapsed else "▶"
        base_title = self.title().lstrip("▼▶ ")
        self.setTitle(f"{icon} {base_title}")
    
    def _show_content(self) -> None:
        """Показати весь контент групи."""
        if self.layout():
            for i in range(self.layout().count()):
                item = self.layout().itemAt(i)
                if item and item.widget():
                    item.widget().setVisible(True)
    
    def _hide_content(self) -> None:
        """Приховати весь контент групи."""
        if self.layout():
            for i in range(self.layout().count()):
                item = self.layout().itemAt(i)
                if item and item.widget():
                    item.widget().setVisible(False)
    
    def setCollapsed(self, collapsed: bool) -> None:
        """Програмно встановити стан згортання.
        
        Args:
            collapsed: True для згортання, False для розгортання
        """
        self.setChecked(not collapsed)
    
    def isCollapsed(self) -> bool:
        """Перевірити, чи згорнуто групу.
        
        Returns:
            True якщо згорнуто, False якщо розгорнуто
        """
        return self._collapsed
