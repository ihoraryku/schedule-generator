from __future__ import annotations

from PyQt6.QtCore import Qt, QRect
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QHeaderView, QStyleOptionHeader, QStyle


class ColoredHeaderView(QHeaderView):
    """Custom header view that supports colored sections for weekends/holidays."""
    
    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self._section_colors: dict[int, QColor] = {}
        self._section_text_colors: dict[int, QColor] = {}
    
    def set_section_color(self, logical_index: int, bg_color: QColor, text_color: QColor | None = None):
        """Set background and text color for a specific section."""
        self._section_colors[logical_index] = bg_color
        if text_color:
            self._section_text_colors[logical_index] = text_color
    
    def clear_section_colors(self):
        """Clear all custom section colors."""
        self._section_colors.clear()
        self._section_text_colors.clear()
    
    def paintSection(self, painter: QPainter, rect: QRect, logicalIndex: int):
        """Override paint to apply custom colors to sections."""
        painter.save()
        
        # Check if this section has a custom color
        if logicalIndex in self._section_colors:
            # Fill background with custom color
            painter.fillRect(rect, self._section_colors[logicalIndex])
            
            # Draw border
            painter.setPen(QColor("#D6D9DE"))
            painter.drawRect(rect.adjusted(0, 0, -1, -1))
            
            # Get header text
            text = self.model().headerData(logicalIndex, self.orientation(), Qt.ItemDataRole.DisplayRole)
            
            # Set text color
            if logicalIndex in self._section_text_colors:
                painter.setPen(self._section_text_colors[logicalIndex])
            else:
                painter.setPen(QColor("#24303F"))
            
            # Draw text centered
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(text))
        else:
            # Use default painting
            super().paintSection(painter, rect, logicalIndex)
        
        painter.restore()
