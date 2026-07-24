; Custom handler for ATA command 0x8E (ATA_C_SCE_SECURITY_CONTROL)

	.area CODE (ABS)
	.org 0xB040        ; Place code at 0xB040

ata_cmd_return_null_empty_sector:
	; Call FUN_CODE_8062()
	lcall	0x8062

	; 2e.6 = 0  (Clear bit 6 of 0x2e)
	clr 0x76

	; DAT_EXTMEM_200b |= 0x10  (Set bit 4 of extmem location 0x200b)
	mov	dptr, #0x200b
	movx	a, @dptr
	orl	a, #0x10
	movx	@dptr, a

	; memset(DAT_EXTMEM_4000, 0, 512)
	; Set DPTR to 0x4000
	mov	dph, #0x40
	mov	dpl, #0x00
	; Loop 512 times to write zeros
	mov	r0, #0x02	; Counter high byte (2)
	mov	r1, #0x00	; Counter low byte (0)
	mov	a, #0x00	; Value to write
clear_loop:
	movx	@dptr, a
	inc	dptr
	djnz	r1, clear_loop
	djnz	r0, clear_loop

	; DAT_SFR_aa = 0
	mov	0xaa, #0x00

	; if (28.2 != '\0') FUN_CODE_2728()
	mov	a, 0x28
	jz	skip_2728
	lcall	0x2728

skip_2728:
	; FUN_CODE_26e7()
	lcall	0x26e7

	; DAT_EXTMEM_200b &= 0xef  (Clear bit 4 of extmem location 0x200b)
	mov	dptr, #0x200b
	movx	a, @dptr
	anl	a, #0xef
	movx	@dptr, a

	; Return
	ret
