"""
Capture tab for PyQt6.

Screen region capture, image adjustment, and AI extraction interface.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QPushButton, QSlider, QCheckBox, QMessageBox, QScrollArea,
    QFrame, QComboBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap, QImage

from PIL import Image
from datetime import datetime, timedelta
import io

from src.config import Config
from src.api_client import APIClient
from src.image_processor import ImageProcessor
from src.location_autocomplete import LocationMatcher
from src.cargo_autocomplete import CargoMatcher
from src.ui.region_selector import RegionSelector
from src.ui.validation_form import ValidationForm
from src.logger import get_logger

logger = get_logger()

# Constants
LOCATION_TIMEOUT_MINUTES = 10
NO_LOCATION_TEXT = "-- No Location --"


class CaptureTab(QWidget):
    """Capture tab with region selection and AI extraction."""

    # Signal emitted when a scan is added to the database
    scan_added = pyqtSignal(dict)
    # Signal emitted for status bar messages (message, timeout_ms)
    status_message = pyqtSignal(str, int)

    def __init__(self, config: Config, api_client: APIClient,
                 location_matcher: LocationMatcher, cargo_matcher: CargoMatcher,
                 scan_db, on_mission_saved_callback, get_active_missions_callback=None):
        super().__init__()

        self.config = config
        self.api_client = api_client
        self.location_matcher = location_matcher
        self.cargo_matcher = cargo_matcher
        self.scan_db = scan_db
        self.on_mission_saved_callback = on_mission_saved_callback
        self.get_active_missions_callback = get_active_missions_callback

        # State
        self.selection = None
        self.original_image = None
        self.adjusted_image = None

        # Location tracking state
        self.scan_location: str = None
        self.location_selected_time: datetime = None

        # Timer to check location timeout
        self.location_timer = QTimer()
        self.location_timer.timeout.connect(self._check_location_timeout)
        self.location_timer.start(30000)  # Check every 30 seconds

        self._setup_ui()
        self._load_saved_region()

    def _setup_ui(self):
        """Setup the capture tab UI with side-by-side layout."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        # Top controls row (location + capture buttons)
        top_controls = QHBoxLayout()
        top_controls.setSpacing(8)

        # Location selector
        top_controls.addWidget(QLabel("Current Location:"))
        self.location_combo = QComboBox()
        self.location_combo.setMinimumWidth(200)
        self.location_combo.addItem("-- Select Location --")
        self.location_combo.addItem(NO_LOCATION_TEXT)
        for loc in self.location_matcher.get_scannable_locations():
            self.location_combo.addItem(loc)
        self.location_combo.currentIndexChanged.connect(self._on_location_changed)
        top_controls.addWidget(self.location_combo)

        self.location_time_label = QLabel("")
        self.location_time_label.setProperty("class", "muted")
        top_controls.addWidget(self.location_time_label)

        self.location_warning_label = QLabel("")
        self.location_warning_label.setStyleSheet("color: #ff9800; font-weight: bold;")
        self.location_warning_label.hide()
        top_controls.addWidget(self.location_warning_label)

        self.parse_anyway_btn = QPushButton("Parse Anyway")
        self.parse_anyway_btn.setProperty("class", "warning")
        self.parse_anyway_btn.setToolTip("Location is stale (>10 min). Click to capture anyway.")
        self.parse_anyway_btn.clicked.connect(self._force_capture_and_extract)
        self.parse_anyway_btn.hide()
        top_controls.addWidget(self.parse_anyway_btn)

        top_controls.addStretch()

        # Capture buttons
        self.select_btn = QPushButton("Select Region")
        self.select_btn.clicked.connect(self._select_region)
        top_controls.addWidget(self.select_btn)

        self.capture_btn = QPushButton("Capture & Extract")
        self.capture_btn.setEnabled(False)
        self.capture_btn.clicked.connect(self._capture_and_extract)
        top_controls.addWidget(self.capture_btn)

        main_layout.addLayout(top_controls)

        # Create validation form first (we'll reparent its widgets)
        synergy_config = {
            'enabled': self.config.get_synergy_enabled(),
            'ship_capacity': self.config.get_ship_capacity(),
            'capacity_warning_threshold': self.config.get_capacity_warning_threshold(),
            'low_synergy_threshold': self.config.get_low_synergy_threshold(),
            'check_timing': self.config.get_synergy_check_timing(),
            'show_route_preview': self.config.get_synergy_show_route_preview(),
            'show_recommendations': self.config.get_synergy_show_recommendations()
        }

        self.validation_form = ValidationForm(
            self.location_matcher,
            self.cargo_matcher,
            get_active_missions_callback=self.get_active_missions_callback,
            synergy_config=synergy_config
        )
        self.validation_form.mission_saved.connect(self._on_mission_saved)
        self.validation_form.hide()  # We reparent its child widgets

        # === TOP SECTION: Side-by-side (Image | Details + Synergy) ===
        top_content = QHBoxLayout()
        top_content.setSpacing(8)

        # LEFT: Image Preview
        preview_group = QGroupBox("Image Preview")
        preview_group.setMinimumHeight(400)
        preview_layout = QVBoxLayout()
        preview_layout.setContentsMargins(8, 8, 8, 8)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet("""
            QLabel {
                border: 2px dashed #3d3d3d;
                border-radius: 4px;
                background-color: #252525;
            }
        """)
        self.image_label.setText("No image captured")

        scroll = QScrollArea()
        scroll.setWidget(self.image_label)
        scroll.setWidgetResizable(True)
        preview_layout.addWidget(scroll)

        # Image adjustment controls
        adjust_layout = QHBoxLayout()
        adjust_layout.setSpacing(4)

        adjust_layout.addWidget(QLabel("Brightness:"))
        self.brightness_slider = QSlider(Qt.Orientation.Horizontal)
        self.brightness_slider.setRange(-100, 100)
        self.brightness_slider.setValue(0)
        self.brightness_slider.setMaximumWidth(80)
        self.brightness_slider.valueChanged.connect(self._on_adjustment_changed)
        adjust_layout.addWidget(self.brightness_slider)
        self.brightness_value_label = QLabel("0")
        self.brightness_value_label.setMinimumWidth(25)
        adjust_layout.addWidget(self.brightness_value_label)

        adjust_layout.addWidget(QLabel("Contrast:"))
        self.contrast_slider = QSlider(Qt.Orientation.Horizontal)
        self.contrast_slider.setRange(-100, 100)
        self.contrast_slider.setValue(0)
        self.contrast_slider.setMaximumWidth(80)
        self.contrast_slider.valueChanged.connect(self._on_adjustment_changed)
        adjust_layout.addWidget(self.contrast_slider)
        self.contrast_value_label = QLabel("0")
        self.contrast_value_label.setMinimumWidth(25)
        adjust_layout.addWidget(self.contrast_value_label)

        adjust_layout.addWidget(QLabel("Gamma:"))
        self.gamma_slider = QSlider(Qt.Orientation.Horizontal)
        self.gamma_slider.setRange(50, 200)
        self.gamma_slider.setValue(100)
        self.gamma_slider.setMaximumWidth(80)
        self.gamma_slider.valueChanged.connect(self._on_adjustment_changed)
        adjust_layout.addWidget(self.gamma_slider)
        self.gamma_value_label = QLabel("1.0")
        self.gamma_value_label.setMinimumWidth(25)
        adjust_layout.addWidget(self.gamma_value_label)

        reset_btn = QPushButton("Reset")
        reset_btn.setProperty("class", "secondary")
        reset_btn.setToolTip("Reset adjustments")
        reset_btn.clicked.connect(self._reset_adjustments)
        adjust_layout.addWidget(reset_btn)

        adjust_layout.addStretch()
        preview_layout.addLayout(adjust_layout)

        preview_group.setLayout(preview_layout)
        top_content.addWidget(preview_group, 1)

        # RIGHT: Mission Details + Synergy (reparent from validation form)
        right_panel = QVBoxLayout()
        right_panel.setSpacing(6)
        right_panel.setContentsMargins(0, 0, 0, 0)

        # Reparent details group from validation form
        self.validation_form.details_group.setParent(None)
        right_panel.addWidget(self.validation_form.details_group)

        # Reparent synergy group if it exists
        if hasattr(self.validation_form, 'synergy_group') and self.validation_form.synergy_group:
            self.validation_form.synergy_group.setParent(None)
            right_panel.addWidget(self.validation_form.synergy_group)

        right_panel.addStretch()

        right_widget = QWidget()
        right_widget.setLayout(right_panel)
        top_content.addWidget(right_widget, 1)

        main_layout.addLayout(top_content, 0)  # Stretch factor 0 - fixed height

        # === BOTTOM SECTION: Objectives (full width, stretches) ===
        # Reparent objectives group from validation form
        self.validation_form.objectives_group.setParent(None)
        main_layout.addWidget(self.validation_form.objectives_group, 1)  # Stretch factor 1 - takes available space

        # Action buttons (from validation form, keep them connected)
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        clear_btn = QPushButton("Clear")
        clear_btn.setProperty("class", "secondary")
        clear_btn.clicked.connect(self.validation_form.clear)
        button_layout.addWidget(clear_btn)

        save_btn = QPushButton("Add to Hauling List")
        save_btn.clicked.connect(self.validation_form._save_mission)
        button_layout.addWidget(save_btn)

        main_layout.addLayout(button_layout)

    def _select_region(self):
        """Open region selector overlay."""
        self.selector = RegionSelector()
        self.selector.region_selected.connect(self._on_region_selected)
        self.selector.showFullScreen()
        logger.debug("Region selector opened")

    def _on_region_selected(self, bbox: tuple):
        """Handle region selection."""
        self.selection = bbox
        x1, y1, x2, y2 = bbox

        self.status_message.emit(f"Region: {x2-x1}x{y2-y1} at ({x1}, {y1})", 5000)
        self.capture_btn.setEnabled(True)

        # Save region
        self._save_region(bbox)

        logger.info(f"Region selected: {bbox}")

    def _capture_and_extract(self):
        """Capture the selected region and extract mission data."""
        if not self.selection:
            QMessageBox.warning(self, "No Region", "Please select a region first")
            return

        # Check if no location is selected (index 0 = "-- Select Location --")
        if self.location_combo.currentIndex() == 0:
            self._show_no_location_warning()
            return

        # Check if location is stale (but not if "No Location" is selected)
        if self._is_location_set() and self._is_location_stale():
            if self.location_combo.currentText() != NO_LOCATION_TEXT:
                self._update_location_warning(True)
                self.status_message.emit("Location is stale - select new location or click 'Parse Anyway'", 0)
                return

        self._do_capture_and_extract()

    def _do_capture_and_extract(self):
        """Perform the actual capture and extraction (no location checks)."""
        if not self.selection:
            return

        try:
            # Disable button during processing
            self.capture_btn.setEnabled(False)
            self.status_message.emit("Capturing...", 0)

            # Capture image
            self.original_image = ImageProcessor.capture_region(self.selection)

            # Apply adjustments
            self._apply_adjustments()

            # Display image
            self._display_image(self.adjusted_image or self.original_image)

            # Extract data (synchronous)
            self.status_message.emit("Extracting mission data...", 0)
            self._extract_mission_data()

        except Exception as e:
            logger.error(f"Capture failed: {e}")
            QMessageBox.critical(self, "Capture Error", f"Failed to capture:\n{str(e)}")
            self.capture_btn.setEnabled(True)
            self.status_message.emit("Capture failed", 5000)

    def _extract_mission_data(self):
        """Extract mission data using AI."""
        try:
            # Use adjusted image if available, otherwise original
            image = self.adjusted_image or self.original_image

            # Get API key
            api_key = self.config.get_api_key()
            if not api_key:
                raise ValueError("No API key configured. Please set API key in Configuration tab.")

            # Call API (model will be retrieved from provider-specific config)
            result = self.api_client.extract_mission_data(image, api_key)

            # Handle result
            self.capture_btn.setEnabled(True)

            if result.get("success"):
                mission_data = result["data"]

                # Apply fuzzy matching to location names
                mission_data = self._apply_location_fuzzy_matching(mission_data)

                # Store scan in database with location
                scan_location = self._get_current_scan_location()
                scan_id = self.scan_db.add_scan(mission_data, scan_location)
                logger.info(f"Scan stored in database: {scan_id[:8]} at {scan_location or 'No Location'}")

                # Emit signal to update scan database tab
                scan_record = self.scan_db.get_scan(scan_id)
                if scan_record:
                    self.scan_added.emit(scan_record)

                self.validation_form.load_data(mission_data)
                loc_str = f" at {scan_location}" if scan_location else ""
                self.status_message.emit(f"Mission data extracted{loc_str} - Review and save below", 5000)
                logger.info("Mission data extracted successfully")
            else:
                error_msg = result.get("error", "Unknown error")
                self.status_message.emit("Extraction failed", 5000)
                QMessageBox.critical(
                    self,
                    "Extraction Error",
                    f"Failed to extract mission data:\n{error_msg}"
                )
                logger.error(f"Extraction error: {error_msg}")

        except Exception as e:
            logger.error(f"Extraction failed: {e}")
            self.capture_btn.setEnabled(True)
            self.status_message.emit("Extraction failed", 5000)
            QMessageBox.critical(
                self,
                "Extraction Error",
                f"Failed to extract mission data:\n{str(e)}"
            )

    def _apply_location_fuzzy_matching(self, mission_data: dict) -> dict:
        """
        Apply fuzzy matching to location names in extracted mission data.

        This helps autocorrect OCR errors or variations in location names
        to match known canonical location names.

        Args:
            mission_data: Dictionary with mission data including objectives

        Returns:
            Updated mission data with fuzzy-matched location names
        """
        if not mission_data or "objectives" not in mission_data:
            return mission_data

        corrected_count = 0

        for objective in mission_data["objectives"]:
            # Apply fuzzy matching to collect_from location
            if "collect_from" in objective:
                original = objective["collect_from"]
                # Use threshold=3 to allow word-level matching (e.g., "Shubin Mining SAL-2" -> "Shubin Mining Facility SAL-2")
                matched = self.location_matcher.get_best_match(original, confidence_threshold=3)
                if matched != original:
                    logger.info(f"Fuzzy matched collect_from: '{original}' -> '{matched}'")
                    corrected_count += 1
                objective["collect_from"] = matched

            # Apply fuzzy matching to deliver_to location
            if "deliver_to" in objective:
                original = objective["deliver_to"]
                # Use threshold=3 to allow word-level matching (e.g., "Shubin Mining SAL-2" -> "Shubin Mining Facility SAL-2")
                matched = self.location_matcher.get_best_match(original, confidence_threshold=3)
                if matched != original:
                    logger.info(f"Fuzzy matched deliver_to: '{original}' -> '{matched}'")
                    corrected_count += 1
                objective["deliver_to"] = matched

        if corrected_count > 0:
            logger.info(f"Applied fuzzy matching: {corrected_count} location(s) corrected")

        return mission_data

    def _on_adjustment_changed(self):
        """Handle slider value changes."""
        # Update labels
        self.brightness_value_label.setText(str(self.brightness_slider.value()))
        self.contrast_value_label.setText(str(self.contrast_slider.value()))
        gamma = self.gamma_slider.value() / 100.0
        self.gamma_value_label.setText(f"{gamma:.1f}")

        # Apply adjustments
        if self.original_image:
            self._apply_adjustments()
            self._display_image(self.adjusted_image)

    def _reset_adjustments(self):
        """Reset all adjustment sliders."""
        self.brightness_slider.setValue(0)
        self.contrast_slider.setValue(0)
        self.gamma_slider.setValue(100)

    def _apply_adjustments(self):
        """Apply image adjustments to the original image."""
        if not self.original_image:
            return

        # Convert slider values to enhancement factors
        # Slider range: -100 to 100 -> Factor range: 0.0 to 2.0
        brightness = 1.0 + (self.brightness_slider.value() / 100.0)
        contrast = 1.0 + (self.contrast_slider.value() / 100.0)
        gamma = self.gamma_slider.value() / 100.0

        self.adjusted_image = ImageProcessor.adjust_image(
            self.original_image,
            brightness=brightness,
            contrast=contrast,
            gamma=gamma
        )

    def _display_image(self, image: Image.Image):
        """Display PIL image in the label."""
        # Resize for display
        display_image = ImageProcessor.resize_for_display(image, max_width=800, max_height=400)

        # Convert to QPixmap
        img_byte_arr = io.BytesIO()
        display_image.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)

        qimage = QImage.fromData(img_byte_arr.getvalue())
        pixmap = QPixmap.fromImage(qimage)

        self.image_label.setPixmap(pixmap)

    def _on_mission_saved(self, mission_data: dict):
        """Handle mission saved from validation form."""
        self.on_mission_saved_callback(mission_data)

        # Clear form and image
        self.validation_form.clear()
        self.original_image = None
        self.adjusted_image = None
        self.image_label.clear()
        self.image_label.setText("No image captured")
        self.status_message.emit("Mission saved! Capture another or switch tabs.", 5000)

    def _save_region(self, bbox: tuple):
        """Save selected region to config."""
        self.config.settings["capture"] = self.config.settings.get("capture", {})
        self.config.settings["capture"]["last_region"] = list(bbox)
        self.config.save()

    def _load_saved_region(self):
        """Load previously saved region."""
        region = self.config.get("capture", "last_region")
        if region and len(region) == 4:
            self.selection = tuple(region)
            x1, y1, x2, y2 = self.selection
            self.status_message.emit(f"Loaded region: {x2-x1}x{y2-y1} at ({x1}, {y1})", 5000)
            self.capture_btn.setEnabled(True)
            logger.info(f"Loaded saved region: {self.selection}")

    def _on_location_changed(self, index: int):
        """Handle location selection change."""
        selected_text = self.location_combo.currentText()

        if index == 0:  # "-- Select Location --"
            self.scan_location = None
            self.location_selected_time = None
            self.location_time_label.setText("")
            self._update_location_warning(False)
        elif selected_text == NO_LOCATION_TEXT:
            # "No Location" option - no timeout warning needed
            self.scan_location = None
            self.location_selected_time = None
            self.location_time_label.setText("(no location tracking)")
            self._update_location_warning(False)
        else:
            self.scan_location = selected_text
            self.location_selected_time = datetime.now()
            self._update_location_time_display()
            self._update_location_warning(False)
            logger.info(f"Scan location set to: {selected_text}")

    def _check_location_timeout(self):
        """Check if the selected location has timed out."""
        if not self._is_location_set():
            return

        # Skip timeout check if "No Location" is selected
        if self.location_combo.currentText() == NO_LOCATION_TEXT:
            return

        self._update_location_time_display()

        if self._is_location_stale():
            self._update_location_warning(True)

    def _is_location_set(self) -> bool:
        """Check if a valid location is selected."""
        return (
            self.location_combo.currentIndex() > 0 and
            self.location_selected_time is not None
        )

    def _is_location_stale(self) -> bool:
        """Check if the selected location is older than the timeout."""
        if not self.location_selected_time:
            return False

        elapsed = datetime.now() - self.location_selected_time
        return elapsed > timedelta(minutes=LOCATION_TIMEOUT_MINUTES)

    def _update_location_time_display(self):
        """Update the location time label."""
        if not self.location_selected_time:
            self.location_time_label.setText("")
            return

        elapsed = datetime.now() - self.location_selected_time
        minutes = int(elapsed.total_seconds() // 60)
        seconds = int(elapsed.total_seconds() % 60)

        if minutes >= LOCATION_TIMEOUT_MINUTES:
            self.location_time_label.setText(f"({minutes}m {seconds}s ago - STALE)")
            self.location_time_label.setStyleSheet("color: #ff9800;")
        else:
            self.location_time_label.setText(f"({minutes}m {seconds}s ago)")
            self.location_time_label.setStyleSheet("")

    def _update_location_warning(self, show_warning: bool):
        """Show or hide the location warning and parse anyway button."""
        if show_warning:
            self.location_warning_label.setText("Location is stale!")
            self.location_warning_label.show()
            self.parse_anyway_btn.show()
            self.capture_btn.setEnabled(False)
        else:
            self.location_warning_label.hide()
            self.parse_anyway_btn.hide()
            # Re-enable capture button if region is selected
            if self.selection:
                self.capture_btn.setEnabled(True)

    def _force_capture_and_extract(self):
        """Force capture even with stale/missing location (Parse Anyway)."""
        # Hide warning UI
        self.location_warning_label.hide()
        self.parse_anyway_btn.hide()

        # Reset the location time to now if we have a location
        if self.scan_location:
            self.location_selected_time = datetime.now()
            self._update_location_time_display()

        # Re-enable capture button
        if self.selection:
            self.capture_btn.setEnabled(True)

        # Perform the actual capture (bypass location checks)
        self._do_capture_and_extract()

    def _get_current_scan_location(self) -> str:
        """Get the current scan location or None."""
        if self.location_combo.currentIndex() == 0:
            return None
        if self.location_combo.currentText() == NO_LOCATION_TEXT:
            return None
        return self.scan_location

    def _show_no_location_warning(self):
        """Show warning when no location is selected."""
        self.location_warning_label.setText("Select a location first!")
        self.location_warning_label.show()
        self.parse_anyway_btn.show()
        self.status_message.emit("Select a location or click 'Parse Anyway' to scan without location", 0)
