"""
Region selector overlay for PyQt6.

Fullscreen transparent overlay for selecting screen regions.
"""

from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore import Qt, QRect, QPoint, pyqtSignal
from PyQt6.QtGui import QPainter, QPen, QColor, QKeyEvent, QMouseEvent

from src.logger import get_logger

logger = get_logger()


class RegionSelector(QWidget):
    """Fullscreen overlay for drag-to-select region."""

    # Signal emitted when region is selected (x, y, width, height)
    region_selected = pyqtSignal(tuple)

    def __init__(self):
        super().__init__()

        self.start_point = None
        self.end_point = None
        self.is_selecting = False

        self._setup_ui()

    def _setup_ui(self):
        """Setup the overlay window."""
        # Make fullscreen and transparent
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)

        # Cover all screens
        screen_geometry = QApplication.primaryScreen().geometry()
        self.setGeometry(screen_geometry)

        # Styling
        self.setStyleSheet("""
            QWidget {
                background-color: rgba(0, 0, 0, 100);
            }
        """)

    def showFullScreen(self):
        """Show overlay in fullscreen mode."""
        super().showFullScreen()
        logger.debug("Region selector overlay shown")

    def mousePressEvent(self, event: QMouseEvent):
        """Handle mouse press to start selection."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.start_point = event.pos()
            self.end_point = event.pos()
            self.is_selecting = True
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent):
        """Handle mouse move to update selection."""
        if self.is_selecting:
            self.end_point = event.pos()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        """Handle mouse release to complete selection."""
        if event.button() == Qt.MouseButton.LeftButton and self.is_selecting:
            self.end_point = event.pos()
            self.is_selecting = False

            # Calculate selection bounds
            if self.start_point and self.end_point:
                x1 = min(self.start_point.x(), self.end_point.x())
                y1 = min(self.start_point.y(), self.end_point.y())
                x2 = max(self.start_point.x(), self.end_point.x())
                y2 = max(self.start_point.y(), self.end_point.y())

                width = x2 - x1
                height = y2 - y1

                # Only emit if selection is valid
                if width > 10 and height > 10:
                    logger.info(f"Region selected: ({x1}, {y1}, {width}, {height})")
                    self.region_selected.emit((x1, y1, x2, y2))

            self.close()

    def keyPressEvent(self, event: QKeyEvent):
        """Handle key press to cancel selection."""
        if event.key() == Qt.Key.Key_Escape:
            logger.debug("Region selection cancelled")
            self.close()

    def paintEvent(self, event):
        """Draw the selection rectangle."""
        painter = QPainter(self)

        # Draw semi-transparent overlay
        painter.fillRect(self.rect(), QColor(0, 0, 0, 100))

        # Draw selection rectangle if selecting
        if self.is_selecting and self.start_point and self.end_point:
            # Calculate rectangle
            x = min(self.start_point.x(), self.end_point.x())
            y = min(self.start_point.y(), self.end_point.y())
            width = abs(self.end_point.x() - self.start_point.x())
            height = abs(self.end_point.y() - self.start_point.y())

            rect = QRect(x, y, width, height)

            # Clear the selected area
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(rect, Qt.GlobalColor.transparent)

            # Draw border
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            pen = QPen(QColor(0, 120, 212), 2)
            painter.setPen(pen)
            painter.drawRect(rect)

            # Draw dimensions text
            painter.setPen(QColor(255, 255, 255))
            dim_text = f"{width} × {height}"
            painter.drawText(rect.bottomRight() + QPoint(-80, 20), dim_text)
