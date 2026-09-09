"""Read a bounded image snapshot without following agent-controlled symlinks."""
import io
import os
from pathlib import Path
import stat
import warnings

# Conservative still-image limit for X's simple upload endpoint.
MAX_IMAGE_BYTES = 5_000_000
FORMATS = {'PNG': ('png', 'image/png'), 'JPEG': ('jpg', 'image/jpeg'),
           'WEBP': ('webp', 'image/webp'), 'GIF': ('gif', 'image/gif')}


def read_image(reference, media_root, chat_root, chat_uid=10000):
    """Accept a library basename or an exact path directly under either root.

    Cache membership is a file-access boundary, not proof of who sent the image.
    The agent still follows Plow's authenticated owner-chat instructions. Neither
    an absolute path elsewhere nor any symlink can widen this root sender's read.
    """
    if (not isinstance(reference, str) or not reference
            or any(ord(c) < 32 or ord(c) == 127 for c in reference)):
        raise ValueError('Each media item must name an image from chat or the image library.')
    roots = [Path(media_root).absolute(), Path(chat_root).absolute()]
    if reference == Path(reference).name and reference not in ('.', '..'):
        root, name = roots[0], reference
    else:
        match = next(((root, reference[len(str(root)) + 1:]) for root in roots
                      if reference.startswith(str(root) + '/')), None)
        if match is None:
            raise ValueError('Image must come from a chat attachment or the image library.')
        root, name = match
        if not name or name in ('.', '..') or '/' in name:
            raise ValueError('Image paths cannot traverse directories.')

    fd = None
    try:
        # Resolve every component via directory descriptors, never Path.resolve
        # followed by a second path open. A cache directory can change mid-read.
        fd = os.open(root.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        for part in root.parts[1:]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        image_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        os.close(fd)
        fd = image_fd
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('Attachment must be a regular image file.')
        if root == roots[1] and info.st_uid != chat_uid:
            raise ValueError('Chat attachment is not owned by the agent runtime.')
        if info.st_size > MAX_IMAGE_BYTES:
            raise ValueError('Image exceeds 5 MB; ask for a smaller still image.')
        with os.fdopen(fd, 'rb') as file:
            fd = None
            data = file.read(MAX_IMAGE_BYTES + 1)
        if not data or len(data) > MAX_IMAGE_BYTES:
            raise ValueError('Image must be nonempty and at most 5 MB.')
    except OSError:
        raise ValueError('Image is unavailable or unsafe to read; ask the owner to resend it.') from None
    finally:
        if fd is not None:
            os.close(fd)

    # Import lazily: host-side credential checks import x_send on stdlib-only
    # Python; only the image sender needs the runtime's existing Pillow.
    from PIL import Image, UnidentifiedImageError

    # Pillow is already part of the pinned Hermes image. Validate the bytes we
    # will upload, not a path that can be swapped after checking it.
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                fmt = image.format
                if fmt not in FORMATS or getattr(image, 'n_frames', 1) != 1:
                    raise ValueError('Send a still PNG, JPEG, WebP or GIF image; animation is not supported.')
                image.verify()
            # JPEG verify() alone does not decode or detect truncation.
            with Image.open(io.BytesIO(data)) as decoded:
                decoded.load()
    except (UnidentifiedImageError, OSError, SyntaxError,
            Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError('Attachment is not a valid supported image; ask the owner to resend it.') from None
    extension, content_type = FORMATS[fmt]
    # No user-controlled filenames in multipart headers.
    return 'image.' + extension, content_type, data
