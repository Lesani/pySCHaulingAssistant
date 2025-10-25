"""
Screen capture and image adjustment tool
=======================================

This script provides a desktop utility that allows you to select an area of
your screen via a drag‑and‑drop interface, capture the contents of that
region on demand, adjust the captured image using brightness, contrast and
gamma sliders, and finally send the adjusted image to Anthropic's Claude API
to identify the objectives of a Star Citizen mission.  

Key features
------------

* **Region selection via drag/drop:** Clicking the “Select Region” button
  launches a full‑screen translucent overlay.  Drag out a rectangle to
  define the region you wish to capture.  Once you release the mouse
  button the overlay disappears and the coordinates are stored.

* **Screenshot on demand:** After selecting a region, press the
  “Capture” button to grab the contents of that area.  The script uses
  Pillow’s `ImageGrab.grab` function with the `bbox` argument to copy
  only the pixels inside the bounding box.  According to the Pillow
  documentation, `ImageGrab.grab` returns the pixels inside the given
  bounding box as an image【802034665241383†L146-L171】.

* **Brightness, contrast and gamma controls:** Once an image has been
  captured, three sliders appear.  The brightness and contrast sliders
  wrap Pillow’s `ImageEnhance` classes.  The Pillow docs state that
  `ImageEnhance.Contrast` can control image contrast – a factor of 1.0
  gives the original image and values greater than 1.0 increase
  contrast【54445414827368†L184-L191】.  `ImageEnhance.Brightness` works
  similarly for brightness【54445414827368†L193-L199】.  Gamma correction
  is implemented with a simple power‑law lookup table to provide a
  non‑linear brightness adjustment.  OpenCV’s tutorial on brightness and
  contrast explains that gamma correction adjusts the brightness using a
  non‑linear transformation between the input and output values【434344867527035†L883-L936】.

* **Sending to Claude:** When you click “Send to Claude”, the adjusted
  image is encoded as base64 and sent to Anthropic’s Messages API.  The
  API supports images via a `base64` source type【858316271402685†L291-L330】.  To
  authenticate, set your API key in the `ANTHROPIC_API_KEY` environment
  variable or enter it in the provided field.  You can adjust the
  target model in the GUI.  The API response is displayed in a text
  widget.

Running the script
------------------

Run the program from a normal desktop environment with Python 3.  A
simple user interface will appear.  Select your capture region, press
“Capture”, adjust the sliders as desired and then press “Send to Claude”.
If the `requests` module cannot connect to the API (for example when
offline or without a valid API key), the script will display the error
message instead of a response.

Dependencies
------------

The script relies on standard modules (`tkinter`, `io`, `base64`,
`os`) plus Pillow for image processing and `requests` for HTTP.  These
are commonly available in modern Python distributions.  No external
hotkey library is used – all interactions occur within the GUI.
"""

import base64
import io
import os
import tkinter as tk
from tkinter import ttk, messagebox

from PIL import Image, ImageTk, ImageEnhance, ImageGrab
import requests


