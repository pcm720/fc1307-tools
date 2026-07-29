#!/usr/bin/env python3
"""
Script Name: fc1307_fw_dump.py

Description:
    Dumps firmware from FC1307(A) based devices. You can use USB->IDE adapter but it must be able to pass "features" flag.
    You can check this by issuing  `sg_raw -r 512 /dev/sda 85 08 0e 00 04 00 01 00 00 00 00 00 00 00 fe 00` command.
    If you get buffer starting with "FC-1307 2012_12_20-BANK..." then your device can't handle ATA "features" flag.

Author:
    Adam Mnemonic
    Ivan V

GitHub:
    https://github.com/pcm720/fc1307-tools

License:
    This project is licensed under a permissive "do whatever you want" license.
    You are free to use, modify, distribute, and sell this software without restriction.

    Attribution is appreciated but not required.
    https://github.com/pcm720/fc1307-tools

Created:
    2026-04-11

Last Modified:
    2026-04-29
"""

import os
import sys
import fcntl
import ctypes


SG_IO = 0x2285              # SG_IO ioctl number
SG_DXFER_FROM_DEV = -3      # Data transfer direction

class sg_io_hdr_t(ctypes.Structure):
    _fields_ = [
        ("interface_id", ctypes.c_int),
        ("dxfer_direction", ctypes.c_int),
        ("cmd_len", ctypes.c_ubyte),
        ("mx_sb_len", ctypes.c_ubyte),
        ("iovec_count", ctypes.c_ushort),
        ("dxfer_len", ctypes.c_uint),
        ("dxferp", ctypes.c_void_p),
        ("cmdp", ctypes.c_void_p),
        ("sbp", ctypes.c_void_p),
        ("timeout", ctypes.c_uint),
        ("flags", ctypes.c_uint),
        ("pack_id", ctypes.c_int),
        ("usr_ptr", ctypes.c_void_p),
        ("status", ctypes.c_ubyte),
        ("masked_status", ctypes.c_ubyte),
        ("msg_status", ctypes.c_ubyte),
        ("sb_len_wr", ctypes.c_ubyte),
        ("host_status", ctypes.c_ushort),
        ("driver_status", ctypes.c_ushort),
        ("resid", ctypes.c_int),
        ("duration", ctypes.c_uint),
        ("info", ctypes.c_uint),
    ]

def read_fw(fd,addr):
    addr_lo = addr & 0xFF
    addr_hi = (addr >> 8) & 0xFF

    # Assuming addr_lo and addr_hi are defined as integers (0x00 - 0xFF)
    cdb = (ctypes.c_ubyte * 16)(
        0x85,     # [0] SCSI Opcode: ATA PASS-THROUGH (16)
        0x08,     # [1] Protocol: PIO Data-In (16-bit)
        0x0E,     # [2] Flags: T_DIR=1 (Inbound), BYTE_BLOCK=1, CK_COND=0
        0x00,     # [3] OFF_LINE (0) / Features (High) (0)
        0x04,     # [4] Features (Low)
        0x00,     # [5] Sector Count (High)
        0x01,     # [6] Sector Count (Low)
        0x00,     # [7] LBA Low (High)
        addr_lo,  # [8] LBA Low (Low) -> addr_lo
        0x00,     # [9] LBA Mid (High)
        addr_hi,  # [10] LBA Mid (Low) -> addr_hi
        0x00,     # [11] LBA High (High)
        0x00,     # [12] LBA High (Low)
        0x00,     # [13] Device Register
        0xFE,     # [14] ATA Command: 0xFE Vendor Command
        0x00      # [15] Control byte / Reserved
    )


    data_buf = ctypes.create_string_buffer(512)
    sense_buf = ctypes.create_string_buffer(32)

    io_hdr = sg_io_hdr_t()
    io_hdr.interface_id    = ord('S')
    io_hdr.dxfer_direction = SG_DXFER_FROM_DEV
    io_hdr.cmd_len         = 16
    io_hdr.mx_sb_len       = len(sense_buf)
    io_hdr.dxfer_len       = 512
    io_hdr.dxferp          = ctypes.addressof(data_buf)
    io_hdr.cmdp            = ctypes.addressof(cdb)
    io_hdr.sbp             = ctypes.addressof(sense_buf)
    io_hdr.timeout         = 5000  # milliseconds

    try:
        # Send command
        fcntl.ioctl(fd, SG_IO, io_hdr)

        # Check status
        if io_hdr.status != 0:
            print("SCSI Status:", io_hdr.status)
            print("Sense Data:", bytes(sense_buf[:io_hdr.sb_len_wr]).hex())
        else:
            print('.',end='',flush=True)

        data = bytes(data_buf)
        return data
    except:
        print(f"\n[!] IOCTL Runtime Failure at address {hex(addr)}: {e}")


if __name__ == "__main__":
    if len(sys.argv)!=3: print(f'Error!\nUsage: {os.path.basename(sys.argv[0])} </dev/sdaX> <out_rom_file.bin>', file=sys.stderr) ; exit(1)

    binfile = open(sys.argv[2],'wb')
    fd = os.open(sys.argv[1], os.O_RDWR)
    for i in range(0,0x10000,0x200):
        data = read_fw(fd,i)
        binfile.write(data)
    print()
    os.close(fd)
    binfile.close()
