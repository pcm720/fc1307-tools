; ATA_C_SCE_SECURITY_CONTROL implementation
; HDD ID MUST be placed in the same page as the code
	.area CODE (ABS)
	.org 0xb200        ; Place code at 0xb200

; Constants
    wdtrst = 0xa6
    wcon   = 0xa7
    saddr  = 0xa9
;

;
; Custom handler for ATA command 0x8E (ATA_C_SCE_SECURITY_CONTROL)
;
ata_c_sce_security_control:
    ; Read the next command byte
    mov     r7,    #0x24
    lcall   0x057e
    mov     a,     0xa4

    ; If 0xEC, call ata_sce_identify_drive
    cjne    a,     #0xec,   unimplemented
    lcall   ata_sce_identify_drive
    ret

unimplemented:
    ; Else, call the default command handler (unimplemented command) and return
    lcall   0x83a2
    ret

;
; ATA_SCE_IDENTIFY_DRIVE (0xEC) subcommand handler
;
ata_sce_identify_drive:
    ; Replicate the original IDENTIFY handler behavior
    ; Setup registers for command handling
    clr     0x6c            ; 2d.4 = 0
    lcall   0x05df
                            ; 2d.3 = 2b.1 & 0x1
    mov     c,     0x59
    mov     0x6b,  c

    ; Prepare the data by copying from ROM 0xb000 to XRAM 0x4000
    lcall   copy_hddid
    clr     a

    ; Setup the transfer
	mov     0xa4,   a
	mov     r7,    #0x20
	lcall   0x0575
	clr     a

	; Prepare PIO OUT (?)
	mov     0xa5,   a
	mov     0xa4,   a
	mov     r7,     #0x28
	lcall   0x0575
	clr     a
	mov     0xaa,   a

	; Set transfer data (?)
	mov     saddr,  #0x02
	mov     wcon,   a
	mov     wdtrst, a
	mov     0xa5,   a
	mov     0xa4,   a
	mov     r7,     #0x60
	lcall   0x0575
	clr     a

	; Start the transfer
	mov     0xa4,   a
	mov     0xa5,   #0x02
	mov     wcon,   #0x80
	mov     r7,     #0x64
	lcall   0x0575

	; Wait for PIO to finish
wait_saddr:
	mov     a,     saddr
	jb      a.1,   wait_saddr

	; Wait for the host to finish reading
wait_sync:
	mov     r7,    #0x3c
    lcall   0x057e
    mov     a,     0xa4
    jb      a.3,   wait_sync

    ; Handle sending buffer to host
    mov     r7,    #0x1
    lcall   0x058c
    setb    0x6c            ; 2d.4 = 1
    lcall   0x05df
    ret

;
; Copies HDD ID from ROM @ 0xb000 to XRAM @ 0x4000
;
copy_hddid:
    mov     r5,     #0xb0       ; source page high byte
    mov     r6,     #0x40       ; destination page high byte
    mov     dpl,    #0x00       ; shared low byte
    mov     r2,     #0x02       ; 2 pages
    mov     r3,     #0x00       ; 256 bytes per page
copy_loop:
    mov     dph,    r5          ; select source page
    clr     a
    movc    a,      @a+dptr     ; read from ROM
    mov     dph,    r6          ; select destination page
    movx    @dptr,  a           ; write to XRAM
    inc     dpl                 ; advance shared offset
    djnz    r3,     copy_loop   ; inner loop (256 ×)
    inc     r5                  ; next source page
    inc     r6                  ; next destination page
    djnz    r2,     copy_loop   ; outer loop (2 ×)
    ret