class CaptureApp:
    """Main application class encapsulating all UI logic."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Mission Objective Screen Capture")
        self.selection = None  # type: tuple[int, int, int, int] | None
        self.original_image = None  # type: Image.Image | None
        self.adjusted_image = None  # type: Image.Image | None

        # Build UI
        self.build_ui()

    def build_ui(self) -> None:
        """Create the main user interface widgets."""
        # Frame for buttons and controls
        control_frame = ttk.Frame(self.root)
        control_frame.pack(side=tk.TOP, fill=tk.X, padx=8, pady=4)

        # Button to select region
        select_btn = ttk.Button(control_frame, text="Select Region", command=self.select_region)
        select_btn.pack(side=tk.LEFT, padx=4)

        # Button to capture the selected region
        self.capture_btn = ttk.Button(control_frame, text="Capture", command=self.capture_region)
        self.capture_btn.pack(side=tk.LEFT, padx=4)
        self.capture_btn["state"] = tk.DISABLED

        # API key entry
        self.api_key_var = tk.StringVar(value=os.environ.get("ANTHROPIC_API_KEY", ""))
        ttk.Label(control_frame, text="API Key:").pack(side=tk.LEFT, padx=(12, 4))
        self.api_entry = ttk.Entry(control_frame, textvariable=self.api_key_var, width=40, show="*")
        self.api_entry.pack(side=tk.LEFT, padx=4)

        # Model entry
        self.model_var = tk.StringVar(value="claude-sonnet-4-5")
        ttk.Label(control_frame, text="Model:").pack(side=tk.LEFT, padx=(12, 4))
        self.model_entry = ttk.Entry(control_frame, textvariable=self.model_var, width=20)
        self.model_entry.pack(side=tk.LEFT, padx=4)

        # Button to send image to Claude
        self.send_btn = ttk.Button(control_frame, text="Send to Claude", command=self.send_to_claude)
        self.send_btn.pack(side=tk.RIGHT, padx=4)
        self.send_btn["state"] = tk.DISABLED

        # Canvas to display image
        self.canvas = tk.Canvas(self.root, background="gray20", height=400)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # Frame for sliders (initially hidden)
        self.slider_frame = ttk.Frame(self.root)
        # Brightness slider
        self.brightness_var = tk.DoubleVar(value=1.0)
        self.contrast_var = tk.DoubleVar(value=1.0)
        self.gamma_var = tk.DoubleVar(value=1.0)
        # Create sliders with labels
        self.brightness_slider = self._make_slider(self.slider_frame, "Brightness", self.brightness_var, self.update_adjusted_image)
        self.contrast_slider = self._make_slider(self.slider_frame, "Contrast", self.contrast_var, self.update_adjusted_image)
        self.gamma_slider = self._make_slider(self.slider_frame, "Gamma", self.gamma_var, self.update_adjusted_image)

        # Text widget to show Claude's response
        self.response_text = tk.Text(self.root, height=8, wrap=tk.WORD)
        self.response_text.pack(fill=tk.X, padx=8, pady=(4, 8))
        self.response_text.insert(tk.END, "Select a region and capture it to begin.\n")
        self.response_text.config(state=tk.DISABLED)

    def _make_slider(self, parent: tk.Frame, label: str, variable: tk.DoubleVar, command) -> ttk.Scale:
        """Helper to create a labeled slider."""
        frame = ttk.Frame(parent)
        ttk.Label(frame, text=label).pack(side=tk.LEFT, padx=4)
        slider = ttk.Scale(frame, from_=0.1, to=3.0, orient=tk.HORIZONTAL, variable=variable, command=lambda _: command())
        slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        frame.pack(fill=tk.X, pady=2)
        return slider

    def select_region(self) -> None:
        """Launch a translucent overlay to select a rectangular region."""
        # Create full screen overlay
        overlay = tk.Toplevel(self.root)
        overlay.attributes("-fullscreen", True)
        overlay.attributes("-alpha", 0.3)
        overlay.attributes("-topmost", True)
        overlay.config(cursor="crosshair")
        canvas = tk.Canvas(overlay, bg="black")
        canvas.pack(fill=tk.BOTH, expand=True)

        coords = {
            "x0": 0,
            "y0": 0,
            "x1": 0,
            "y1": 0,
            "rect": None
        }

        def on_mouse_down(event):
            coords["x0"] = overlay.winfo_pointerx()
            coords["y0"] = overlay.winfo_pointery()
            coords["x1"] = coords["x0"]
            coords["y1"] = coords["y0"]
            coords["rect"] = canvas.create_rectangle(coords["x0"], coords["y0"], coords["x1"], coords["y1"], outline="red", width=2)

        def on_mouse_move(event):
            if coords["rect"] is not None:
                coords["x1"] = overlay.winfo_pointerx()
                coords["y1"] = overlay.winfo_pointery()
                canvas.coords(coords["rect"], coords["x0"], coords["y0"], coords["x1"], coords["y1"])

        def on_mouse_up(event):
            # Save bounding box in root coordinates
            x0, y0, x1, y1 = coords["x0"], coords["y0"], coords["x1"], coords["y1"]
            # Normalize coordinates (left, upper, right, lower)
            left = min(x0, x1)
            top = min(y0, y1)
            right = max(x0, x1)
            bottom = max(y0, y1)
            self.selection = (int(left), int(top), int(right), int(bottom))
            overlay.destroy()
            self.capture_btn["state"] = tk.NORMAL
            self.response_text.config(state=tk.NORMAL)
            self.response_text.delete(1.0, tk.END)
            self.response_text.insert(tk.END, f"Selected region: {self.selection}\nClick 'Capture' to grab the image.\n")
            self.response_text.config(state=tk.DISABLED)

        overlay.bind("<Button-1>", on_mouse_down)
        overlay.bind("<B1-Motion>", on_mouse_move)
        overlay.bind("<ButtonRelease-1>", on_mouse_up)

    def capture_region(self) -> None:
        """Capture the previously selected region and display it."""
        if not self.selection:
            messagebox.showwarning("No selection", "Please select a region first.")
            return
        try:
            # Use ImageGrab to capture only the bounding box.  Pillow's grab
            # function returns the pixels inside the bounding box as an image
            # object【802034665241383†L146-L171】.
            img = ImageGrab.grab(bbox=self.selection)
        except Exception as exc:
            messagebox.showerror("Capture failed", f"Could not capture the screen region: {exc}")
            return
        self.original_image = img
        self.brightness_var.set(1.0)
        self.contrast_var.set(1.0)
        self.gamma_var.set(1.0)
        # Display the image
        self.display_image(img)
        # Show sliders
        self.slider_frame.pack(fill=tk.X, padx=8, pady=(4, 4))
        self.send_btn["state"] = tk.NORMAL

    def update_adjusted_image(self) -> None:
        """Update the displayed image based on slider values."""
        if self.original_image is None:
            return
        # Start with original image
        img = self.original_image
        # Apply brightness
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(self.brightness_var.get())
        # Apply contrast
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(self.contrast_var.get())
        # Apply gamma correction via lookup table
        gamma_value = self.gamma_var.get()
        # Build lookup table for each possible pixel value
        lut = [min(255, max(0, int((i / 255.0) ** (1.0 / gamma_value) * 255))) for i in range(256)]
        img = img.point(lut * img.layers)
        self.adjusted_image = img
        self.display_image(img)

    def display_image(self, img: Image.Image) -> None:
        """Render the given PIL image onto the canvas."""
        # Resize image to fit inside the canvas while maintaining aspect ratio
        canvas_width = self.canvas.winfo_width() or 1
        canvas_height = self.canvas.winfo_height() or 1
        aspect = img.width / img.height
        if img.width > canvas_width or img.height > canvas_height:
            if canvas_width / aspect <= canvas_height:
                new_w = canvas_width
                new_h = int(canvas_width / aspect)
            else:
                new_h = canvas_height
                new_w = int(canvas_height * aspect)
        else:
            new_w, new_h = img.width, img.height
        resized = img.resize((new_w, new_h), Image.LANCZOS)
        # Convert to Tk photo
        self.photo = ImageTk.PhotoImage(resized)
        self.canvas.delete("all")
        self.canvas.create_image(canvas_width // 2, canvas_height // 2, image=self.photo, anchor=tk.CENTER)

    def send_to_claude(self) -> None:
        """Send the adjusted image to the Anthropic Claude API for analysis."""
        if self.adjusted_image is None:
            messagebox.showwarning("No image", "Capture and adjust an image first.")
            return
        api_key = self.api_key_var.get().strip()
        if not api_key:
            messagebox.showwarning("Missing API key", "Please enter your Anthropic API key.")
            return
        model = self.model_var.get().strip()
        if not model:
            model = "claude-sonnet-4-5"

        # Encode image as PNG in memory
        buffer = io.BytesIO()
        self.adjusted_image.save(buffer, format="PNG")
        data_bytes = buffer.getvalue()
        image_base64 = base64.b64encode(data_bytes).decode("utf-8")

        # Build request payload using the Messages API's vision format
        payload = {
            "model": model,
            "max_tokens": 512,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": image_base64
                            }
                        },
                        {
                            "type": "text",
                            "text": "Identify the objectives of the star citizen mission in this image."
                        }
                    ]
                }
            ]
        }
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        url = "https://api.anthropic.com/v1/messages"

        # Send request
        try:
            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()
            resp_data = response.json()
            # Extract text from response
            content_items = resp_data.get("content", [])
            text_parts = []
            for item in content_items:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
            answer = "\n".join(text_parts) if text_parts else str(resp_data)
        except Exception as exc:
            answer = f"Error: {exc}"
        # Show response
        self.response_text.config(state=tk.NORMAL)
        self.response_text.delete(1.0, tk.END)
        self.response_text.insert(tk.END, answer)
        self.response_text.config(state=tk.DISABLED)


def main() -> None:
    """Entry point for the application."""
    root = tk.Tk()
    app = CaptureApp(root)
    # Ensure the canvas resizes correctly
    def on_resize(event):
        if app.adjusted_image is not None:
            app.display_image(app.adjusted_image)
        elif app.original_image is not None:
            app.display_image(app.original_image)
    app.canvas.bind("<Configure>", on_resize)
    root.mainloop()


if __name__ == "__main__":
    main()