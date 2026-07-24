# Support for SCE ATA_C_SCE_SECURITY_CONTROL Proprietary Command

Based on the [code](https://gist.github.com/uyjulian/4611fa6c234fb2bbde21fb65747bab95) by uyjulian

## Overview

In firmware 3.72 of the FC1307A, the ATA command dispatch table is located at address 0x9482.

This patch replaces the ATA command 0xC0 (CFA ERASE SECTORS) with a custom handler for the 0x8E command, adding support for PS2 and PSX consoles.

## Technical Details

```c
void ata_cmd_return_null_empty_sector(void)
{  
  FUN_CODE_8062();
  2e.6 = 0;
  DAT_EXTMEM_200b |= 0x10;
  memset(DAT_EXTMEM_4000, 0, 512);
  DAT_SFR_aa = 0;
  if (28.2 != '\0')
    FUN_CODE_2728();
  FUN_CODE_26e7();
  DAT_EXTMEM_200b &= 0xef;
}
```

## Implementation

This patch modifies the ATA command handler entry at address 0x950F to replace command 0xC0 with a custom handler for 0x8E command at address 0xB040 that implements the `ata_cmd_return_null_empty_sector` function.

The custom handler is written in 8051 assembly and performs the following operations:
1. Calls FUN_CODE_8062()
2. Clears bit 6 of 0x2e
3. Sets bit 4 of external memory location 0x200b
4. Fills 512 bytes at external memory location 0x4000 with zeros
5. Sets SFR register 0xaa to 0
6. Conditionally calls FUN_CODE_2728() if the second bit of 0x28 is non-zero
7. Calls FUN_CODE_26e7()
8. Clears bit 4 of external memory location 0x200b
9. Returns

## References

More information and tools:
- https://zenn.dev/mctek/articles/306d1afc153c0b
- https://github.com/amnemonic/fc1307-tools
