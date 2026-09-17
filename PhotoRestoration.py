"""
PhotoRestoration.py
Shared photo-restoration helper for Piwigo-connected applications.

Public API
----------
    CV2_AVAILABLE : bool
        True when opencv-python and numpy are importable.

    opencv_restore(pil_img, exposure, contrast, red_cast, sharpen) -> Image
        Apply fading/redness/blur corrections to a PIL image and return a
        new corrected PIL image.  All parameters are on a -100…+100 (or
        0…100) scale.  Sharpening is skipped when CV2_AVAILABLE is False.

    grey_world_red_cast(pil_img) -> float
        The red_cast setting that neutralises a photo's colour cast, measured
        from the photo rather than judged by eye.  Needs neither cv2 nor a
        slider to have been touched.
"""

try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except Exception:
    CV2_AVAILABLE = False


def opencv_restore(pil_img, exposure: float, contrast: float,
                   red_cast: float, sharpen: float):
    """Apply fading/redness/blur corrections using OpenCV.

    Parameters
    ----------
    pil_img  : PIL.Image.Image
    exposure : -100 … +100  (brightness shift)
    contrast : -100 … +100  (multiplicative contrast)
    red_cast : -100 … +100  (+ reduces redness, - warms the photo up)
    sharpen  :    0 … +100  (unsharp-mask strength)

    Returns a new PIL Image (RGB).
    """
    import numpy as _np  # always available when CV2_AVAILABLE, but guard anyway

    img = _np.array(pil_img.convert("RGB"), dtype=_np.float32)

    # 1. Colour cast.  The same arithmetic runs both ways: a negative value
    #    puts red back and takes blue out, for a scan that came out cold.
    if red_cast:
        t = red_cast / 100.0
        img[:, :, 0] = _np.clip(img[:, :, 0] * (1.0 - t * 0.50), 0, 255)  # R ↓
        img[:, :, 1] = _np.clip(img[:, :, 1] * (1.0 + t * 0.05), 0, 255)  # G ↑ slight
        img[:, :, 2] = _np.clip(img[:, :, 2] * (1.0 + t * 0.30), 0, 255)  # B ↑

    # 2. Exposure + contrast  (alpha: 0.5…2.5  beta: -100…+100)
    alpha = 1.0 + contrast / 100.0 * 1.5
    beta  = exposure
    if alpha != 1.0 or beta != 0.0:
        img = _np.clip(img * alpha + beta, 0, 255)

    # 3. Sharpening (unsharp mask) — requires cv2
    if sharpen > 0 and CV2_AVAILABLE:
        t       = sharpen / 100.0
        sigma   = 1.0 + t * 2.0
        amount  = t * 3.0
        u8      = img.astype(_np.uint8)
        blurred = cv2.GaussianBlur(u8, (0, 0), sigma)
        img     = cv2.addWeighted(u8, 1.0 + amount, blurred, -amount, 0).astype(_np.float32)

    from PIL import Image
    return Image.fromarray(_np.clip(img, 0, 255).astype(_np.uint8))


def grey_world_red_cast(pil_img) -> float:
    """The red_cast setting that neutralises this photo's colour cast.

    Grey-world white balance: take an average scene to be neutral overall, so
    any gap between the red and blue means is the cast.  This solves for the
    red_cast that closes that gap, given what red_cast does to each channel
    above --

        R x (1 - 0.50t)  =  B x (1 + 0.30t)
        t = (R - B) / (0.50R + 0.30B)

    -- and returns it on the slider's own -100…+100 scale.  An orange scan
    gives a positive answer, a cold one a negative.

    Measured on a small copy, because the mean of a 100x100 thumbnail is the
    mean of the photo and costs nothing to work out.  Needs no cv2.
    """
    from PIL import Image, ImageStat

    small = pil_img.convert("RGB").resize((100, 100), Image.LANCZOS)
    r, _g, b = ImageStat.Stat(small).mean
    denominator = 0.50 * r + 0.30 * b
    if denominator <= 0:                    # a black frame has no cast to fix
        return 0.0
    return max(-100.0, min(100.0, (r - b) / denominator * 100.0))
