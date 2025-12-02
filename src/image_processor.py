"""
Image capture and processing utilities.

Handles screen capture and image adjustments (brightness, contrast, gamma).
"""

from typing import Tuple, Optional

from PIL import Image, ImageGrab, ImageEnhance

from src.logger import get_logger

logger = get_logger()


class ImageProcessor:
    """Handles image capture and processing operations."""

    @staticmethod
    def capture_region(bbox: Tuple[int, int, int, int]) -> Optional[Image.Image]:
        """
        Capture a region of the screen.

        Args:
            bbox: Bounding box as (left, top, right, bottom)

        Returns:
            Captured PIL Image or None if capture fails
        """
        try:
            logger.debug(f"Capturing screen region: {bbox}")
            image = ImageGrab.grab(bbox=bbox)
            logger.debug(f"Captured image: {image.size[0]}x{image.size[1]} pixels, mode: {image.mode}")
            return image
        except Exception as e:
            logger.error(f"Failed to capture region {bbox}: {e}")
            return None

    @staticmethod
    def adjust_image(
        image: Image.Image,
        brightness: float = 1.0,
        contrast: float = 1.0,
        gamma: float = 1.0
    ) -> Image.Image:
        """
        Apply brightness, contrast, and gamma adjustments to an image.

        Args:
            image: Source PIL Image
            brightness: Brightness factor (1.0 = no change)
            contrast: Contrast factor (1.0 = no change)
            gamma: Gamma correction factor (1.0 = no change)

        Returns:
            Adjusted PIL Image
        """
        # Start with original image
        result = image

        # Apply brightness
        if brightness != 1.0:
            enhancer = ImageEnhance.Brightness(result)
            result = enhancer.enhance(brightness)

        # Apply contrast
        if contrast != 1.0:
            enhancer = ImageEnhance.Contrast(result)
            result = enhancer.enhance(contrast)

        # Apply gamma correction via lookup table
        if gamma != 1.0:
            lut = ImageProcessor._create_gamma_lut(gamma)
            # For RGB/RGBA images, LUT needs to be repeated for each channel
            if result.mode in ('RGB', 'RGBA'):
                lut = lut * len(result.getbands())
            result = result.point(lut)

        return result

    @staticmethod
    def _create_gamma_lut(gamma: float) -> list:
        """
        Create a gamma correction lookup table.

        Args:
            gamma: Gamma correction factor

        Returns:
            List of 256 corrected values (0-255)
        """
        return [
            min(255, max(0, int((i / 255.0) ** (1.0 / gamma) * 255)))
            for i in range(256)
        ]

    @staticmethod
    def resize_for_display(
        image: Image.Image,
        max_width: int,
        max_height: int,
        resample: Image.Resampling = Image.LANCZOS
    ) -> Image.Image:
        """
        Resize image to fit within max dimensions while maintaining aspect ratio.

        Args:
            image: Source PIL Image
            max_width: Maximum width in pixels
            max_height: Maximum height in pixels
            resample: Resampling filter to use

        Returns:
            Resized PIL Image
        """
        if max_width <= 0 or max_height <= 0:
            return image

        aspect = image.width / image.height

        # Only resize if image is larger than max dimensions
        if image.width > max_width or image.height > max_height:
            if max_width / aspect <= max_height:
                new_w = max_width
                new_h = int(max_width / aspect)
            else:
                new_h = max_height
                new_w = int(max_height * aspect)
        else:
            new_w, new_h = image.width, image.height

        if (new_w, new_h) != (image.width, image.height):
            return image.resize((new_w, new_h), resample)

        return image
