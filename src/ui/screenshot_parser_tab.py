"""
Screenshot Parser tab for PyQt6.

Load screenshots from file or clipboard, select regions, and parse mission data.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QPushButton, QTreeWidget, QTreeWidgetItem, QHeaderView,
    QMessageBox, QFileDialog, QScrollArea, QSplitter, QApplication,
    QComboBox, QProgressDialog, QTabWidget, QListWidget, QListWidgetItem,
    QAbstractItemView, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QRect, QPoint, QUrl
from PyQt6.QtGui import QPixmap, QImage, QPainter, QPen, QColor, QBrush, QKeySequence, QShortcut

from PIL import Image
import io

from src.config import Config
from src.api_client import APIClient
from src.location_autocomplete import LocationMatcher
from src.cargo_autocomplete import CargoMatcher
from src.mission_scan_db import MissionScanDB
from src.image_processor import ImageProcessor
from src.logger import get_logger

logger = get_logger()

# Constants
NO_LOCATION_TEXT = "-- No Location --"
INTERSTELLAR_TEXT = "INTERSTELLAR"


class ImageSelectionWidget(QLabel):
    """Widget for displaying an image with drag-to-select functionality."""

    selection_changed = pyqtSignal(tuple)  # Emits (x1, y1, x2, y2) in image coordinates

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(400, 300)
        self.setStyleSheet("""
            QLabel {
                border: 2px dashed #3d3d3d;
                border-radius: 4px;
                background-color: #252525;
            }
        """)
        self.setText("No image loaded\n\nLoad from file or paste from clipboard")

        # Image state
        self._original_pixmap = None  # Full resolution
        self._display_pixmap = None   # Scaled for display
        self._scale_factor = 1.0

        # Selection state
        self._selection_start = None
        self._selection_end = None
        self._selection_rect = None  # In image coordinates
        self._is_selecting = False

        self.setMouseTracking(True)

    def set_image(self, image: Image.Image):
        """Set the image to display."""
        # Convert PIL Image to QPixmap
        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)

        qimage = QImage.fromData(img_byte_arr.getvalue())
        self._original_pixmap = QPixmap.fromImage(qimage)

        self._update_display()

    def clear_image(self):
        """Clear the displayed image."""
        self._original_pixmap = None
        self._display_pixmap = None
        self._selection_rect = None
        self.setText("No image loaded\n\nLoad from file or paste from clipboard")
        self.update()

    def set_selection(self, rect: tuple):
        """Set the selection rectangle (in image coordinates)."""
        if rect and len(rect) == 4:
            x1, y1, x2, y2 = rect
            self._selection_rect = QRect(x1, y1, x2 - x1, y2 - y1)
        else:
            self._selection_rect = None
        self.update()

    def get_selection(self) -> tuple:
        """Get the current selection rectangle in image coordinates."""
        if self._selection_rect:
            r = self._selection_rect
            return (r.x(), r.y(), r.x() + r.width(), r.y() + r.height())
        return None

    def get_selected_image(self) -> Image.Image:
        """Get the selected region as a PIL Image."""
        if not self._original_pixmap or not self._selection_rect:
            return None

        # Crop the original pixmap
        r = self._selection_rect
        cropped = self._original_pixmap.copy(r)

        # Convert to PIL Image
        buffer = cropped.toImage()
        width = buffer.width()
        height = buffer.height()

        ptr = buffer.bits()
        ptr.setsize(buffer.sizeInBytes())

        # Create PIL Image from bytes
        img = Image.frombytes('RGBA', (width, height), bytes(ptr), 'raw', 'BGRA')
        return img.convert('RGB')

    def _update_display(self):
        """Update the displayed pixmap with scaling."""
        if not self._original_pixmap:
            return

        # Scale to fit widget while maintaining aspect ratio
        available_size = self.size()
        scaled = self._original_pixmap.scaled(
            available_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )

        self._display_pixmap = scaled
        self._scale_factor = scaled.width() / self._original_pixmap.width()

        self.setPixmap(scaled)

    def resizeEvent(self, event):
        """Handle widget resize."""
        super().resizeEvent(event)
        if self._original_pixmap:
            self._update_display()
            self.update()

    def paintEvent(self, event):
        """Paint the widget with selection overlay."""
        super().paintEvent(event)

        if not self._display_pixmap or not self._selection_rect:
            return

        painter = QPainter(self)

        # Calculate offset for centered image
        offset_x = (self.width() - self._display_pixmap.width()) // 2
        offset_y = (self.height() - self._display_pixmap.height()) // 2

        # Convert selection from image coords to display coords
        r = self._selection_rect
        display_rect = QRect(
            int(r.x() * self._scale_factor) + offset_x,
            int(r.y() * self._scale_factor) + offset_y,
            int(r.width() * self._scale_factor),
            int(r.height() * self._scale_factor)
        )

        # Draw semi-transparent overlay outside selection
        overlay_color = QColor(0, 0, 0, 128)
        painter.fillRect(self.rect(), overlay_color)

        # Clear the selection area (show image through)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.fillRect(display_rect, Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        # Draw the image in the selection area
        if self._display_pixmap:
            source_rect = QRect(
                display_rect.x() - offset_x,
                display_rect.y() - offset_y,
                display_rect.width(),
                display_rect.height()
            )
            painter.drawPixmap(display_rect, self._display_pixmap, source_rect)

        # Draw selection border
        pen = QPen(QColor("#00aaff"), 2, Qt.PenStyle.SolidLine)
        painter.setPen(pen)
        painter.drawRect(display_rect)

        # Draw corner handles
        handle_size = 8
        handle_color = QColor("#00aaff")
        painter.setBrush(QBrush(handle_color))
        corners = [
            display_rect.topLeft(),
            display_rect.topRight(),
            display_rect.bottomLeft(),
            display_rect.bottomRight()
        ]
        for corner in corners:
            painter.drawRect(
                corner.x() - handle_size // 2,
                corner.y() - handle_size // 2,
                handle_size,
                handle_size
            )

        painter.end()

    def mousePressEvent(self, event):
        """Handle mouse press for selection start."""
        if event.button() == Qt.MouseButton.LeftButton and self._display_pixmap:
            self._is_selecting = True
            self._selection_start = event.pos()
            self._selection_end = event.pos()

    def mouseMoveEvent(self, event):
        """Handle mouse move for selection drag."""
        if self._is_selecting and self._display_pixmap:
            self._selection_end = event.pos()
            self._update_selection_rect()
            self.update()

    def mouseReleaseEvent(self, event):
        """Handle mouse release for selection end."""
        if event.button() == Qt.MouseButton.LeftButton and self._is_selecting:
            self._is_selecting = False
            self._selection_end = event.pos()
            self._update_selection_rect()
            self.update()

            # Emit selection changed signal
            if self._selection_rect:
                sel = self.get_selection()
                self.selection_changed.emit(sel)
                logger.debug(f"Selection changed: {sel}")

    def _update_selection_rect(self):
        """Update the selection rectangle from start/end points."""
        if not self._selection_start or not self._selection_end or not self._display_pixmap:
            return

        # Calculate offset for centered image
        offset_x = (self.width() - self._display_pixmap.width()) // 2
        offset_y = (self.height() - self._display_pixmap.height()) // 2

        # Convert display coordinates to image coordinates
        def display_to_image(point):
            x = (point.x() - offset_x) / self._scale_factor
            y = (point.y() - offset_y) / self._scale_factor
            # Clamp to image bounds
            x = max(0, min(x, self._original_pixmap.width()))
            y = max(0, min(y, self._original_pixmap.height()))
            return int(x), int(y)

        x1, y1 = display_to_image(self._selection_start)
        x2, y2 = display_to_image(self._selection_end)

        # Normalize rectangle (ensure x1 < x2, y1 < y2)
        if x1 > x2:
            x1, x2 = x2, x1
        if y1 > y2:
            y1, y2 = y2, y1

        # Minimum selection size
        if x2 - x1 > 10 and y2 - y1 > 10:
            self._selection_rect = QRect(x1, y1, x2 - x1, y2 - y1)
        else:
            self._selection_rect = None


class ScreenshotParserTab(QWidget):
    """Tab for parsing screenshots from file or clipboard."""

    # Signal emitted when a scan is added to database
    scan_added = pyqtSignal(dict)

    def __init__(self, config: Config, api_client: APIClient,
                 location_matcher: LocationMatcher, cargo_matcher: CargoMatcher,
                 scan_db: MissionScanDB):
        super().__init__()

        self.config = config
        self.api_client = api_client
        self.location_matcher = location_matcher
        self.cargo_matcher = cargo_matcher
        self.scan_db = scan_db

        # State
        self._current_image = None  # PIL Image
        self._current_source = None  # Track source (file path or "clipboard")
        self._scan_location = None  # Selected in-game location

        self._setup_ui()
        self._load_saved_selection()

    def _setup_ui(self):
        """Setup the tab UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Location selector row
        location_layout = QHBoxLayout()
        location_layout.setSpacing(8)

        location_layout.addWidget(QLabel("Scan Location:"))

        self.location_combo = QComboBox()
        self.location_combo.setMinimumWidth(250)
        self.location_combo.addItem("-- Select Location --")
        self.location_combo.addItem(NO_LOCATION_TEXT)
        self.location_combo.addItem(INTERSTELLAR_TEXT)
        # Add all scannable locations
        for loc in self.location_matcher.get_scannable_locations():
            self.location_combo.addItem(loc)
        self.location_combo.currentIndexChanged.connect(self._on_location_changed)
        location_layout.addWidget(self.location_combo)

        location_layout.addStretch()
        layout.addLayout(location_layout)

        # Top controls
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(8)

        load_btn = QPushButton("Load from File")
        load_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        load_btn.clicked.connect(self._load_from_file)
        controls_layout.addWidget(load_btn)

        paste_btn = QPushButton("Paste from Clipboard")
        paste_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        paste_btn.clicked.connect(self._paste_from_clipboard)
        controls_layout.addWidget(paste_btn)

        controls_layout.addSpacing(20)

        self.parse_btn = QPushButton("Parse Selection")
        self.parse_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.parse_btn.setEnabled(False)
        self.parse_btn.clicked.connect(self._parse_selection)
        controls_layout.addWidget(self.parse_btn)

        self.parse_full_btn = QPushButton("Parse Full Image")
        self.parse_full_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.parse_full_btn.setEnabled(False)
        self.parse_full_btn.clicked.connect(self._parse_full_image)
        controls_layout.addWidget(self.parse_full_btn)

        controls_layout.addStretch()

        clear_btn = QPushButton("Clear")
        clear_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        clear_btn.setProperty("class", "secondary")
        clear_btn.clicked.connect(self._clear_all)
        controls_layout.addWidget(clear_btn)

        layout.addLayout(controls_layout)

        # Selection info
        self.selection_label = QLabel("No selection - drag on image to select region")
        self.selection_label.setProperty("class", "muted")
        layout.addWidget(self.selection_label)

        # Main content splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Image display with selection
        image_group = QGroupBox("Screenshot")
        image_layout = QVBoxLayout()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        self.image_widget = ImageSelectionWidget()
        self.image_widget.selection_changed.connect(self._on_selection_changed)
        scroll.setWidget(self.image_widget)

        image_layout.addWidget(scroll)
        image_group.setLayout(image_layout)
        splitter.addWidget(image_group)

        # Right panel with tabs for Results and Batch
        self.right_tabs = QTabWidget()

        # Results tab
        results_widget = QWidget()
        results_layout = QVBoxLayout(results_widget)
        results_layout.setContentsMargins(4, 4, 4, 4)

        self.results_tree = QTreeWidget()
        self.results_tree.setColumnCount(2)
        self.results_tree.setHeaderLabels(["Field", "Value"])
        self.results_tree.setAlternatingRowColors(True)

        header = self.results_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

        results_layout.addWidget(self.results_tree)

        # Action buttons for results
        results_actions = QHBoxLayout()
        results_actions.addStretch()

        self.copy_results_btn = QPushButton("Copy Results")
        self.copy_results_btn.setProperty("class", "secondary")
        self.copy_results_btn.setEnabled(False)
        self.copy_results_btn.clicked.connect(self._copy_results)
        results_actions.addWidget(self.copy_results_btn)

        results_layout.addLayout(results_actions)
        self.right_tabs.addTab(results_widget, "Results")

        # Batch tab
        batch_widget = self._create_batch_panel()
        self.right_tabs.addTab(batch_widget, "Batch")

        splitter.addWidget(self.right_tabs)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)

        # Add splitter with stretch factor so it expands to fill space
        layout.addWidget(splitter, 1)  # stretch factor 1 makes it expand

        # Status bar
        self.status_label = QLabel("Ready - Load an image to begin")
        self.status_label.setProperty("class", "muted")
        layout.addWidget(self.status_label)

    def _create_batch_panel(self) -> QWidget:
        """Create the batch processing panel with file list."""
        batch_widget = QWidget()
        batch_layout = QVBoxLayout(batch_widget)
        batch_layout.setContentsMargins(4, 4, 4, 4)
        batch_layout.setSpacing(6)

        # Toolbar row
        batch_toolbar = QHBoxLayout()
        batch_toolbar.setSpacing(6)

        self.batch_add_btn = QPushButton("Add Files...")
        self.batch_add_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.batch_add_btn.clicked.connect(self._add_batch_files)
        batch_toolbar.addWidget(self.batch_add_btn)

        self.batch_remove_btn = QPushButton("Remove")
        self.batch_remove_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.batch_remove_btn.setEnabled(False)
        self.batch_remove_btn.clicked.connect(self._remove_selected_files)
        batch_toolbar.addWidget(self.batch_remove_btn)

        batch_toolbar.addStretch()

        batch_clear_btn = QPushButton("Clear")
        batch_clear_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        batch_clear_btn.setProperty("class", "secondary")
        batch_clear_btn.clicked.connect(self._clear_batch_list)
        batch_toolbar.addWidget(batch_clear_btn)

        batch_layout.addLayout(batch_toolbar)

        # File list with drag & drop support
        self.batch_file_list = QListWidget()
        self.batch_file_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.batch_file_list.setAlternatingRowColors(True)
        self.batch_file_list.itemSelectionChanged.connect(self._on_batch_selection_changed)
        self.batch_file_list.itemClicked.connect(self._on_batch_file_clicked)
        self.batch_file_list.setAcceptDrops(True)
        self.batch_file_list.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)

        # Enable drag & drop on the list widget
        self.batch_file_list.dragEnterEvent = self._batch_drag_enter
        self.batch_file_list.dragMoveEvent = self._batch_drag_move
        self.batch_file_list.dropEvent = self._batch_drop

        batch_layout.addWidget(self.batch_file_list, 1)  # stretch factor 1

        # Delete key shortcut for removing files
        delete_shortcut = QShortcut(QKeySequence.StandardKey.Delete, self.batch_file_list)
        delete_shortcut.activated.connect(self._remove_selected_files)

        # Info label
        self.batch_info_label = QLabel("Drag files here or click Add Files...")
        self.batch_info_label.setProperty("class", "muted")
        self.batch_info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        batch_layout.addWidget(self.batch_info_label)

        # Start processing button
        self.batch_start_btn = QPushButton("Start Processing")
        self.batch_start_btn.setEnabled(False)
        self.batch_start_btn.clicked.connect(self._start_batch_processing)
        batch_layout.addWidget(self.batch_start_btn)

        return batch_widget

    def _add_batch_files(self):
        """Open file dialog to add files to batch list."""
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Screenshots for Batch Processing",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp);;All Files (*)"
        )

        for path in file_paths:
            self._add_file_to_batch_list(path)

    def _add_file_to_batch_list(self, file_path: str):
        """Add a single file to the batch list (skip duplicates)."""
        import os

        # Check for duplicates
        for i in range(self.batch_file_list.count()):
            if self.batch_file_list.item(i).data(Qt.ItemDataRole.UserRole) == file_path:
                return  # Skip duplicate

        # Add item
        item = QListWidgetItem(os.path.basename(file_path))
        item.setData(Qt.ItemDataRole.UserRole, file_path)
        item.setToolTip(file_path)
        self.batch_file_list.addItem(item)

        self._update_batch_ui_state()

    def _remove_selected_files(self):
        """Remove selected files from batch list."""
        selected_items = self.batch_file_list.selectedItems()
        for item in selected_items:
            row = self.batch_file_list.row(item)
            self.batch_file_list.takeItem(row)

        self._update_batch_ui_state()

    def _clear_batch_list(self):
        """Clear all files from batch list."""
        self.batch_file_list.clear()
        self._update_batch_ui_state()

    def _on_batch_selection_changed(self):
        """Handle batch list selection change."""
        has_selection = len(self.batch_file_list.selectedItems()) > 0
        self.batch_remove_btn.setEnabled(has_selection)

    def _on_batch_file_clicked(self, item: QListWidgetItem):
        """Preview selected batch file in image widget."""
        file_path = item.data(Qt.ItemDataRole.UserRole)
        if file_path:
            try:
                image = Image.open(file_path)
                self._set_image(image)
                self._current_source = file_path
                self.status_label.setText(f"Preview: {file_path}")
            except Exception as e:
                logger.error(f"Failed to preview batch file: {e}")

    def _update_batch_ui_state(self):
        """Update batch UI state based on file list count."""
        count = self.batch_file_list.count()
        has_files = count > 0

        self.batch_start_btn.setEnabled(has_files)

        # Update tab title with count
        if has_files:
            self.right_tabs.setTabText(1, f"Batch ({count})")
            self.batch_info_label.setText(f"{count} file(s) ready for processing")
        else:
            self.right_tabs.setTabText(1, "Batch")
            self.batch_info_label.setText("Drag files here or click Add Files...")

    def _batch_drag_enter(self, event):
        """Handle drag enter event for batch file list."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def _batch_drag_move(self, event):
        """Handle drag move event for batch file list."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def _batch_drop(self, event):
        """Handle drop event for batch file list."""
        if event.mimeData().hasUrls():
            valid_extensions = ('.png', '.jpg', '.jpeg', '.bmp', '.webp')
            for url in event.mimeData().urls():
                path = url.toLocalFile()
                if path.lower().endswith(valid_extensions):
                    self._add_file_to_batch_list(path)
            event.acceptProposedAction()
        else:
            event.ignore()

    def _start_batch_processing(self):
        """Process all files in the batch list."""
        # Get selection area (from current image or saved config)
        selection = self.image_widget.get_selection()
        if not selection:
            # Try to load from config
            saved_selection = self.config.get("screenshot_parser", "last_selection")
            if saved_selection and len(saved_selection) == 4:
                selection = tuple(saved_selection)
            else:
                QMessageBox.warning(
                    self,
                    "No Selection",
                    "Please load an image and select a region first.\n\n"
                    "The selection area will be used for all screenshots in the batch."
                )
                return

        # Get API key
        api_key = self.config.get_api_key()
        if not api_key:
            QMessageBox.warning(
                self,
                "No API Key",
                "No API key configured. Please set API key in Configuration tab."
            )
            return

        # Get file paths from list
        file_count = self.batch_file_list.count()
        if file_count == 0:
            return

        # Confirm batch processing
        scan_location = self._get_current_scan_location()
        loc_str = scan_location if scan_location else "(No Location)"
        x1, y1, x2, y2 = selection

        reply = QMessageBox.question(
            self,
            "Confirm Batch Process",
            f"Process {file_count} screenshot(s)?\n\n"
            f"Location: {loc_str}\n"
            f"Selection: {x2-x1}x{y2-y1} at ({x1}, {y1})\n\n"
            "Each screenshot will be parsed and added to the database.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Create progress dialog
        progress = QProgressDialog(
            "Processing screenshots...",
            "Cancel",
            0,
            file_count,
            self
        )
        progress.setWindowTitle("Batch Processing")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)

        # Process files (from end to start to avoid index shifting issues)
        success_count = 0
        error_count = 0
        errors = []

        # Build list of items to process
        items_to_process = []
        for i in range(file_count):
            items_to_process.append((i, self.batch_file_list.item(i)))

        for idx, (row_idx, item) in enumerate(items_to_process):
            if progress.wasCanceled():
                break

            file_path = item.data(Qt.ItemDataRole.UserRole)
            progress.setValue(idx)
            progress.setLabelText(f"Processing {idx+1}/{file_count}:\n{file_path}")
            QApplication.processEvents()

            try:
                # Load image
                image = Image.open(file_path)

                # Validate selection is within image bounds
                if x2 > image.width or y2 > image.height:
                    raise ValueError(
                        f"Selection ({x2}x{y2}) exceeds image size ({image.width}x{image.height})"
                    )

                # Crop to selection
                cropped = image.crop(selection)

                # Parse via API
                result = self.api_client.extract_mission_data(cropped, api_key)

                if result.get("success"):
                    mission_data = result["data"]

                    # Apply fuzzy matching
                    mission_data = self._apply_location_fuzzy_matching(mission_data)

                    # Store in database
                    scan_id = self.scan_db.add_scan(mission_data, scan_location)

                    # Emit signal to update scan database tab
                    scan_record = self.scan_db.get_scan(scan_id)
                    if scan_record:
                        self.scan_added.emit(scan_record)

                    success_count += 1
                    logger.info(f"Batch: Parsed {file_path} -> {scan_id[:8]}")

                    # Mark item for removal (will remove after loop to avoid index issues)
                    item.setData(Qt.ItemDataRole.UserRole + 1, "success")
                else:
                    error_msg = result.get("error", "Unknown error")
                    errors.append(f"{file_path}: {error_msg}")
                    error_count += 1
                    logger.error(f"Batch: Failed to parse {file_path}: {error_msg}")

                    # Mark item as failed (red text)
                    item.setForeground(QColor("red"))
                    item.setToolTip(f"Error: {error_msg}")

            except Exception as e:
                errors.append(f"{file_path}: {str(e)}")
                error_count += 1
                logger.error(f"Batch: Error processing {file_path}: {e}")

                # Mark item as failed
                item.setForeground(QColor("red"))
                item.setToolTip(f"Error: {str(e)}")

        progress.setValue(file_count)

        # Remove successfully processed items (in reverse order)
        for i in range(self.batch_file_list.count() - 1, -1, -1):
            item = self.batch_file_list.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole + 1) == "success":
                self.batch_file_list.takeItem(i)

        self._update_batch_ui_state()

        # Show summary
        if progress.wasCanceled():
            summary = f"Batch processing cancelled.\n\nProcessed: {success_count} successful, {error_count} failed"
        else:
            summary = f"Batch processing complete.\n\nSuccessful: {success_count}\nFailed: {error_count}"

        if errors:
            # Show first few errors
            error_details = "\n".join(errors[:5])
            if len(errors) > 5:
                error_details += f"\n... and {len(errors) - 5} more errors"
            summary += f"\n\nErrors:\n{error_details}"

        QMessageBox.information(self, "Batch Complete", summary)

        self.status_label.setText(f"Batch complete: {success_count} parsed, {error_count} failed")
        logger.info(f"Batch processing complete: {success_count} success, {error_count} failed")

    def _load_from_file(self):
        """Load image from file dialog."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Screenshot",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp);;All Files (*)"
        )

        if file_path:
            try:
                image = Image.open(file_path)
                self._set_image(image)
                self._current_source = file_path
                self.status_label.setText(f"Loaded: {file_path}")
                logger.info(f"Loaded image from file: {file_path}")
            except Exception as e:
                logger.error(f"Failed to load image: {e}")
                QMessageBox.critical(self, "Load Error", f"Failed to load image:\n{str(e)}")

    def _paste_from_clipboard(self):
        """Paste image from clipboard."""
        clipboard = QApplication.clipboard()
        mime_data = clipboard.mimeData()

        if mime_data.hasImage():
            qimage = clipboard.image()
            if not qimage.isNull():
                # Convert QImage to PIL Image
                buffer = qimage.bits()
                buffer.setsize(qimage.sizeInBytes())

                # Handle different formats
                if qimage.format() == QImage.Format.Format_RGB32:
                    image = Image.frombytes('RGBA', (qimage.width(), qimage.height()),
                                           bytes(buffer), 'raw', 'BGRA')
                elif qimage.format() == QImage.Format.Format_ARGB32:
                    image = Image.frombytes('RGBA', (qimage.width(), qimage.height()),
                                           bytes(buffer), 'raw', 'BGRA')
                else:
                    # Convert to RGB32 first
                    qimage = qimage.convertToFormat(QImage.Format.Format_RGB32)
                    buffer = qimage.bits()
                    buffer.setsize(qimage.sizeInBytes())
                    image = Image.frombytes('RGBA', (qimage.width(), qimage.height()),
                                           bytes(buffer), 'raw', 'BGRA')

                image = image.convert('RGB')
                self._set_image(image)
                self._current_source = "clipboard"
                self.status_label.setText("Loaded from clipboard")
                logger.info("Loaded image from clipboard")
                return

        QMessageBox.warning(self, "No Image", "No image found in clipboard")

    def _set_image(self, image: Image.Image):
        """Set the current image."""
        self._current_image = image
        self.image_widget.set_image(image)

        # Enable parse buttons
        self.parse_full_btn.setEnabled(True)

        # Apply saved selection if available
        saved_selection = self.config.get("screenshot_parser", "last_selection")
        if saved_selection and len(saved_selection) == 4:
            x1, y1, x2, y2 = saved_selection
            # Validate selection is within image bounds
            if x2 <= image.width and y2 <= image.height:
                self.image_widget.set_selection(saved_selection)
                self.parse_btn.setEnabled(True)
                self._update_selection_label(saved_selection)
            else:
                self.selection_label.setText("Saved selection out of bounds - drag to select new region")
        else:
            self.selection_label.setText("Drag on image to select region")

    def _on_selection_changed(self, selection: tuple):
        """Handle selection change from image widget."""
        if selection:
            self._save_selection(selection)
            self.parse_btn.setEnabled(True)
            self._update_selection_label(selection)
        else:
            self.parse_btn.setEnabled(False)
            self.selection_label.setText("No selection - drag on image to select region")

    def _update_selection_label(self, selection: tuple):
        """Update the selection info label."""
        x1, y1, x2, y2 = selection
        width = x2 - x1
        height = y2 - y1
        self.selection_label.setText(f"Selection: {width}x{height} at ({x1}, {y1})")

    def _save_selection(self, selection: tuple):
        """Save selection to config."""
        if "screenshot_parser" not in self.config.settings:
            self.config.settings["screenshot_parser"] = {}
        self.config.settings["screenshot_parser"]["last_selection"] = list(selection)
        self.config.save()
        logger.debug(f"Saved selection: {selection}")

    def _load_saved_selection(self):
        """Load saved selection from config."""
        saved = self.config.get("screenshot_parser", "last_selection")
        if saved:
            logger.debug(f"Loaded saved selection: {saved}")

    def _on_location_changed(self, index: int):
        """Handle location selection change."""
        selected_text = self.location_combo.currentText()

        if index == 0:  # "-- Select Location --"
            self._scan_location = None
        elif selected_text == NO_LOCATION_TEXT:
            self._scan_location = None
        elif selected_text == INTERSTELLAR_TEXT:
            self._scan_location = "INTERSTELLAR"
            logger.info("Scan location set to: INTERSTELLAR")
        else:
            self._scan_location = selected_text
            logger.info(f"Scan location set to: {selected_text}")

    def _get_current_scan_location(self) -> str:
        """Get the current scan location or None."""
        if self.location_combo.currentIndex() == 0:
            return None
        if self.location_combo.currentText() == NO_LOCATION_TEXT:
            return None
        if self.location_combo.currentText() == INTERSTELLAR_TEXT:
            return "INTERSTELLAR"
        return self._scan_location

    def _parse_selection(self):
        """Parse the selected region."""
        selection = self.image_widget.get_selection()
        if not selection:
            QMessageBox.warning(self, "No Selection", "Please select a region first")
            return

        image = self.image_widget.get_selected_image()
        if image:
            self._do_parse(image)

    def _parse_full_image(self):
        """Parse the full image."""
        if self._current_image:
            self._do_parse(self._current_image)

    def _do_parse(self, image: Image.Image):
        """Parse the given image."""
        try:
            self.status_label.setText("Parsing...")
            self.parse_btn.setEnabled(False)
            self.parse_full_btn.setEnabled(False)

            # Get API key
            api_key = self.config.get_api_key()
            if not api_key:
                raise ValueError("No API key configured. Please set API key in Configuration tab.")

            # Call API
            result = self.api_client.extract_mission_data(image, api_key)

            self.parse_btn.setEnabled(True)
            self.parse_full_btn.setEnabled(True)

            if result.get("success"):
                mission_data = result["data"]

                # Apply fuzzy matching to locations
                mission_data = self._apply_location_fuzzy_matching(mission_data)

                # Store scan in database with selected in-game location
                scan_location = self._get_current_scan_location()
                scan_id = self.scan_db.add_scan(mission_data, scan_location)
                logger.info(f"Scan stored in database: {scan_id[:8]} at {scan_location or 'No Location'}")

                # Emit signal to update scan database tab
                scan_record = self.scan_db.get_scan(scan_id)
                if scan_record:
                    self.scan_added.emit(scan_record)

                # Display results
                self._display_results(mission_data)

                loc_str = f" at {scan_location}" if scan_location else ""
                self.status_label.setText(f"Parsing complete{loc_str} - added to database")
                logger.info("Screenshot parsed successfully")
            else:
                error_msg = result.get("error", "Unknown error")
                self.status_label.setText("Parsing failed")
                QMessageBox.critical(self, "Parse Error", f"Failed to parse:\n{error_msg}")
                logger.error(f"Parse error: {error_msg}")

        except Exception as e:
            logger.error(f"Parse failed: {e}")
            self.parse_btn.setEnabled(True)
            self.parse_full_btn.setEnabled(True)
            self.status_label.setText("Parsing failed")
            QMessageBox.critical(self, "Parse Error", f"Failed to parse:\n{str(e)}")

    def _apply_location_fuzzy_matching(self, mission_data: dict) -> dict:
        """Apply fuzzy matching to location names."""
        if not mission_data or "objectives" not in mission_data:
            return mission_data

        for objective in mission_data["objectives"]:
            if "collect_from" in objective:
                original = objective["collect_from"]
                matched = self.location_matcher.get_best_match(original, confidence_threshold=3)
                if matched != original:
                    logger.info(f"Fuzzy matched collect_from: '{original}' -> '{matched}'")
                objective["collect_from"] = matched

            if "deliver_to" in objective:
                original = objective["deliver_to"]
                matched = self.location_matcher.get_best_match(original, confidence_threshold=3)
                if matched != original:
                    logger.info(f"Fuzzy matched deliver_to: '{original}' -> '{matched}'")
                objective["deliver_to"] = matched

        return mission_data

    def _display_results(self, mission_data: dict):
        """Display parsed results in tree view."""
        self.results_tree.clear()

        # Basic info
        if "reward" in mission_data:
            item = QTreeWidgetItem(self.results_tree)
            item.setText(0, "Reward")
            item.setText(1, f"{mission_data['reward']:,} aUEC")

        if "availability" in mission_data:
            item = QTreeWidgetItem(self.results_tree)
            item.setText(0, "Availability")
            item.setText(1, mission_data["availability"])

        if "rank" in mission_data and mission_data["rank"]:
            item = QTreeWidgetItem(self.results_tree)
            item.setText(0, "Rank")
            item.setText(1, mission_data["rank"])

        if "contracted_by" in mission_data and mission_data["contracted_by"]:
            item = QTreeWidgetItem(self.results_tree)
            item.setText(0, "Contracted By")
            item.setText(1, mission_data["contracted_by"])

        # Objectives
        objectives = mission_data.get("objectives", [])
        if objectives:
            obj_parent = QTreeWidgetItem(self.results_tree)
            obj_parent.setText(0, f"Objectives ({len(objectives)})")
            obj_parent.setExpanded(True)

            for i, obj in enumerate(objectives, 1):
                obj_item = QTreeWidgetItem(obj_parent)
                obj_item.setText(0, f"Objective {i}")

                if "collect_from" in obj:
                    child = QTreeWidgetItem(obj_item)
                    child.setText(0, "Collect From")
                    child.setText(1, obj["collect_from"])

                if "deliver_to" in obj:
                    child = QTreeWidgetItem(obj_item)
                    child.setText(0, "Deliver To")
                    child.setText(1, obj["deliver_to"])

                if "scu_amount" in obj:
                    child = QTreeWidgetItem(obj_item)
                    child.setText(0, "SCU Amount")
                    child.setText(1, str(obj["scu_amount"]))

                if "cargo_type" in obj and obj["cargo_type"]:
                    child = QTreeWidgetItem(obj_item)
                    child.setText(0, "Cargo Type")
                    child.setText(1, obj["cargo_type"])

                obj_item.setExpanded(True)

        self.results_tree.expandAll()
        self.copy_results_btn.setEnabled(True)

        # Store parsed data for copying
        self._parsed_data = mission_data

    def _copy_results(self):
        """Copy results to clipboard as text."""
        if not hasattr(self, '_parsed_data') or not self._parsed_data:
            return

        lines = []
        data = self._parsed_data

        if "reward" in data:
            lines.append(f"Reward: {data['reward']:,} aUEC")
        if "availability" in data:
            lines.append(f"Availability: {data['availability']}")
        if "rank" in data and data["rank"]:
            lines.append(f"Rank: {data['rank']}")
        if "contracted_by" in data and data["contracted_by"]:
            lines.append(f"Contracted By: {data['contracted_by']}")

        objectives = data.get("objectives", [])
        if objectives:
            lines.append(f"\nObjectives ({len(objectives)}):")
            for i, obj in enumerate(objectives, 1):
                lines.append(f"  {i}. Collect from: {obj.get('collect_from', 'N/A')}")
                lines.append(f"     Deliver to: {obj.get('deliver_to', 'N/A')}")
                lines.append(f"     Amount: {obj.get('scu_amount', 0)} SCU")
                if obj.get('cargo_type'):
                    lines.append(f"     Cargo: {obj['cargo_type']}")

        text = "\n".join(lines)
        QApplication.clipboard().setText(text)
        self.status_label.setText("Results copied to clipboard")

    def _clear_all(self):
        """Clear image and results."""
        self._current_image = None
        self._current_source = None
        self.image_widget.clear_image()
        self.results_tree.clear()
        self.parse_btn.setEnabled(False)
        self.parse_full_btn.setEnabled(False)
        self.copy_results_btn.setEnabled(False)
        self.selection_label.setText("No selection - drag on image to select region")
        self.status_label.setText("Cleared - Load an image to begin")
        self._parsed_data = None
