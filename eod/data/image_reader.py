import os
import cv2
from PIL import Image
import numpy as np
from eod.utils.general.registry_factory import IMAGE_READER_REGISTRY
from eod.utils.general.log_helper import default_logger as logger


__all__ = ['FileSystemCVReader', 'FileSystemPILReader']


def get_cur_image_dir(image_dir, idx):
    if isinstance(image_dir, list) or isinstance(image_dir, tuple):
        assert idx < len(image_dir)
        return image_dir[idx]
    return image_dir


class ImageReader(object):
    def __init__(self, image_dir, color_mode, memcached=None):
        super(ImageReader, self).__init__()
        self.image_dir = image_dir
        self.color_mode = color_mode
        self.memcached = memcached
        if self.memcached is not None:
            self.init_memcached()

    def image_directory(self):
        return self.image_dir

    def image_color(self):
        return self.color_mode

    def init_memcached(self):
        from pymemcache.client.base import PooledClient
        host = self.memcached.get('host', '127.0.0.1')
        port = self.memcached.get('port', '11211')
        pool_size = self.memcached.get('pool_size', 4)
        self.client = PooledClient(f'{host}:{port}', max_pool_size=pool_size)
        self.image_shapes = {}

    def hash_filename(self, filename):
        import hashlib
        md5 = hashlib.md5()
        md5.update(filename.encode('utf-8'))
        hash_filename = md5.hexdigest()
        return hash_filename

    def read(self, filename):
        if self.memcached is None:
            return self.fs_read(filename)
        else:
            try:
                hash_filename = self.hash_filename(filename)
                if hash_filename not in self.image_shapes:
                    img = self.fs_read(filename)
                    en_img = cv2.imencode('.jpg', img)[1]
                    self.client.set(hash_filename, en_img.tostring(), noreply=False)
                    self.image_shapes[hash_filename] = img.shape
                else:
                    img = self.client.get(hash_filename)
                    img = np.frombuffer(img, dtype=np.uint8)
                    img = cv2.imdecode(img, cv2.IMREAD_COLOR)
            except Exception as e:
                logger.warning(f"memcached exception {e}, using file read")
                return self.fs_read(filename)
        return img

    def __call__(self, filename, image_dir_idx=0):
        image_dir = get_cur_image_dir(self.image_dir, image_dir_idx)
        filename = os.path.join(image_dir, filename)
        img = self.read(filename)
        return img


@IMAGE_READER_REGISTRY.register('fs_opencv')
class FileSystemCVReader(ImageReader):
    def __init__(self, image_dir, color_mode, memcached=None, to_float32=False):
        super(FileSystemCVReader, self).__init__(image_dir, color_mode, memcached)
        assert color_mode in ['RGB', 'BGR', 'GRAY'], '{} not supported'.format(color_mode)
        if color_mode == 'RGB':
            self.cvt_color = getattr(cv2, 'COLOR_BGR2{}'.format(color_mode))
        else:
            self.cvt_color = None
        self.to_float32 = to_float32

    def fs_read(self, filename):
        assert os.path.exists(filename), filename
        if self.color_mode == 'GRAY':
            img = cv2.imread(filename, 0)
        else:
            img = cv2.imread(filename, cv2.IMREAD_COLOR)
        if self.color_mode == 'RGB':
            img = cv2.cvtColor(img, self.cvt_color)
        if self.to_float32:
            img = img.astype(np.float32)
        return img

    def fake_image(self, *size):
        if len(size) == 0:
            if self.color_mode == 'GRAY':
                size = (512, 512, 1)
            else:
                size = (512, 512, 3)
        return np.zeros(size, dtype=np.uint8)


@IMAGE_READER_REGISTRY.register('fs_pillow')
class FileSystemPILReader(ImageReader):
    def __init__(self, image_dir, color_mode, memcached=None):
        super(FileSystemPILReader, self).__init__(image_dir, color_mode, memcached)
        assert color_mode == 'RGB', 'only RGB mode supported for pillow for now'

    def fake_image(self, *size):
        if len(size) == 0:
            size = (512, 512, 3)
        return Image.new(self.color_mode, size)

    def fs_read(self, filename):
        assert os.path.exists(filename), filename
        img = Image.open(filename).convert(self.color_mode)
        return img


def build_image_reader(cfg_reader):
    return IMAGE_READER_REGISTRY.build(cfg_reader)
