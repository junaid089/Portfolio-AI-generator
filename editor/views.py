import os
import json
import os
import uuid

from PIL import Image, ImageEnhance
from django.conf import settings
from django.contrib.auth.decorators import user_passes_test
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from .forms import ObjectRemovalForm, UploadForm
from .models import Asset, GeneratorJob, Version


@method_decorator(cache_page(getattr(settings, 'HOME_CACHE_SECONDS', 300)), name='dispatch')
class HomeView(TemplateView):
    """Homepage dashboard showing recent assets with lightweight caching."""

    template_name = 'editor/home.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        asset_queryset = (
            Asset.objects.order_by('-created_at')
            .prefetch_related('generator_jobs')
        )
        all_assets = list(asset_queryset[:100])  # limit to keep cache footprint small
        context['assets'] = all_assets[:24]

        tags = []
        for asset in all_assets:
            for tag in asset.tags or []:
                if tag and tag not in tags:
                    tags.append(tag)
        context['categories'] = [{'name': tag} for tag in tags[:8]]
        context['featured_assets'] = [a for a in all_assets if 'featured' in (a.tags or [])][:6]
        return context


def upload_and_edit(request):
    if request.method == 'POST':
        form = UploadForm(request.POST, request.FILES)
        if form.is_valid():
            title = form.cleaned_data.get('title')
            imgfile = form.cleaned_data['image']
            brightness = form.cleaned_data['brightness']
            contrast = form.cleaned_data['contrast']
            saturation = form.cleaned_data['saturation']

            asset = Asset.objects.create(title=title, image=imgfile)

            # open with PIL
            img_path = asset.image.path
            img = Image.open(img_path).convert('RGB')

            # Brightness
            if brightness != 1.0:
                img = ImageEnhance.Brightness(img).enhance(brightness)

            # Contrast
            if contrast != 1.0:
                img = ImageEnhance.Contrast(img).enhance(contrast)

            # Saturation (Pillow ImageEnhance.Color)
            if saturation != 1.0:
                img = ImageEnhance.Color(img).enhance(saturation)

            # Save processed image
            filename = f"processed_{uuid.uuid4().hex[:8]}.jpg"
            processed_dir = os.path.join(settings.MEDIA_ROOT, 'processed')
            os.makedirs(processed_dir, exist_ok=True)
            out_path = os.path.join(processed_dir, filename)
            img.save(out_path, format='JPEG', quality=95)

            # attach to asset
            # store relative path for ImageField
            asset.processed_image.name = f'processed/{filename}'
            asset.save()

            return render(request, 'editor/result.html', {'asset': asset})
    else:
        form = UploadForm()
    return render(request, 'editor/upload.html', {'form': form})


def editor_view(request, asset_id):
    asset = get_object_or_404(Asset, pk=asset_id)
    # current actions from metadata (if any)
    edits = asset.metadata.get('edits') if asset.metadata else None
    return render(request, 'editor/editor.html', {'asset': asset, 'edits': json.dumps(edits or [])})


@require_POST
def save_actions(request, asset_id):
    """Save action-list JSON for an asset (autosave/explicit save)."""
    asset = get_object_or_404(Asset, pk=asset_id)
    try:
        payload = json.loads(request.body.decode('utf-8'))
        actions = payload.get('actions')
        note = payload.get('note', '')
        if not isinstance(actions, list):
            return HttpResponseBadRequest('actions must be a list')
    except Exception:
        return HttpResponseBadRequest('invalid json')

    # persist into metadata
    meta = asset.metadata or {}
    meta['edits'] = actions
    asset.metadata = meta
    asset.save()

    # snapshot version
    Version.objects.create(asset=asset, actions=actions, note=note)

    return JsonResponse({'status': 'ok'})


@require_POST
def export_actions(request, asset_id):
    """Render the provided or saved actions server-side and save processed image."""
    asset = get_object_or_404(Asset, pk=asset_id)
    try:
        payload = json.loads(request.body.decode('utf-8'))
        actions = payload.get('actions') or asset.metadata.get('edits')
        if not isinstance(actions, list):
            return HttpResponseBadRequest('actions must be a list')
    except Exception:
        return HttpResponseBadRequest('invalid json')

    # apply actions server-side using Pillow
    try:
        processed_path = apply_actions_and_save(asset, actions)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

    return JsonResponse({'status': 'ok', 'processed': asset.processed_image.url})


