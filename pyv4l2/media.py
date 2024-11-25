from __future__ import annotations

import ctypes
import fcntl
import weakref
import os
import glob
import fnmatch
import pyv4l2.uapi as uapi
from .helpers import filepath_for_major_minor
from .enums import MediaEntityFunction, MediaLinkFlag, MediaPadFlag, MediaInterfaceType

__all__ = [
    'MediaObject', 'MediaEntity', 'MediaInterface', 'MediaPad', 'MediaLink',
    'MediaDevice',
    'MediaLinkFlag'
]

class MediaTopology:
    def __init__(self, topology, entities, interfaces, pads, links) -> None:
        self.topology = topology
        self.entities = entities
        self.interfaces = interfaces
        self.pads = pads
        self.links = links


class MediaObject:
    links: list[MediaLink]

    def __init__(self, md: MediaDevice, id: int) -> None:
        self.md = md
        self.id = id

    def _finalize(self):
        self.links = [l for l in self.md.links if self.id in (l.media_link.source_id, l.media_link.sink_id)]


class MediaEntity(MediaObject):
    def __init__(self, md, media_entity: uapi.media_v2_entity) -> None:
        super().__init__(md, media_entity.id)
        self.media_entity = media_entity
        self.name = media_entity.name.decode('ascii')
        self.function = MediaEntityFunction(media_entity.function)
        self.flags = media_entity.flags
        self.pads: list[MediaPad] = None # type: ignore
        self.interface: MediaInterface = None # type: ignore

    def _finalize(self):
        super()._finalize()
        self.pads = [p for p in self.md.pads if p.media_pad.entity_id == self.id]

        ifaces = []

        for ids in [(l.media_link.source_id, l.media_link.sink_id) for l in self.links]:
            for id in ids:
                ob = self.md.find_id(id)

                if not isinstance(ob, MediaInterface):
                    continue

                ifaces.append(ob)

        if len(ifaces) > 1:
            raise RuntimeError('Multiple interfaces for entity')

        if len(ifaces) > 0:
            self.interface = ifaces[0]

    def __repr__(self) -> str:
        return f"MediaEntity({self.id}, '{self.name}')"

    @property
    def pad_links(self) -> list[MediaLink]:
        return [l for p in self.pads for l in p.links]


class MediaInterface(MediaObject):
    def __init__(self, md, media_iface: uapi.media_v2_interface) -> None:
        super().__init__(md, media_iface.id)
        self.media_iface = media_iface
        self.majorminor = (self.media_iface.unnamed_1.devnode.major, self.media_iface.unnamed_1.devnode.minor)
        self.dev_path = filepath_for_major_minor(*self.majorminor)
        self.intf_type = MediaInterfaceType(self.media_iface.intf_type)

    def _finalize(self):        # pylint: disable=useless-parent-delegation
        super()._finalize()

    def __repr__(self) -> str:
        return f'MediaInterface({self.id})'

    @property
    def is_subdev(self):
        return self.media_iface.intf_type == uapi.MEDIA_INTF_T_V4L_SUBDEV

    @property
    def is_video(self):
        return self.media_iface.intf_type == uapi.MEDIA_INTF_T_V4L_VIDEO


class MediaPad(MediaObject):
    def __init__(self, md, media_pad: uapi.media_v2_pad) -> None:
        super().__init__(md, media_pad.id)
        self.media_pad = media_pad
        self.index = media_pad.index
        self.entity: MediaEntity = None # type: ignore

    def _finalize(self):
        super()._finalize()
        self.entity = next(e for e in self.md.entities if e.id == self.media_pad.entity_id)

    def __repr__(self) -> str:
        return f"MediaPad({self.id}, '{self.entity.name}':{self.index})"

    @property
    def is_source(self):
        return (self.media_pad.flags & uapi.MEDIA_PAD_FL_SOURCE) != 0

    @property
    def is_sink(self):
        return (self.media_pad.flags & uapi.MEDIA_PAD_FL_SINK) != 0

    @property
    def is_internal(self):
        return (self.media_pad.flags & uapi.MEDIA_PAD_FL_INTERNAL) != 0

    @property
    def flags(self) -> MediaPadFlag:
        return MediaPadFlag(self.media_pad.flags)


