"""
Modern dark theme stylesheets for PyQt6.

Provides a polished, contemporary dark mode interface.
"""

# Main application dark theme
DARK_THEME = """
QMainWindow, QDialog, QWidget {
    background-color: #1e1e1e;
    color: #e0e0e0;
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 9pt;
}

/* Tab Widget */
QTabWidget::pane {
    border: 1px solid #3d3d3d;
    background-color: #1e1e1e;
    border-radius: 4px;
}

QTabBar::tab {
    background-color: #2d2d2d;
    color: #b0b0b0;
    padding: 8px 20px;
    margin-right: 2px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
}

QTabBar::tab:selected {
    background-color: #1e1e1e;
    color: #0078d4;
    border-bottom: 2px solid #0078d4;
}

QTabBar::tab:hover:!selected {
    background-color: #3d3d3d;
    color: #ffffff;
}

/* Buttons */
QPushButton {
    background-color: #0078d4;
    color: #ffffff;
    border: none;
    padding: 6px 16px;
    border-radius: 4px;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #106ebe;
}

QPushButton:pressed {
    background-color: #005a9e;
}

QPushButton:disabled {
    background-color: #3d3d3d;
    color: #666666;
}

QPushButton[class="secondary"] {
    background-color: #2d2d2d;
    color: #e0e0e0;
    border: 1px solid #404040;
}

QPushButton[class="secondary"]:hover {
    background-color: #3d3d3d;
    border-color: #505050;
}

QPushButton[class="danger"] {
    background-color: #d32f2f;
}

QPushButton[class="danger"]:hover {
    background-color: #f44336;
}

QPushButton[class="warning"] {
    background-color: #ff9800;
    color: #000000;
}

QPushButton[class="warning"]:hover {
    background-color: #ffa726;
}

/* Input Fields */
QLineEdit, QTextEdit, QPlainTextEdit {
    background-color: #2d2d2d;
    color: #e0e0e0;
    border: 1px solid #404040;
    border-radius: 4px;
    padding: 6px 8px;
    selection-background-color: #0078d4;
}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
    border: 1px solid #0078d4;
}

QSpinBox, QDoubleSpinBox {
    background-color: #2d2d2d;
    color: #e0e0e0;
    border: 1px solid #404040;
    border-radius: 4px;
    padding: 4px;
    selection-background-color: #0078d4;
}

QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #0078d4;
}

/* ComboBox */
QComboBox {
    background-color: #2d2d2d;
    color: #e0e0e0;
    border: 1px solid #404040;
    border-radius: 4px;
    padding: 6px 8px;
    min-width: 100px;
}

QComboBox:hover {
    border-color: #505050;
}

QComboBox:focus {
    border-color: #0078d4;
}

QComboBox QAbstractItemView {
    background-color: #2d2d2d;
    color: #e0e0e0;
    border: 1px solid #404040;
    selection-background-color: #0078d4;
    selection-color: #ffffff;
    outline: none;
}

/* Labels */
QLabel {
    color: #e0e0e0;
    background-color: transparent;
}

QLabel[class="heading"] {
    font-size: 11pt;
    font-weight: bold;
    color: #ffffff;
}

QLabel[class="subheading"] {
    font-size: 10pt;
    font-weight: 600;
    color: #b0b0b0;
}

QLabel[class="muted"] {
    color: #808080;
}

/* Group Box */
QGroupBox {
    background-color: #252525;
    border: 1px solid #3d3d3d;
    border-radius: 6px;
    margin-top: 12px;
    padding-top: 12px;
    font-weight: 600;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 4px 8px;
    color: #ffffff;
}

/* Sliders */
QSlider::groove:horizontal {
    background: #3d3d3d;
    height: 6px;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    background: #0078d4;
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border-radius: 8px;
}

QSlider::handle:horizontal:hover {
    background: #106ebe;
}

/* Scrollbars */
QScrollBar:vertical {
    background: #2d2d2d;
    width: 12px;
    border-radius: 6px;
}

QScrollBar::handle:vertical {
    background: #505050;
    border-radius: 6px;
    min-height: 20px;
}

QScrollBar::handle:vertical:hover {
    background: #606060;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    background: #2d2d2d;
    height: 12px;
    border-radius: 6px;
}

QScrollBar::handle:horizontal {
    background: #505050;
    border-radius: 6px;
    min-width: 20px;
}

QScrollBar::handle:horizontal:hover {
    background: #606060;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}

/* Tree/Table Views */
QTreeView, QTableView {
    background-color: #2d2d2d;
    alternate-background-color: #282828;
    color: #e0e0e0;
    border: 1px solid #3d3d3d;
    border-radius: 4px;
    gridline-color: #3d3d3d;
    selection-background-color: #0078d4;
    selection-color: #ffffff;
    outline: none;
}

QTreeView::item, QTableView::item {
    padding: 6px 4px;
    border: none;
}

QTreeView::item:hover, QTableView::item:hover {
    background-color: #3d3d3d;
}

QTreeView::item:selected, QTableView::item:selected {
    background-color: #0078d4;
    color: #ffffff;
}

QHeaderView::section {
    background-color: #252525;
    color: #b0b0b0;
    padding: 8px 4px;
    border: none;
    border-right: 1px solid #3d3d3d;
    border-bottom: 1px solid #3d3d3d;
    font-weight: 600;
}

QHeaderView::section:hover {
    background-color: #2d2d2d;
}

/* Checkboxes */
QCheckBox {
    spacing: 8px;
    color: #e0e0e0;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 2px solid #404040;
    border-radius: 3px;
    background-color: #2d2d2d;
}

QCheckBox::indicator:hover {
    border-color: #0078d4;
}

QCheckBox::indicator:checked {
    background-color: #0078d4;
    border-color: #0078d4;
}

/* Radio Buttons */
QRadioButton {
    spacing: 8px;
    color: #e0e0e0;
}

QRadioButton::indicator {
    width: 18px;
    height: 18px;
    border: 2px solid #404040;
    border-radius: 9px;
    background-color: #2d2d2d;
}

QRadioButton::indicator:hover {
    border-color: #0078d4;
}

QRadioButton::indicator:checked {
    background-color: #0078d4;
    border-color: #0078d4;
}

/* Progress Bar */
QProgressBar {
    background-color: #2d2d2d;
    border: 1px solid #3d3d3d;
    border-radius: 4px;
    text-align: center;
    color: #e0e0e0;
}

QProgressBar::chunk {
    background-color: #0078d4;
    border-radius: 3px;
}

/* Tooltips */
QToolTip {
    background-color: #2d2d2d;
    color: #e0e0e0;
    border: 1px solid #404040;
    border-radius: 4px;
    padding: 4px 8px;
}

/* Context Menu */
QMenu {
    background-color: #2d2d2d;
    color: #e0e0e0;
    border: 1px solid #404040;
    border-radius: 4px;
    padding: 4px;
}

QMenu::item {
    padding: 6px 24px 6px 12px;
    border-radius: 3px;
}

QMenu::item:selected {
    background-color: #0078d4;
    color: #ffffff;
}

QMenu::separator {
    height: 1px;
    background: #3d3d3d;
    margin: 4px 8px;
}

/* Status Bar */
QStatusBar {
    background-color: #252525;
    color: #b0b0b0;
    border-top: 1px solid #3d3d3d;
}

QStatusBar::item {
    border: none;
}
"""

def get_stylesheet() -> str:
    """Get the default dark theme stylesheet."""
    return DARK_THEME
