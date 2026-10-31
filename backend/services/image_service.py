import io
from pathlib import Path
from typing import Callable, Optional
import uuid
from PIL import Image, ImageFilter, ImageOps
import pillow_heif

from backend.models import DraftImage, ImageVariantMode

pillow_heif.register_heif_opener()


class ImageService:
    def __init__(
        self,
        data_dir: Path,
        mask_extractor: Optional[Callable[[Image.Image], Image.Image]] = None,
        rembg_model: str = "u2netp",
    ):
        self.data_dir = Path(data_dir)
        self.images_dir = self.data_dir / "images"
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self._mask_extractor = mask_extractor
        self._rembg_model = rembg_model
        self._rembg_session = None

    def clean_and_orient(self, raw_bytes: bytes) -> Image.Image:
        """Open, orient according to EXIF, convert to RGB, and discard all metadata."""
        with Image.open(io.BytesIO(raw_bytes)) as loaded_img:
            oriented = ImageOps.exif_transpose(loaded_img)
            if oriented is None:
                oriented = loaded_img
            rgb_conv = oriented.convert("RGB")
            # Create a completely fresh image with pixel copy to guarantee no EXIF tags survive
            clean_img = Image.new("RGB", rgb_conv.size)
            clean_img.paste(rgb_conv, (0, 0))
            return clean_img

    def create_optimized_variant(self, clean_img: Image.Image) -> Image.Image:
        """Auto-contrast and downscale max dimension to 2048px."""
        opt = ImageOps.autocontrast(clean_img.copy(), cutoff=0.5)
        opt.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
        return opt

    def create_ai_input_variant(self, clean_img: Image.Image) -> Image.Image:
        """Downscale max dimension to 1024px for AI input to preserve privacy and tokens."""
        ai_img = clean_img.copy()
        ai_img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
        return ai_img

    def extract_foreground(self, img: Image.Image) -> Image.Image:
        """Extract RGBA image with foreground using rembg or injected mask extractor."""
        if self._mask_extractor is not None:
            return self._mask_extractor(img)

        import rembg
        if self._rembg_session is None:
            self._rembg_session = rembg.new_session(self._rembg_model)

        return rembg.remove(img, session=self._rembg_session)

    def _get_draft_image_dir(self, draft_id: str) -> Path:
        dir_path = self.images_dir / draft_id
        dir_path.mkdir(parents=True, exist_ok=True)
        return dir_path

    def process_upload(
        self, draft_id: str, raw_bytes: bytes, original_filename: str
    ) -> DraftImage:
        draft_img_dir = self._get_draft_image_dir(draft_id)
        image_id = f"img_{uuid.uuid4().hex[:12]}"

        clean_img = self.clean_and_orient(raw_bytes)
        opt_img = self.create_optimized_variant(clean_img)
        ai_img = self.create_ai_input_variant(clean_img)

        opt_path = draft_img_dir / f"{image_id}_optimized.jpg"
        ai_path = draft_img_dir / f"{image_id}_ai.jpg"

        opt_img.save(opt_path, format="JPEG", quality=90, optimize=True)
        ai_img.save(ai_path, format="JPEG", quality=85, optimize=True)

        variants = {
            ImageVariantMode.OPTIMIZED: f"/api/drafts/{draft_id}/images/{image_id}/optimized"
        }

        return DraftImage(
            id=image_id,
            original_filename=original_filename,
            active_mode=ImageVariantMode.OPTIMIZED,
            variants=variants,
            width=opt_img.width,
            height=opt_img.height,
            exif_stripped=True,
        )

    def get_or_create_cutout(self, draft_id: str, image_id: str) -> Path:
        draft_img_dir = self._get_draft_image_dir(draft_id)
        cutout_path = draft_img_dir / f"{image_id}_cutout.jpg"
        if cutout_path.exists():
            return cutout_path

        opt_path = draft_img_dir / f"{image_id}_optimized.jpg"
        if not opt_path.exists():
            raise FileNotFoundError(f"Optimized image not found: {opt_path}")

        with Image.open(opt_path) as opt_img:
            rgba = self.extract_foreground(opt_img)
            # Composite foreground onto clean neutral light-gray/white (#F8F9FA) canvas
            bg = Image.new("RGB", rgba.size, (248, 249, 250))
            bg.paste(rgba, mask=rgba.split()[3])
            bg.save(cutout_path, format="JPEG", quality=90, optimize=True)
            return cutout_path

    def get_or_create_blurred(self, draft_id: str, image_id: str) -> Path:
        draft_img_dir = self._get_draft_image_dir(draft_id)
        blurred_path = draft_img_dir / f"{image_id}_blurred.jpg"
        if blurred_path.exists():
            return blurred_path

        opt_path = draft_img_dir / f"{image_id}_optimized.jpg"
        if not opt_path.exists():
            raise FileNotFoundError(f"Optimized image not found: {opt_path}")

        with Image.open(opt_path) as opt_img:
            rgba = self.extract_foreground(opt_img)
            blurred_bg = opt_img.filter(ImageFilter.GaussianBlur(radius=18))
            composited = Image.composite(opt_img, blurred_bg, rgba.split()[3])
            composited.save(blurred_path, format="JPEG", quality=90, optimize=True)
            return blurred_path

    def delete_image(self, draft_id: str, image_id: str) -> bool:
        draft_img_dir = self._get_draft_image_dir(draft_id)
        deleted_any = False
        for p in draft_img_dir.glob(f"{image_id}_*"):
            try:
                p.unlink()
                deleted_any = True
            except OSError:
                pass
        return deleted_any