class MediaLink(MediaObject):
    def __init__(self, md, media_link: uapi.media_v2_link) -> None:
        super().__init__(md, media_link.id)
        self.media_link = media_link
        self.flags = media_link.flags
        self.source: MediaObject = None # type: ignore
        self.sink: MediaObject = None # type: ignore

    def _finalize(self):
        super()._finalize()
        self.source = next(e for e in self.md.objects if e.id == self.media_link.source_id)
        self.sink = next(e for e in self.md.objects if e.id == self.media_link.sink_id)

    def __repr__(self) -> str:
        return f'MediaLink({self.id}, {self.source}->{self.sink})'

    @property
    def is_enabled(self):
        return (self.flags & uapi.MEDIA_LNK_FL_ENABLED) != 0

    @property
    def is_immutable(self):
        return (self.flags & uapi.MEDIA_LNK_FL_IMMUTABLE) != 0

    @property
    def source_pad(self) -> MediaPad:
        if isinstance(self.source, MediaPad):
            return self.source
        raise RuntimeError('Source is not a MediaPad')

    @property
    def sink_pad(self) -> MediaPad:
        if isinstance(self.sink, MediaPad):
            return self.sink
        raise RuntimeError('Sink is not a MediaPad')

    def enable(self):
        self._setup(uapi.MEDIA_LNK_FL_ENABLED)

    def disable(self):
        self._setup(0)

    def _setup(self, flags):
        desc = uapi.media_link_desc()
        desc.source.entity = self.source_pad.entity.id
        desc.source.index = self.source_pad.index
        desc.sink.entity = self.sink_pad.entity.id
        desc.sink.index = self.sink_pad.index
        desc.flags = flags

        fcntl.ioctl(self.md.fd, uapi.MEDIA_IOC_SETUP_LINK, desc, False)

        self.flags = flags


class MediaDevice:
    def __init__(self, name: str, key: str = 'path') -> None:
        if key != 'path':
            name = MediaDevice.__find_media_device_by_value(key, name)
            key = 'path'

        self.fd = os.open(name, os.O_RDWR | os.O_NONBLOCK)
        self.__read_device_info()
        self.__read_topology()

        weakref.finalize(self, os.close, self.fd)

    @staticmethod
    def __find_media_device_by_value(key: str, value: str) -> str:
        for path in glob.glob('/dev/media*'):
            try:
                fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
            except OSError:
                continue

            try:
                mdi = uapi.media_device_info()
                fcntl.ioctl(fd, uapi.MEDIA_IOC_DEVICE_INFO, mdi, True)

                device_val = getattr(mdi, key).decode()

                if fnmatch.fnmatch(device_val, value):
                    return path
            finally:
                os.close(fd)

        raise FileNotFoundError(f'No media device "{key}" = "{value}" found')

    def get_device_info(self):
        mdi = uapi.media_device_info()
        fcntl.ioctl(self.fd, uapi.MEDIA_IOC_DEVICE_INFO, mdi, True)
        return mdi

    @staticmethod
    def __decode_kernel_version(v: int):
        a = (v >> 16) & 0xff
        b = (v >> 8) & 0xff
        c = v & 0xff
        return (a, b, c)

    def __read_device_info(self):
        mdi = uapi.media_device_info()
        fcntl.ioctl(self.fd, uapi.MEDIA_IOC_DEVICE_INFO, mdi, True)

        self.driver = mdi.driver.decode()
        self.model = mdi.model.decode()
        self.serial = mdi.serial.decode()
        self.bus_info = mdi.bus_info.decode()
        self.media_version = MediaDevice.__decode_kernel_version(mdi.media_version)
        self.hw_revision = mdi.hw_revision
        self.driver_version = MediaDevice.__decode_kernel_version(mdi.driver_version)


    def __read_topology(self):
        topology = uapi.media_v2_topology()

        fcntl.ioctl(self.fd, uapi.MEDIA_IOC_G_TOPOLOGY, topology, True)

        entities = (uapi.media_v2_entity * topology.num_entities)()
        interfaces = (uapi.media_v2_interface * topology.num_interfaces)()
        pads = (uapi.media_v2_pad * topology.num_pads)()
        links = (uapi.media_v2_link * topology.num_links)()

        topology.ptr_entities = ctypes.addressof(entities)
        topology.ptr_interfaces = ctypes.addressof(interfaces)
        topology.ptr_pads = ctypes.addressof(pads)
        topology.ptr_links = ctypes.addressof(links)

        fcntl.ioctl(self.fd, uapi.MEDIA_IOC_G_TOPOLOGY, topology, True)

        self.topology = MediaTopology(topology, entities, interfaces, pads, links)

        self.objects = \
            [MediaEntity(self, e) for e in self.topology.entities] + \
            [MediaInterface(self, i) for i in self.topology.interfaces] + \
            [MediaPad(self, p) for p in self.topology.pads] + \
            [MediaLink(self, l) for l in self.topology.links]

        for o in self.objects:
            o._finalize()       # pylint: disable=protected-access

    @property
    def entities(self):
        yield from [o for o in self.objects if isinstance(o, MediaEntity)]

    @property
    def pads(self):
        yield from [o for o in self.objects if isinstance(o, MediaPad)]

    @property
    def links(self):
        yield from [o for o in self.objects if isinstance(o, MediaLink)]

    @property
    def interfaces(self):
        yield from [o for o in self.objects if isinstance(o, MediaInterface)]

    def find_id(self, id) -> MediaObject | None:
        return next((o for o in self.objects if o.id == id), None)

    def find_entity(self, name):
        for e in self.entities:
            if fnmatch.fnmatch(e.name, name):
                return e
        return None
