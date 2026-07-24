#!/bin/bash
export PATH=./bin:$PATH

# Check if required tools are available
if ! command -v sdas8051 &> /dev/null; then
    echo "Error: sdas8051 not found. Please install the ASxxxx Assembler package."
    exit 1
fi

if ! command -v sdld &> /dev/null; then
    echo "Error: sdld not found. Please install the ASxxxx Assembler package."
    exit 1
fi

# Assemble ident_checksum.asm
echo "Assembling ident_checksum.asm..."
sdas8051 -o ident_checksum.rel ident_checksum.asm
if [ $? -ne 0 ]; then
    echo "Error assembling ident_checksum.asm"
    exit 1
fi

sdld -i ident_checksum.rel
if [ $? -ne 0 ]; then
    echo "Error linking ident_checksum.rel"
    exit 1
fi

python3 tools/hex2bin.py ident_checksum.ihx ident_checksum.bin
if [ $? -ne 0 ]; then
    echo "Error converting ident_checksum.ihx to bin"
    exit 1
fi

# Assemble our custom ATA handler
echo "Assembling ata_c_sce_security_control.asm..."
sdas8051 -o ata_c_sce_security_control.rel ata_c_sce_security_control.asm
if [ $? -ne 0 ]; then
    echo "Error assembling ata_c_sce_security_control.asm"
    exit 1
fi

sdld -i ata_c_sce_security_control.rel
if [ $? -ne 0 ]; then
    echo "Error linking ata_c_sce_security_control.rel"
    exit 1
fi

python3 tools/hex2bin.py ata_c_sce_security_control.ihx ata_c_sce_security_control.bin
if [ $? -ne 0 ]; then
    echo "Error converting ata_c_sce_security_control.ihx to bin"
    exit 1
fi

# Apply patches
echo "Applying firmware patches..."
python3 patch_fw.py V3.72.bin V3.72_patched.bin
if [ $? -ne 0 ]; then
    echo "Error patching firmware"
    exit 1
fi

# Clean up
rm -f *.rel *.ihx ident_checksum.bin ata_c_sce_security_control.bin

echo "Build completed successfully!"