def apply_actions_and_save(asset, actions):
    """Replay a list of simple actions on the asset's original image and save result.

    Supported ops: exposure (brightness), contrast, saturation, rotate (deg), crop (box [x,y,w,h])
    """
    src_path = asset.image.path
    img = Image.open(src_path).convert('RGB')

    for act in actions:
        op = act.get('op')
        if op == 'exposure':
            v = float(act.get('value', 1.0))
            img = ImageEnhance.Brightness(img).enhance(v)
        elif op == 'contrast':
            v = float(act.get('value', 1.0))
            img = ImageEnhance.Contrast(img).enhance(v)
        elif op == 'saturation':
            v = float(act.get('value', 1.0))
            img = ImageEnhance.Color(img).enhance(v)
        elif op == 'rotate':
            deg = float(act.get('deg', 0.0))
            img = img.rotate(-deg, expand=True)
        elif op == 'crop':
            box = act.get('box')
            if box and len(box) == 4:
                x, y, w, h = map(int, box)
                img = img.crop((x, y, x + w, y + h))
        # other ops can be added here

    # Save processed image
    filename = f"export_{uuid.uuid4().hex[:8]}.jpg"
    out_dir = os.path.join(settings.MEDIA_ROOT, 'processed')
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, filename)
    img.save(out_path, format='JPEG', quality=95)

    asset.processed_image.name = f'processed/{filename}'
    asset.save()
    return out_path


def object_removal(request):
    """Basic object removal placeholder using OpenCV inpainting with a mask.
    Expects a mask image where white pixels indicate the area to remove."""
    if request.method == 'POST':
        form = ObjectRemovalForm(request.POST, request.FILES)
        if form.is_valid():
            asset = None
            asset_id = form.cleaned_data.get('asset_id')
            uploaded_image = form.cleaned_data.get('image')
            mask_file = form.cleaned_data.get('mask')

            # Determine source asset: existing or newly uploaded
            if asset_id:
                asset = get_object_or_404(Asset, pk=asset_id)
            elif uploaded_image:
                # create a temporary asset from uploaded image
                asset = Asset.objects.create(title='Object removal upload', image=uploaded_image)
            else:
                return render(request, 'editor/object_removal.html', {
                    'form': form,
                    'error': 'Please provide either an existing asset id or upload an image.'
                })

            # Lazy import of numpy & cv2 so management commands work without heavy deps
            try:
                import numpy as np
                import cv2
            except Exception:
                return render(request, 'editor/object_removal.html', {
                    'form': form,
                    'error': 'Required libraries (numpy, opencv-python) are not installed. See requirements.txt.'
                })

            src_path = asset.processed_image.path if asset.processed_image else asset.image.path
            src = cv2.imread(src_path)
            if src is None:
                return render(request, 'editor/object_removal.html', {
                    'form': form,
                    'error': 'Failed to load source image for inpainting.'
                })

            try:
                mask_np = cv2.imdecode(np.frombuffer(mask_file.read(), np.uint8), cv2.IMREAD_GRAYSCALE)
            except Exception:
                return render(request, 'editor/object_removal.html', {
                    'form': form,
                    'error': 'Failed to read mask image. Ensure it is a valid image file.'
                })

            # create binary mask (white=255 = inpaint region)
            _, mask_bin = cv2.threshold(mask_np, 127, 255, cv2.THRESH_BINARY)

            inpainted = cv2.inpaint(src, mask_bin, 3, cv2.INPAINT_TELEA)

            # save result
            filename = f"inpaint_{uuid.uuid4().hex[:8]}.jpg"
            out_dir = os.path.join(settings.MEDIA_ROOT, 'processed')
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, filename)
            cv2.imwrite(out_path, inpainted)

            asset.processed_image.name = f'processed/{filename}'
            asset.save()

            return render(request, 'editor/result.html', {'asset': asset})
    else:
        form = ObjectRemovalForm()
    return render(request, 'editor/object_removal.html', {'form': form})


class GeneratorDashboardView(TemplateView):
    """Render the generator interface and list recent generated assets."""

    template_name = 'editor/generator.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['recent'] = (
            Asset.objects.filter(title__startswith='Gen:')
            .only('id', 'title', 'image', 'preview_image', 'created_at')
            .order_by('-created_at')[:24]
        )
        return context


