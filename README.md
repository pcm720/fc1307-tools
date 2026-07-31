# FC1307 Tools

This fork of [the original repository](https://github.com/amnemonic/fc1307-tools) provides tools to dump, patch, and flash firmware for this chip, with special focus on improving compatibility with PlayStation 2 and PSX DESR.

## ATA_C_SCE_SECURITY_CONTROL support for PS2/PSX DESR

The custom firmware includes a patch that adds support for the proprietary SCE security commands required by PSX DESR models. This patch:

1. Implements the `ATA_C_SCE_SECURITY_CONTROL` command (0x8E)
2. Handles the `ATA_SCE_IDENTIFY_DRIVE` subcommand (0xEC)
3. Provides the necessary security responses for PSX compatibility
4. Allows using custom HDD IDs for identification

For technical details, see [ata_c_sce_security_control.md](patches/ata_c_sce_security_control.md)

### HDD ID

The patch supports custom HDD IDs for use with your own PSX DESR HDD dumps (untested).  
To use a custom ID:

1. Place a 512-byte `hddid.bin` file with your HDD ID in the `patches` directory
2. Rebuild the firmware as described below

If no custom ID is provided, a null-filled buffer will be used, which is enough to satisfy the security check.

## Prerequisites

- Linux system (required for low-level ATA access)
- Python 3.x
- sg3_utils package (`sudo apt install sg3-utils`)
- FC1307A-based device connected via USB-to-IDE adapter
- Compatible USB-to-IDE adapter that properly handles ATA features

## Flashing Instructions

### Warning
Flashing firmware carries risk. If an incorrect or incompatible firmware is flashed, the device may become unresponsive and require external SPI flashing to recover. Ensure you understand the risks before proceeding.

### 1. Check Adapter Compatibility

First, verify your USB-to-IDE adapter can properly handle ATA features:

For 12-byte SCSI command descriptor block:
```bash
sudo sg_raw -r 512 /dev/sdX a1 08 0e 04 00 00 00 00 00 FE 00 00
```

For 16-byte SCSI command descriptor block:
```bash
sudo sg_raw -r 512 /dev/sdX 85 08 0e 00 04 00 01 00 00 00 00 00 00 00 fe 00
```

Some adapters only support 16-byte CDBs, so try both.

If you receive a buffer starting with "FC-1307 2012_12_20-BANK...", your adapter cannot handle the required ATA features.

### 2. Build Custom Firmware

Navigate to the `patches` directory and run the build script:

```bash
cd patches
./build_all.sh
```

This will generate a patched firmware file `V3.72_patched.bin` in the `patches/` directory.

### 3. Flash the Firmware

Flash the custom firmware using one of the provided scripts, depending on your adapter compatibility:

For adapters that work with 12-byte SCSI commands:
```bash
sudo python3 fc1307_fw_write.py /dev/sdX patches/V3.72_patched.bin
```

For adapters that require 16-byte SCSI commands:
```bash
sudo python3 fc1307_fw_write_16.py /dev/sdX patches/V3.72_patched.bin
```

Replace `/dev/sdX` with your actual device path.

The flashing process will:
1. Clear the SPI flash
2. Write the firmware in 512-byte chunks
3. Display progress indicators during the write process

### 4. Verification

After flashing, you can verify the firmware by reading it back using the appropriate dump script:

For 12-byte SCSI commands:
```bash
sudo python3 fc1307_fw_dump.py /dev/sdX dumped_firmware.bin
```

For 16-byte SCSI commands:
```bash
sudo python3 fc1307_fw_dump_16.py /dev/sdX dumped_firmware.bin
```

Be sure to power cycle the adapter for the new firmware to apply.

## Recovery

If flashing fails or renders the device unresponsive:

1. The FC1307A has a failsafe bootloader that should allow re-flashing
2. If the firmware is valid, but your patches render the FC1307A completely unresponsive, external SPI flashing will be required
3. Use an SPI flasher to restore the FC1307A's SPI flash

## Credits
- Adam Mnemonic for the initial 3.72 reverse engineering that made this possible
- uyjulian for suggesting a way to patch FC1307A firmware for SCE security commands
- MCtek for FC1307A [reverse-engineering efforts](https://zenn.dev/mctek/articles/306d1afc153c0b)
