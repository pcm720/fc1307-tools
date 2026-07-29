import os, sys
import binascii


def calc_chcksum(bin_content):
    if len(bin_content)!=0x4000:
        return None
    chcecksum=0
    for offset in range(0,len(bin_content)-2,2):
        chcecksum = (chcecksum + int.from_bytes(bin_content[offset:offset+2],byteorder='little') ) & 0xFFFF
    return (0x10000 - chcecksum) & 0xFFFF, int.from_bytes(bin_content[-2:],byteorder='little')

#----------------------------------------------------------------------------------------------------------

bin = bytearray( open(sys.argv[1],'rb').read() )

if binascii.crc32(bin)!= 0xe35c3e58:
    exit('Error: CRC!=e35c3e58. Please provide unmodified V3.72 firmware.')

#
# Patch infinite loop at BOOT (Checking pins P1.0 - P1.3)
#
bin[0x3CE:0x3D0] = b'\x80\x00'
bin[0x3DA:0x3DC] = b'\x80\x00'

#
# ident_checksum.asm
# Replace call to function at address @0x2015 to our custom at address 0xaf00 inside ATA ECh command handler
#
# if bin[0x8223:0x8226] == b'\x12\x20\x15': bin[0x8223:0x8226] = b'\x12\xaf\x00'
if bin[0x8226:0x8226+3] == b'\xE4\xF5\xA4':
    bin[0x8226:0x8226+3] = b'\x12\xaf\x00'
else:
    exit('Can\'t patch @0x8226')

# Insert our custom code inside empty area at @0xaf00
code=open('ident_checksum.bin','rb').read()
bin[0xaf00:0xaf00+len(code)] = code

#
# ata_c_sce_security_control.asm
# Patch ATA command dispatch table - Redirect command 0xC0 to our custom handler
#
# Dispatch table is at 0x9482, each entry is 3 bytes (<2-byte handler address> <1-byte command>)
# We'll replace command 0xC0 with 0x8E and point it to our custom handler at 0xb200
# Command 0xC0 slot is at offset 0x950F
bin[0x950F:0x950F+3] = b'\xb2\x00\x8e'

# Insert our ATA command 0x8E handler inside empty area at @0xb200
code=open('ata_c_sce_security_control.bin','rb').read()
bin[0xb200:0xb200+len(code)] = code

# Inject HDD ID
try:
    hddid = open('hddid.bin','rb').read()
    if len(hddid) == 0x200:
        print("Using the provided HDD ID")
        bin[0xb000:0xb200] = hddid
    else:
        raise ValueError("Unexpected HDD ID length")
except:
    print("Using nulled HDD ID")
    bin[0xb000:0xb1ff] = [0] * (0x1ff)

#
# Replace revision number and device name
#
bin[0x3f00:0x3f00+0x8] = b'Rev3.72A'.ljust(0x8)
bin[0x3f32:0x3f32+0x28] = b'FC1307A SD-ATA Adapter (PS2-compatible)'.ljust(0x28)

# Fix checksums
chsm_calc, chsm_stored = calc_chcksum(bin[0x0000:0x4000]);  bin[0x3FFE:0x4000] =bytes([chsm_calc&0xFF,(chsm_calc>>8)&0xFF])
chsm_calc, chsm_stored = calc_chcksum(bin[0x4000:0x8000]);  bin[0x7FFE:0x8000] =bytes([chsm_calc&0xFF,(chsm_calc>>8)&0xFF])
chsm_calc, chsm_stored = calc_chcksum(bin[0x8000:0xC000]);  bin[0xBFFE:0xC000] =bytes([chsm_calc&0xFF,(chsm_calc>>8)&0xFF])
chsm_calc, chsm_stored = calc_chcksum(bin[0xC000:0x10000]); bin[0xFFFE:0x10000]=bytes([chsm_calc&0xFF,(chsm_calc>>8)&0xFF])


# save to file
open(sys.argv[2],'wb').write(bin)
print(f'Saved patched file, with corrected checksums to {sys.argv[2]}. New file checksum: {binascii.crc32(bin):08X}')