@require_POST
def create_generator_job(request):
    """Create a generator job and run a placeholder generator that creates simple images with the prompt text.

    This is a demo/stub to exercise the UI and data flow. Replace with real API calls later.
    """
    prompt = request.POST.get('prompt', '').strip()
    count = int(request.POST.get('count', 1))
    size = request.POST.get('size', '512x512')
    if not prompt:
        return HttpResponseBadRequest('prompt required')

    job = GeneratorJob.objects.create(prompt=prompt, count=count, size=size)

    # store extra params on the job for later use (seed, negative_prompt, model)
    extra = {}
    for k in ('seed', 'negative_prompt', 'model'):
        v = request.POST.get(k)
        if v:
            extra[k] = v
    if extra:
        # attach to job via params JSON field if available, else use metadata via setattr
        try:
            job.params = extra
            job.save()
        except Exception:
            # older schema: ignore
            pass

    # enqueue generation task (Celery)
    ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    try:
        from .tasks import hf_generate_task
        hf_generate_task.delay(job.id)
        if ajax:
            return JsonResponse({'status': 'enqueued', 'job_id': job.id})
        return redirect('editor:generator')
    except Exception:
        # fallback to synchronous placeholder generator if Celery not available
        w, h = map(int, size.split('x')) if 'x' in size else (512, 512)
        created_assets = []
        for i in range(count):
            # Draw a generator placeholder with darker background and centered text
            from PIL import ImageDraw, ImageFont
            img = Image.new('RGB', (w, h), color=(24, 24, 24))
            draw = ImageDraw.Draw(img)
            try:
                font_size = max(16, w // 20)
                font = ImageFont.truetype('arial.ttf', font_size)
            except Exception:
                font = ImageFont.load_default()
            text = (prompt[:400] + '...') if len(prompt) > 400 else prompt
            lines = f"{text}\n({i+1}/{count})"
            try:
                bbox = draw.multiline_textbbox((0, 0), lines, font=font, spacing=4)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
            except Exception:
                tw, th = draw.textsize(lines, font=font)
            x = max(10, (w - tw) // 2)
            y = max(10, (h - th) // 2)
            draw.multiline_text((x, y), lines, fill=(230, 230, 230), font=font, align='center', spacing=4)

            filename = f"gen_{uuid.uuid4().hex[:8]}.jpg"
            out_dir = os.path.join(settings.MEDIA_ROOT, 'generated')
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, filename)
            img.save(out_path, format='JPEG', quality=90)

            asset = Asset.objects.create(title=f"Gen: {prompt[:40]}", image='generated/' + filename)
            created_assets.append(asset)
            job.result_assets.add(asset)

        job.completed = True
        job.save()

        if ajax:
            # return result URLs
            urls = [request.build_absolute_uri(a.image.url) for a in created_assets]
            return JsonResponse({'status': 'done', 'job_id': job.id, 'results': urls})
        return redirect('editor:generator')


def generator_status(request, job_id):
    """Return JSON status for a generator job: completed flag and result URLs."""
    job = get_object_or_404(GeneratorJob.objects.prefetch_related('result_assets'), pk=job_id)
    completed = bool(job.completed)
    assets = job.result_assets.all().only('id', 'image', 'processed_image', 'preview_image')
    results = []
    for a in assets:
        url = None
        if a.preview_image:
            url = a.preview_image.url
        elif a.processed_image:
            url = a.processed_image.url
        elif a.image:
            url = a.image.url
        elif getattr(a, 'file', None):
            url = a.file.url
        if url:
            results.append(request.build_absolute_uri(url))
    return JsonResponse({'job_id': job.id, 'completed': completed, 'results': results})


@require_POST
def regenerate_preview(request, asset_id):
    """Regenerate a single generated asset preview (AJAX).

    Overwrites the existing image file with a visible preview (dark background, centered text).
    Returns JSON with the new absolute URL on success.
    """
    asset = get_object_or_404(Asset, pk=asset_id)

    # Only operate on generated/ files to be safe
    try:
        img_path = asset.image.path
    except Exception:
        return JsonResponse({'status': 'error', 'message': 'Asset has no file path'}, status=400)

    # compute expected preview name/url
    preview_name = os.path.splitext(os.path.basename(img_path))[0] + '.jpg'
    preview_rel = f'previews/{preview_name}'
    preview_url = request.build_absolute_uri(settings.MEDIA_URL + preview_rel)

    # Try to enqueue HF preview generation via Celery; if not available, fall back to synchronous local generation
    try:
        from .tasks import hf_generate_preview_task
        hf_generate_preview_task.delay(asset.id, prompt=asset.title or None)
        return JsonResponse({'status': 'enqueued', 'url': preview_url})
    except Exception:
        # fallback to local generation (same behavior as the older implementation)
        try:
            from PIL import Image, ImageDraw, ImageFont
            with Image.new('RGB', (512, 512), color=(24, 24, 24)) as base:
                draw = ImageDraw.Draw(base)
                try:
                    font_size = max(14, 512 // 20)
                    font = ImageFont.truetype('arial.ttf', font_size)
                except Exception:
                    font = ImageFont.load_default()

                text = asset.title or os.path.splitext(os.path.basename(img_path))[0]
                lines = f"{text}\n(regenerated)"
                try:
                    bbox = draw.multiline_textbbox((0, 0), lines, font=font, spacing=4)
                    tw = bbox[2] - bbox[0]
                    th = bbox[3] - bbox[1]
                except Exception:
                    tw, th = draw.textsize(lines, font=font)
                x = max(10, (512 - tw) // 2)
                y = max(10, (512 - th) // 2)
                draw.multiline_text((x, y), lines, fill=(230, 230, 230), font=font, align='center', spacing=4)

                # Attempt to preserve original size if possible
                try:
                    from PIL import Image as PILImage
                    orig = PILImage.open(img_path)
                    w, h = orig.size
                    orig.close()
                    if (w, h) != (512, 512):
                        base = base.resize((w, h), PILImage.Resampling.LANCZOS)
                except Exception:
                    pass

                previews_dir = os.path.join(settings.MEDIA_ROOT, 'previews')
                os.makedirs(previews_dir, exist_ok=True)
                preview_path = os.path.join(previews_dir, preview_name)
                base.save(preview_path, format='JPEG', quality=90)

            asset.preview_image.name = preview_rel
            asset.save()
            return JsonResponse({'status': 'ok', 'url': request.build_absolute_uri(asset.preview_image.url)})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@user_passes_test(lambda u: u.is_staff)
def batch_regenerate_page(request):
    """Admin page to select generated assets and enqueue preview generation."""
    assets = Asset.objects.filter(image__startswith='generated/').order_by('-created_at')[:200]
    return render(request, 'editor/admin_batch_regen.html', {'assets': assets})


@user_passes_test(lambda u: u.is_staff)
@require_POST
def batch_enqueue_previews(request):
    """Enqueue preview generation tasks for selected assets.

    Expects form-encoded 'asset_ids' values (can be multiple). Returns JSON list of {asset_id, preview_url, enqueued}.
    """
    ids = request.POST.getlist('asset_ids')
    if not ids:
        return JsonResponse({'status': 'error', 'message': 'no asset_ids provided'}, status=400)

    results = []
    for aid in ids:
        try:
            a = Asset.objects.get(pk=int(aid))
        except Exception:
            results.append({'asset_id': aid, 'error': 'not found'})
            continue

        img_path = None
        try:
            img_path = a.image.path
        except Exception:
            pass

        preview_name = os.path.splitext(os.path.basename(img_path or a.image.name))[0] + '.jpg'
        preview_rel = f'previews/{preview_name}'
        preview_url = request.build_absolute_uri(settings.MEDIA_URL + preview_rel)

        try:
            from .tasks import hf_generate_preview_task
            hf_generate_preview_task.delay(a.id, prompt=a.title or None)
            results.append({'asset_id': a.id, 'preview_url': preview_url, 'enqueued': True})
        except Exception:
            # fallback: generate locally synchronously
            try:
                from PIL import Image, ImageDraw, ImageFont
                with Image.new('RGB', (512, 512), color=(24, 24, 24)) as base:
                    draw = ImageDraw.Draw(base)
                    try:
                        font = ImageFont.load_default()
                    except Exception:
                        font = None
                    text = a.title or os.path.splitext(os.path.basename(a.image.name))[0]
                    draw.text((10, 10), text, fill=(230, 230, 230), font=font)
                    previews_dir = os.path.join(settings.MEDIA_ROOT, 'previews')
                    os.makedirs(previews_dir, exist_ok=True)
                    preview_path = os.path.join(previews_dir, preview_name)
                    base.save(preview_path, format='JPEG', quality=90)
                a.preview_image.name = preview_rel
                a.save()
                results.append({'asset_id': a.id, 'preview_url': preview_url, 'enqueued': False})
            except Exception as e:
                results.append({'asset_id': a.id, 'error': str(e)})

    return JsonResponse({'status': 'ok', 'results': results})
