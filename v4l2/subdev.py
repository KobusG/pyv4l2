import ctypes
import errno
import fcntl
import v4l2

class SubDevice:
    def __init__(self, entity: v4l2.MediaEntity) -> None:
        self.entity = entity
        assert(entity.interface.is_subdev)
        self.file = open(entity.interface.dev_path)
        self.fd = self.file.fileno()

    def get_format(self, which, pad, stream=0):
        fmt = v4l2.v4l2_subdev_format()
        fmt.pad = pad
        fmt.stream = stream
        fmt.which = which
        fcntl.ioctl(self.fd, v4l2.VIDIOC_SUBDEV_G_FMT, fmt, True)
        return fmt

    def get_routes(self):
        routing = v4l2.v4l2_subdev_routing()

        try:
            fcntl.ioctl(self.fd, v4l2.VIDIOC_SUBDEV_G_ROUTING, routing, True)

            routes = (v4l2.v4l2_subdev_route * routing.num_routes)()
            routing.routes = ctypes.addressof(routes)

            fcntl.ioctl(self.fd, v4l2.VIDIOC_SUBDEV_G_ROUTING, routing, True)

        except OSError as e:
            if e.errno == errno.ENOTTY:
                routes = (v4l2.v4l2_subdev_route * 0)()
            else:
                raise

        return routes


class VideoDevice:
    def __init__(self, entity: v4l2.MediaEntity) -> None:
        self.entity = entity
        assert(entity.interface.is_video)
        self.file = open(entity.interface.dev_path)
        self.fd = self.file.fileno()

    def get_format(self):
        fmt = v4l2.v4l2_format()
        fmt.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE
        fcntl.ioctl(self.fd, v4l2.VIDIOC_G_FMT, fmt, True)
        return fmt
