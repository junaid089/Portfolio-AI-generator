from django.core.management.base import BaseCommand
from django.conf import settings
from editor.models import Asset
from PIL import Image, ImageDraw, ImageFont, ImageStat
import os


class Command(BaseCommand):
    help = "Regenerate placeholder previews for assets in media/generated/ (overwrites files)."

    def add_arguments(self, parser):
        parser.add_argument('--only-missing', action='store_true', help='Only regenerate images that appear mostly-white')
        parser.add_argument('--limit', type=int, default=0, help='Limit number of assets to process (0 = all)')

    def handle(self, *args, **options):
        qs = Asset.objects.filter(image__startswith='generated/')
        if options['limit']:
            qs = qs[: options['limit']]

        total = 0
        for a in qs:
            path = a.image.path
            if not os.path.exists(path):
                self.stderr.write(f"Skipping {path}: file not found")
                continue

            try:
                img = Image.open(path).convert('RGB')
            except Exception as e:
                self.stderr.write(f"Skipping {path}: cannot open ({e})")
                continue

            # detect mostly-white images if requested
            if options['only_missing']:
                stat = ImageStat.Stat(img)
                mean = sum(stat.mean) / len(stat.mean)
                # if mean is high (near 255) it's probably blank/white
                if mean < 250:
                    self.stdout.write(f"Skipping {a.pk}: mean={mean:.1f} (not mostly white)")
                    continue

            w, h = img.size

            # Build a new visible preview (dark background, centered text)
            base = Image.new('RGB', (w, h), color=(24, 24, 24))
            draw = ImageDraw.Draw(base)
            try:
                font_size = max(14, w // 20)
                font = ImageFont.truetype('arial.ttf', font_size)
            except Exception:
                font = ImageFont.load_default()

            text = a.title or os.path.splitext(os.path.basename(path))[0]
            lines = f"{text}\n(regenerated)"

            try:
                bbox = draw.multiline_textbbox((0, 0), lines, font=font, spacing=4)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
            except Exception:
                tw, th = draw.textsize(lines, font=font)

            x = max(10, (w - tw) // 2)
            y = max(10, (h - th) // 2)
            draw.multiline_text((x, y), lines, fill=(230, 230, 230), font=font, align='center', spacing=4)

            # Try to enqueue HF preview generation via Celery; fallback to local write
            enqueued = False
            try:
                from editor.tasks import hf_generate_preview_task
                # enqueue async preview generation
                hf_generate_preview_task.delay(a.id, prompt=a.title or os.path.splitext(os.path.basename(path))[0])
                self.stdout.write(f"Enqueued preview generation for asset {a.id}")
                enqueued = True
                total += 1
            except Exception:
                # fallback: save preview locally (same behavior as before)
                try:
                    previews_dir = os.path.join(settings.MEDIA_ROOT, 'previews')
                    os.makedirs(previews_dir, exist_ok=True)
                    preview_name = os.path.splitext(os.path.basename(path))[0] + '.jpg'
                    preview_path = os.path.join(previews_dir, preview_name)
                    base.save(preview_path, format='JPEG', quality=90)
                    # attach to model
                    a.preview_image.name = f'previews/{preview_name}'
                    a.save()
                    total += 1
                    self.stdout.write(f"Wrote preview: {preview_path}")
                except Exception as e:
                    self.stderr.write(f"Failed to save preview for {path}: {e}")

        self.stdout.write(self.style.SUCCESS(f"Finished. Regenerated {total} previews."))
