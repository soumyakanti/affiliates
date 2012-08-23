from StringIO import StringIO

from django.conf import settings
from django.core.files.uploadedfile import InMemoryUploadedFile

import commonware
import requests
from celery.decorators import task
from PIL import Image, ImageDraw

from facebook.models import FacebookBannerInstance, FacebookClickStats
from facebook.utils import current_hour
from shared.utils import get_object_or_none


log = commonware.log.getLogger('a.facebook')


@task
def add_click(banner_instance_id):
    """Add a click to the specified banner instance."""
    banner_instance = get_object_or_none(FacebookBannerInstance,
                                         id=banner_instance_id)
    if banner_instance is not None:
        banner_instance.total_clicks += 1
        banner_instance.save()

        stats, created = (FacebookClickStats.objects
                          .get_or_create(hour=current_hour(),
                                         banner_instance=banner_instance))
        stats.clicks += 1
        stats.save()


@task
def generate_banner_instance_image(banner_instance_id):
    """
    Create an image for a banner image by adding the user's profile image to the
    banner image.
    """
    banner_instance = get_object_or_none(FacebookBannerInstance,
                                         id=banner_instance_id)
    if banner_instance is not None:
        banner_image_file = banner_instance.banner.image

        # Grab the user's photo from Facebook
        try:
            r = requests.get(banner_instance.user.picture_url)
        except requests.exceptions.RequestException, e:
            log.error('Error downloading photo for user %s: %s' %
                      (banner_instance.user.id, e))
            return

        try:
            user_image = Image.open(StringIO(r.content))
            user_image.load()
            banner_image = Image.open(banner_image_file)
            banner_image.load()
        except ValueError, e:
            log.error('Error loading images for banner instance %s: %s' %
                      (banner_instance.id, e))
            return

        # Generate the actual image.
        custom_image = banner_image.copy()

        # Calculate and draw border box.
        coords = settings.FACEBOOK_CUSTOM_IMG_COORDS
        border = settings.FACEBOOK_CUSTOM_IMG_BORDER
        box_coords = (coords[0] - border['width'], coords[1] - border['width'],
                      coords[0] + 49 + border['width'],
                      coords[1] + 49 + border['width'])
        ImageDraw.Draw(custom_image).rectangle(box_coords, fill=border['color'])

        # Draw user avatar
        custom_image.paste(user_image, coords)

        # Store the image in memory so we can save it to the model.
        io = StringIO()
        custom_image.save(io, format='PNG')
        custom_image_file = InMemoryUploadedFile(io, None, 'custom_image.png',
                                                 'image/png', io.len, None)
        banner_instance.custom_image.save('custom_image.png', custom_image_file)
