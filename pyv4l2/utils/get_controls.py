#!/usr/bin/env python3

import argparse
import struct
from pprint import pprint

import pyv4l2
from pyv4l2 import uapi
import fcntl, errno

from dataclasses import dataclass, field

@dataclass
class V4lControl:
    id: int = field(init=False)
    type: int = field(init=False)
    name: str = field(init=False)
    minimum: int = field(init=False)
    maximum: int = field(init=False)
    step: int = field(init=False)
    default_value: int = field(init=False)
    flags: int = field(init=False)
    elem_size: int = field(init=False)
    elems: int = field(init=False)
    nr_of_dims: int = field(init=False)
    dims: list = field(init=False)
    menu_items: dict = field(init=False)

    def from_ext_ctrl(self, ctrl: uapi.v4l2_query_ext_ctrl):
        self.id = ctrl.id
        self.type = ctrl.type
        self.name = ctrl.name.decode("utf-8")
        self.minimum = ctrl.minimum
        self.maximum = ctrl.maximum
        self.step = ctrl.step
        self.default_value = ctrl.default_value
        self.flags = ctrl.flags
        self.elem_size = ctrl.elem_size
        self.elems = ctrl.elems
        self.nr_of_dims = ctrl.nr_of_dims
        self.dims = struct.unpack("IIII", bytes(ctrl.dims))
        self.menu_items = None

    def type_str(self):
        typenames = {
        uapi.V4L2_CTRL_TYPE_INTEGER: "INTEGER_CTRL",
        uapi.V4L2_CTRL_TYPE_BOOLEAN: "BOOLEAN_CTRL",
        uapi.V4L2_CTRL_TYPE_MENU: "MENU_CTRL",
        uapi.V4L2_CTRL_TYPE_BUTTON: "BUTTON_CTRL",
        uapi.V4L2_CTRL_TYPE_INTEGER64: "INTEGER64_CTRL",
        uapi.V4L2_CTRL_TYPE_CTRL_CLASS: "CTRL_CLASS_CTRL",
        uapi.V4L2_CTRL_TYPE_STRING: "STRING_CTRL",
        uapi.V4L2_CTRL_TYPE_BITMASK: "BITMASK_CTRL",
        uapi.V4L2_CTRL_TYPE_INTEGER_MENU: "INTEGER_MENU_CTRL"
        }
        return typenames[self.type]

def get_controls(dev: pyv4l2.VideoDevice|pyv4l2.SubDevice):
    ctrl_id = uapi.V4L2_CTRL_FLAG_NEXT_CTRL
    current_class = "User Controls"
    controls = {current_class: []}

    while True:
        ctrl = uapi.v4l2_query_ext_ctrl()
        ctrl.id = ctrl_id
        try:
            fcntl.ioctl(dev.fd, uapi.VIDIOC_QUERY_EXT_CTRL, ctrl, True)
        except OSError:
            break

        if ctrl.type == uapi.V4L2_CTRL_TYPE_CTRL_CLASS:
            current_class = ctrl.name.decode("utf-8")
            controls[current_class] = []

        ctrlv = V4lControl()
        ctrlv.from_ext_ctrl(ctrl)
        if ctrl.type == uapi.V4L2_CTRL_TYPE_MENU or ctrl.type == uapi.V4L2_CTRL_TYPE_INTEGER_MENU:
            querymenu = uapi.v4l2_querymenu()
            querymenu.id = ctrl.id
            options = {}
            for i in range(ctrl.minimum, ctrl.maximum + 1):
                querymenu.index = i
                try:
                    print("trying ctrl")
                    fcntl.ioctl(dev.fd, uapi.VIDIOC_QUERYMENU, querymenu, True)
                    print("finished with contr")
                    options[i] = querymenu.name.decode("utf-8") if ctrl.type == uapi.V4L2_CTRL_TYPE_MENU else int.from_bytes(querymenu.name, "little")
                    print(f"option: {options[i]}, {querymenu.id} {querymenu.name}")
                except OSError as e:
                    print(f"error: {e}")
                    # querymenu can fail for given index, but there can
                    # still be more valid indexes
                    pass
            if options:
                ctrlv.menu_items = options

        controls[current_class].append(ctrlv)
        ctrl_id = ctrl.id | uapi.V4L2_CTRL_FLAG_NEXT_CTRL
    return controls


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('device', help='video device')
    args = parser.parse_args()

    dev = pyv4l2.SubDevice(args.device)
    controls = get_controls(dev)
    for k, v in controls.items():
        print(f"Class: {k}")
        for ctrl in v:
            print(f"  {ctrl.name}: {ctrl.minimum} - {ctrl.maximum} (default: {ctrl.default_value}) type:{ctrl.type_str()}")
            if ctrl.type == uapi.V4L2_CTRL_TYPE_MENU:
                print(f"    Menu items: {ctrl.menu_items}")
    # pp = {k, [x.name for x in v] for (k,v) in controls.items()}
    # pprint(pp)


if __name__ == '__main__':
    main()
