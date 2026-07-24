@SETLOCAL
@set PATH=%PATH%;.\bin\
@echo off

sdas8051 -o ident_checksum.rel ident_checksum.asm
sdld -i ident_checksum.rel
tools\hex2bin.py ident_checksum.ihx ident_checksum.bin

sdas8051 -o ata_c_sce_security_control.rel ata_c_sce_security_control.asm
sdld -i ata_c_sce_security_control.rel
tools\hex2bin.py ata_c_sce_security_control.ihx ata_c_sce_security_control.bin

patch_fw.py V3.72.bin V3.72_patched.bin

@del *.rel
@del *.ihx
@del ident_checksum.bin
@del ata_c_sce_security_control.bin
