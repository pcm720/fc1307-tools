# Support for SCE ATA_C_SCE_SECURITY_CONTROL Proprietary Command

Based on the [code](https://gist.github.com/uyjulian/4611fa6c234fb2bbde21fb65747bab95) by uyjulian

## Overview

In the FC1307A firmware V3.72, the ATA command dispatch table is located at address 0x9482.

This patch replaces the ATA command 0xC0 (CFA ERASE SECTORS) with a custom handler for the `0x8e` command, adding support for PS2 and PSX consoles.

## Technical Details

To satisfy the HDD security check present in the official SCE modules and PSX DVR, the drive should respond to the ATA_C_SCE_SECURITY_CONTROL ATA_SCE_IDENTIFY_DRIVE (`0x8e 0xec`) command with SCE-specific data retrieved from a special security sector.

However, none of the known implementations check the response contents, so returning a zero-filled buffer is enough.

## Implementation

This patch modifies the ATA command handler entry at address `0x950f` to replace command `0xc0` with a custom handler for the `0x8e` command at address `0xb040` that implements the `ATA_C_SCE_SECURITY_CONTROL` command set.

Currently, only the ATA_SCE_IDENTIFY_DRIVE subcommand is implemented.

## References

More information and tools:
- https://www.psdevwiki.com/ps2/Hard_Drive
- https://zenn.dev/mctek/articles/306d1afc153c0b
- https://github.com/amnemonic/fc1307-tools
