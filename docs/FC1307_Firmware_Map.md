# FC1307A V3.72 Firmware — Comprehensive Reverse-Engineering Map

**This document was generated from binary analysis of V3.72.bin by an LLM with a lot of hand-holding and reiterations.**  
**Do not trust anything in this document and take everything with a pound of salt**

---

## 1. Architecture Overview

The FC1307A is an SD-to-IDE bridge built around an 8051-compatible MCU core with an on-chip **ATA engine**. The **main firmware image (64 KiB)** is stored on an **external SPI flash chip**.

```
+--------+     +----------------+     +------------------+     +--------+
|  Host  |<--->|   ATA Engine   |<--->|  Buffer RAM      |<--->| SD Card|
| (IDE)  |     |  (autonomous)  |     |  (XRAM pages)    |     | (SPI)  |
+--------+     +----------------+     +------------------+     +--------+
                    ^                           ^
                    |                           |
                 8051 SFRs               8051 MOVX
              (command, status,            (sector buffers,
               taskfile)                  scratch, IDENTIFY data)
                    ^
                    |
              +-----------+
              | SPI Flash |  <-- 64 KiB firmware image (external)
              +-----------+
```

**Reset vector:** `0x0000` → `SJMP 0x001F`

### 1.1 Boot Sequence

```
Reset → Clear IRAM/SFRs → SJMP 0x0311
  |
  v
0x0311: Check XRAM "BANK" signature at 0x4202
  |
  v
0x0360: Issue SPI READ cmd 0x03, addr=0x00004000, size inferred
  |       (the 0x0360 code sequence writes to SPI controller regs only; no
  |        explicit XRAM destination pointer is set before the read command.
  |        Destination — whether XRAM buffer, DMA, or controller-internal —
  |        is inferred from later controller behavior, not explicit setup.)
  v
0x03BF: Check P1 pins (0x90-0x93) for hardware strapping
  |       P1.0-1.2 must be HIGH, P1.3 must be HIGH
  |       P1.3 LOW → infinite loop at 0x03CE (board-specific hang)
  v
0x03DC: EEPROM signature check via 0x2FE0
  v
0x03FF: Enter main polling loop
```

---

## 2. Memory Map

### 2.1 SPI Flash (External, 64 KiB)

The FC1307 uses an external SPI flash chip connected to the same `0x6000`–`0x6010` controller interface as the SD card. The SPI flash stores the **64 KiB firmware image** plus configuration data.

**Verified SPI flash operations:**

| Command | Opcode | Who Uses It | Purpose |
|---------|--------|-------------|---------|
| READ | `0x03` | Init (`0x0360`), SD ISR (`0x0903`), `0xFE` FEATURES=0x04 | Read firmware/data from SPI flash |
| FAST READ | `0x0B` | `0xFE` FEATURES=0x05 | Fast read with byte-address mode |
| PAGE PROGRAM | `0x02` | `0xFE` FEATURES=0x0B/0x0D | Write 512B to SPI flash |
| SECTOR ERASE | `0x20` | `0xFE` FEATURES=0x1A | Erase 4KB sector |
| BLOCK ERASE | `0xD8` | `0xFE` FEATURES=0x1B | Erase 64KB block |
| CHIP ERASE | `0xC7` | `0xFE` FEATURES=0x1C | Erase entire chip |
| WRSR | `0x01` | `0xFE` FEATURES=0x17 | Write status register |
| RDSR | `0x05` | `0x0259` helper, `0xFE` FEATURES=0x16 | Read status register |
| WREN | `0x06` | `0x027B` helper | Write enable |
| WRDI | `0x04` | `0x0293` helper | Write disable |

> **All SPI write/erase opcodes are ONLY issued from the `0xFE` FEATURES dispatch table** (`0x27E3`). There is no autonomous SD card path that triggers SPI flash programming. See `fc1307_fw_write.py` for the host-side protocol.

### 2.2 XRAM (External RAM / On-chip buffer SRAM)

The FC1307 uses a non-standard 8051 with on-chip XRAM mapped to `0x0000`–`0x7FFF` (or similar). The firmware heavily references these regions:

| Region | Inferred Use |
|--------|-------------|
| `0x1104` | Engine configuration register (written during init: `ORL 0x1104, #0x02`) |
| `0x2000`–`0x2026` | ATA command engine status / mailbox region. `0x2000`, `0x2002`, `0x2006`, `0x2009`, `0x200B` are frequently accessed. |
| `0x2044` | Polling flag checked in main loop |
| `0x2906` | DMA / transfer parameter staging |
| `0x3???` | (Unknown) |
| `0x4000`–`0x41FF` | **Engine buffer page 2** — 512-byte PIO sector buffer. Used for IDENTIFY DEVICE, READ SECTOR, WRITE SECTOR, READ BUFFER, WRITE BUFFER. During IDENTIFY PIO OUT, the ATA engine sends the full 512 bytes (`0x4000`–`0x41FF`) to the host. |
| `0x4200`–`0x4205` | Signature check region. Init code reads 0x4202–0x4205 looking for "BANK" bytes (`0x42`, `0x41`, `0x4E`, `0x4B`). |
| `0x4400`–`0x4603` | **ATA Security command state**. Holds password/state data for ATA Security commands (0xF1–0xF6). Code at 0x0C93 writes "FC07" signature here; 0x4629 validates it. |
| `0x4628` | Referenced in math routines / security validation |
| `0x5C00`–`0x5C??` | **EEPROM read buffer** (I2C scratch) |
| `0x5E14`–`0x5E15` | EEPROM address staging |
| `0x6000`–`0x6010` | **SD controller registers** (SPI/SD command/status) |

> **Buffer page 2 — runtime protocol markers in DMA/SD paths:**
> In several DMA/SD read paths (functions at `0x2867`, `0x2885`, `0x28E3`, `0x2927`, etc.), the firmware overwrites the first 3 bytes of the buffer with a protocol marker (`0xAA` at `0x4000`, sector count at `0x4001`–`0x4002`) **before** calling the PIO OUT completion stub (`0x26E7`). This is a **runtime overwrite**, not a structural header. It is absent in IDENTIFY, READ BUFFER, and WRITE BUFFER paths.

### 2.3 IRAM (Internal RAM, `0x00`–`0x7F`)

The firmware uses direct-addressed IRAM extensively for global state. Key addresses known from cross-referencing both binary analysis and existing disassembly:

| Address | Name | Type | Purpose |
|---------|------|------|---------|
| `0x20`–`0x2F` | Bit-addressable flags | bits | `bit_20`, `bit_24`, `bit_28`, `bit_2B`, `bit_2D`, `bit_32`, `bit_35`, `bit_36`, `bit_37`, `bit_38`, `bit_3D`, `bit_40`, `bit_42`, `bit_43`, `bit_46`, `bit_47`, `bit_4A`, `bit_4C`, `bit_50`, `bit_51`, `bit_53`, `bit_59`, `bit_5A`, `bit_5D`, `bit_5E`, `bit_5F`, `bit_60`, `bit_6B`, `bit_6C`, `bit_6D`, `bit_6E`, `bit_6F`, `bit_70`, `bit_74`, `bit_76`, `bit_78`, `bit_79` — also `bit_80`–`bit_93` etc. |
| `0x30`–`0x31` | `RAM_30/31` | word | 16-bit sector count / buffer param |
| `0x38` | `RAM_38` | byte | PIO IN counter / sector index |
| `0x42` | `RAM_42` | byte | Error flag / remaining sector count |
| `0x43` | `RAM_43` | byte | Cached dispatch opcode (command byte copied from A4 after engine cmd 0x44). Also holds engine flags. |
| `0x50` | `RAM_50` | byte | Adapter mode selector (0=SPEED, 1=BACKUP, 2=JBOD) |
| `0x53` | `RAM_53` | byte | SD sector address high |
| `0x60` | `RAM_60` | byte | Default sector count (preloaded into TF1) |
| `0x67`–`0x6B` | `RAM_67`-`6B` | bytes | **ISR taskfile snapshot** (cmd, TF0-TF3) |
| `0x6D` | `RAM_6D` | byte | Retry / loop counter |
| `0x70`–`0x71` | `RAM_70/71` | word | Sector count for SD ops |
| `0x72`–`0x78` | `RAM_72`-`78` | bytes | Function argument scratch |
| `0x95`–`0x9B` | `RAM_95`-`9B` | bytes | Math / SD address temporaries |
| `0x99` | `RAM_99` | byte | **Current UDMA mode number** |
| `0x9C`–`0x9F` | | bytes | SD LBA / buffer address temporaries |
| `0xA0`–`0xA7` | | bytes | Register bank 2 / math temporaries |
| `0xA9`–`0xAC` | | bytes | Register bank 2 / SD card addressing |

---

## 3. Interrupt Vectors

| Vector Address | Name | Handler | Description |
|----------------|------|---------|-------------|
| `0x0000` | RESET | `SJMP 0x001F` | Clear IRAM, set SFRs |
| `0x0003` | EXT0 | `LJMP 0x0044` | **Main ATA command ISR** (taskfile snapshot + engine state) |
| `0x000B` | TIMER0 | `LJMP 0x01B4` | Timer 0 ISR (timing / debounce) |
| `0x0013` | EXT1 | `LJMP 0x0217` | SD card controller event ISR |
| `0x001B` | TIMER1 | `LJMP 0x01EB` | Timer 1 ISR (heartbeat/timeout) |
| `0x0023` | UART | `INC R0` (code) | **Not used as ISR** — reused as init code |
| `0x002B` | TIMER2 | `CLR 0x75` (code) | **Not used as ISR** — reused as init code |

**EXT0 ISR (`0x0044`)** is the critical path for ATA commands. It:
1. Pushes ACC and PSW
2. Switches to **register bank 1** (`MOV PSW, #0x08`)
3. Checks `bit_2B`; if clear, skips ahead to taskfile snapshot at `0x013F`
4. If `bit_2B` is set, manages sector addressing state and issues engine commands `0x0C`/`0x6C`
5. At `0x013F`: reads `0xA1` into ACC, masks with `0x03`, and loops while non-zero (waits for both fire and fire+wait bits to clear), then **restores** taskfile from IRAM into SFRs (`0x67→A2`, `0x68→A4`, `0x69→A5`, `0x6A→A6`, `0x6B→A7`), issues `0x08` and `0x44`, copies A4 result to `RAM_43`, **snapshots** taskfile back to IRAM (`A2→0x67`, `A4→0x68`, ... `A7→0x6B` at `0x019E`–`0x01AA`), and clears `bit_2A`
6. Pops registers and returns with `RETI`

**EXT1 ISR (`0x0217`)** handles SD controller events. It:
1. Pushes all registers (ACC, B, DPL, DPH, PSW)
2. Switches to **register bank 3** (`MOV PSW, #0x18`)
3. Disables Timer 0 interrupts (`CLR ET0`)
4. Calls `0x0903` (SD controller event handler)
5. Re-enables Timer 0
6. Pops registers and returns

---

## 4. Standard 8051 + FC1307-Specific SFRs

### 4.1 Standard 8051 SFRs (verified by usage count)

| SFR | Address | Reads | Writes | Role |
|-----|---------|-------|--------|------|
| ACC (`0xE0`) | 0xE0 | 89 | 138 | Accumulator — heavy use |
| B (`0xF0`) | 0xF0 | 33 | 44 | B register / MUL/DIV helper |
| PSW (`0xD0`) | 0xD0 | ? | 8 | Program status word |
| SP (`0x81`) | 0x81 | 0 | 1 | Stack pointer (set to 0xC2 at reset) |
| DPL (`0x82`) | 0x82 | 4 | 291 | Data pointer low — **heavily written** |
| DPH (`0x83`) | 0x83 | 2 | 292 | Data pointer high — **heavily written** |
| TCON (`0x88`) | 0x88 | 0 | 4 | Timer control |
| TMOD (`0x89`) | 0x89 | 0 | 1 | Timer mode |
| TL0 (`0x8A`) | 0x8A | 0 | 10 | Timer 0 low |
| TH0 (`0x8C`) | 0x8C | 0 | 9 | Timer 0 high |
| TL1 (`0x8B`) | 0x8B | 0 | 2 | Timer 1 low |
| TH1 (`0x8D`) | 0x8D | 0 | 2 | Timer 1 high |
| SCON (`0x98`) | 0x98 | 0 | 1 | Serial control |
| IE (`0xA8`) | 0xA8 | 1 | 1 | Interrupt enable (set to `0xCF`) |
| IP (`0xB8`) | 0xB8 | 0 | 1 | Interrupt priority |
| P1 (`0x90`) | 0x90 | 0 | 1 | Port 1 (set to 0xFF) |

### 4.2 FC1307 ATA Engine SFRs (verified)

| SFR | Addr | Reads | Writes | Inferred Name & Function |
|-----|------|-------|--------|--------------------------|
| `0xA1` | A1 | 4 | 1 | **ATA_CTRL** — Write `1`=fire, `2`=fire+wait; bit 1 of register value = busy/readable (firmware reads 0xA1 into ACC, then tests ACC.1; the SFR itself is not bit-addressable) |
| `0xA2` | A2 | ? | ? | **ATA_CMD** — Engine command code + host command latch |
| `0xA4` | A4 | 36 | 115 | **ATA_TF0** — Taskfile Reg 0 (Status/Error). Polled for DRQ (bit 3). |
| `0xA5` | A5 | 14 | 115 | **ATA_TF1** — Taskfile Reg 1 (Sector Count/Features) |
| `0xA6` | A6 | ? | 23 | **ATA_TF2** — Taskfile Reg 2 (LBA Low) |
| `0xA7` | A7 | ? | 33 | **ATA_TF3** — Taskfile Reg 3 (LBA Mid / Cylinder Low) |
| `0xA9` | A9 | 3 | 21 | **ATA_SADDR** — Buffer page / sector index. Values 0,1,2. Bit 1 = busy. |
| `0xAA` | AA | 0 | 29 | **ATA_HADDR** — High address byte (forms {AA, A9} pointer) |

> **Unidentified SFRs** with high activity: `0xFA` (55 writes, 30 reads), `0xB1` (24 reads, 15 writes), `0xB2` (27 writes), `0xB3` (13 writes), `0xB4` (12 writes), `0xFB` (21 writes), `0xAF` (16 reads). These are likely SD controller or auxiliary engine registers.

---

## 5. Function Directory

This table catalogues the most significant subroutines, data tables, and inline stubs decoded from the binary. Caller counts are shown where applicable; entries with `0` callers or `—` are labels, stubs, or dispatch tables reached via JMP/LJMP, not standalone CALL targets.

| Address | Callers | Name / Inferred Purpose | Cross-Refs |
|---------|---------|------------------------|------------|
| `0x0575` | 112 | **ATA_Engine_Fire** | R7 → IRAM 0x74 → 0xA2 (ATA_CMD); write 0x01 to 0xA1 (fire no-wait) |
| `0x057E` | 65 | **ATA_Engine_FireWait** | R7 → IRAM 0x76 → 0xA2 (ATA_CMD); write 0x02 to 0xA1 (fire+wait); busy-wait reads 0xA1 into ACC, polls ACC.1 |
| `0x058C` | 37 | **ATA_Engine_Teardown** | End-of-transfer (R7=1 PIO-OUT, R7=2 PIO-IN) |
| `0x05DF` | 18 | **ATA_Engine_Status** | Refresh host status register (cmd 0x10) |
| `0x0501` | 11 | | Timer/math helper? |
| `0x0523` | 6 | | Timer helper |
| `0x0550` | 6 | | |
| `0x0606` | 12 | | |
| `0x063A` | 17 | **SD_Buffer_Setup**? | Called from `0x07A5` with sector params |
| `0x07A5` | 33 | **SD_Sector_Read_Setup**? | Writes to XRAM 0x200B, sets up 0xB2-0xB6, calls `0x063A` |
| `0x07E2` | 18 | | Called after `0x063A` in read path |
| `0x0903` | 1 | **SD_Controller_Event_Handler** | Called from EXT1 ISR (`0x0217`). Manages XRAM flags (0x2000, 0x200B) and SD controller (0x6000-0x6010) command completion / status. |
| `0x097D` | 8 | | |
| `0x0AEC` | 29 | **Copy_Regs_to_B2B6** | Copies R3/R5/R7/... to IRAM 0xB2-0xB6 |
| `0x0B02` | 6 | | Main command state-machine step |
| `0x120A` | 6 | | |
| `0x1454` | 9 | | |
| `0x145C` | 7 | | |
| `0x14B6` | 7 | | |
| `0x1510` | 4 | | |
| `0x156A` | 4 | | |
| `0x15C4` | 5 | | |
| `0x1694` | 10 | | Math (multiply/divide?) |
| `0x16A9` | 15 | | Math / 32-bit shift? |
| `0x19E4` | 5 | | |
| `0x1E2A` | 22 | **Transfer_Request_Handler** | Moves sector counts into XRAM 0x200B, sets up DMA |
| `0x1EE9` | 4 | | |
| `0x1FD4` | 4 | | |
| `0x2015` | 3 | **IDENTIFY_Build_Data** | Fills `0x4000` with IDENTIFY data (from `0x3DD8` defaults + EEPROM) |
| `0x23AA` | 0 | **IDENTIFY_Load_UDMA_Mask** | Inline label inside IDENTIFY path. Loads UDMA mask from ROM `0x3D2E` into WORD 88 via MOVC. Not a standalone CALL target. |
| `0x2615` | 5 | | Transfer setup helper |
| `0x26B8` | 6 | **Transfer_Complete_DMA** | DMA cleanup path (checks `bit_76`) |
| `0x26E7` | 20 | **Transfer_Complete_PIO** | PIO cleanup path |
| `0x2728` | 25 | **DMA_Out_Setup** | Sets `R7=2`, teardown, then PIO OUT with buffer page 1 |
| `0x2740` | 6 | **DMA_State_Reset** | Clears DMA flag, waits on `bit_28`, zeros buffer params |
| `0x27DE` | 3 | **0xFE_Features_Dispatch** | Reads `RAM_39` (= FEATURES), calls `0x335D` with table at `0x27E3` |
| `0x2847` | 0 | **FE_00_Read_FW_CID** | 0xFE FEATURES=0x00. Reads FW version + SD CID/CSD into buffer, then PIO OUT. No `0xAA` overwrite. |
| `0x2857` | 0 | **FE_01_Stub** | 0xFE FEATURES=0x01. Minimal stub, zero-length PIO OUT. |
| `0x2864` | 0 | **FE_02_SPI_RDMDID** | 0xFE FEATURES=0x02. SPI cmd `0x90` (RDMDID), 2-byte response + `0xAA` header. |
| `0x2882` | 0 | **FE_03_SPI_RDJDID** | 0xFE FEATURES=0x03. SPI cmd `0x9F` (RDJDID), 2-byte response + `0xAA` header. |
| `0x28A0` | 0 | **FE_04_05_SPI_Read** | 0xFE FEATURES=0x04/0x05. SPI read 512B via `0x03` (READ) or `0x0B` (FAST READ). Branch on key. No `0xAA` header. |
| `0x28DD` | 0 | **FE_06_Read_XMEM_Byte** | 0xFE FEATURES=0x06. Read single byte from XRAM `[0x30:0x31]` into buffer `0x4001`. `0xAA` header. |
| `0x2903` | 0 | **FE_07_SPI_Cmd_60** | 0xFE FEATURES=0x07. SPI cmd `0x60` (DUAL_FAST_READ or vendor-specific), status poll, `0xAA` header. |
| `0x293A` | 0 | **FE_08_SPI_Bulk_Read** | 0xFE FEATURES=0x08. Large dual multi-sector read (`0x40` + `0x4040` sectors), `0xAA` header. |
| `0x2BF5` | 4 | | |
| `0x2FD6` | 11 | **Delay_Loop** | Software delay: decrements R7 in a loop |
| `0x2FE0` | 1 | **EEPROM_Check_Signature** | Reads EEPROM at 0xA0, checks "KTC" / 0x00 signatures |
| `0x3028` | 10 | **I2C_Start** | EEPROM I2C start condition (P1.4/P1.5 bitbang) |
| `0x3040` | 12 | **I2C_Stop** | EEPROM I2C stop condition |
| `0x304C` | 13 | **I2C_WriteByte** | EEPROM I2C write byte + ACK read |
| `0x308D` | 1 | **I2C_ReadByte** | EEPROM I2C read byte (MSB-first, 8 bits) |
| `0x30BA` | 2 | **I2C_WriteBit** | Single bit write with clock |
| `0x30CD` | 16 | **EEPROM_Read** | Full I2C EEPROM read transaction |
| `0x3142` | 4 | | |
| `0x318C` | 5 | | |
| `0x31CB` | 4 | | 32-bit multiply / divide helper |
| `0x3256` | 11 | | 32-bit math helper |
| `0x32E8` | 37 | | Math routine (32-bit?) |
| `0x331F` | 40 | | Math / shift routine |
| `0x332B` | 24 | | Math / shift routine |
| `0x3338` | 28 | | Math / shift routine |
| `0x3344` | 8 | | Math routine |
| `0x335D` | 9 | | Opcode-to-handler dispatch lookup |
| `0x3933` | 4 | | |
| `0x4074` | 6 | | |
| `0x423E` | 4 | | |
| `0x424C` | 9 | | |
| `0x48DC` | 12 | | |
| `0x5408` | 11 | | |
| `0x59E4` | 20 | | Bit-shift / power-of-two math |
| `0x61E4` | 7 | | |
| `0x612F` | 5 | | |
| `0x61F5` | 4 | | |
| `0x6520` | 7 | | |
| `0x69E4` | 6 | | |
| `0x6078` | 5 | | |
| `0x8083` | 10 | **PIO_OUT_Prepare** | Issues engine cmd 0x28, reads params into RAM_45 |
| `0x821A` | 1 | **IDENTIFY_PIO_OUT** | Full IDENTIFY handler (sets up buffer page 2, commits PIO OUT) |
| `0x82C9` | 0 | **SET_FEATURES_UDMA_Path** | Label inside 0x8273 handler. UDMA/MWDMA mode selection (no clamping!). Reached by LJMP from within 0x8273, not by external CALL. |
| `0x83A2` | 4 | **Unimplemented_Command** | Sets ABRT, returns error status |
| `0x86C1` | 3 | **PIO_IN_Setup** | Arms PIO IN transfer (buffer page 1) |
| `0x8DFE` | 4 | **PIO_OUT_Begin** | Clears TF0-TF3, fires engine cmd 0x60 |
| `0x9482` | — | **Primary_Dispatch_Table** | 62 entries: `(handler_hi, handler_lo, opcode)` |
| `0x9540` | — | **Cmd_0xEC_IDENTIFY** | `LCALL 0x821A` |
| `0x9544` | — | **Cmd_0xEF_SET_FEATURES** | `LCALL 0x8273` |
| `0x9548` | — | **Cmd_0xC6_SET_MULTIPLE** | `LCALL 0x8376` |
| `0x954C` | — | **Cmd_0x91_INIT_DEVICE_PARAMS** | `LCALL 0x90D9` |
| `0x9550` | — | **Cmd_0x50_FORMAT_TRACK** | `LCALL 0x91EB` |
| `0x9554` | — | **Cmd_0x10_RECALIBRATE_Stub** | `MOV R7, #0x38; LCALL 0x057E; MOV A, 0xA4; JNB 0xE6, 0x9563` — generic status-check stub covering `0x10`–`0x1F` |
| `0x956B` | — | **Cmd_Default_None** | `MOV R7, #0x02` — generic stub covering `0x03`, `0x41`, `0x70`–`0x7F`, `0x99`, `0xE6`, `0xE7`, `0xEA` |
| `0x9571` | — | **Cmd_0x40_READ_VERIFY** | `LCALL 0x941C` |
| `0x9575` | — | **Cmd_0x90_EXEC_DIAG** | `LCALL 0x91A8` |
| `0x9579` | — | **Cmd_STANDBY_Stub** | `LCALL 0x922C` — covers `0x94`, `0x96`, `0xE0`, `0xE2` |
| `0x957D` | — | **Cmd_IDLE_Stub** | `LCALL 0x9234` — covers `0x95`, `0x97`, `0xE1`, `0xE3` |
| `0x9581` | — | **Cmd_CHECK_POWER_Stub** | `LCALL 0x923C` — covers `0x98`, `0xE5` |
| `0x9585` | — | **Cmd_0x87_CFA_TRANSLATE** | `LCALL 0x9255` |
| `0x9589` | — | **Cmd_0xB0_SMART** | `LCALL 0x939C` |
| `0x958D` | — | **Cmd_0xC0_CFA_ERASE** | `LCALL 0x9413` |
| `0x962E` | — | **Inline_Dispatch_Table** | 17 entries (mode-0 dispatch for READ/WRITE) |
| `0x9665` | — | **PIO_Read_EXT_Handler** | READ SECTOR(S) EXT inline stub (`SETB bit_37`, falls through) |
| `0x9667` | — | **PIO_Read_Mult_EXT_Handler** | READ MULTIPLE EXT inline stub (`SETB bit_37`, falls through) |
| `0x9669` | — | **PIO_Read_Handler** | Hot-path READ handler (inline table, opcodes `0x20`, `0x21`, `0xC4`) |
| `0x96A4` | — | **PIO_Write_EXT_Handler** | WRITE SECTOR(S) EXT inline stub (`SETB bit_37`, falls through) |
| `0x96A6` | — | **PIO_Write_CFA_Handler** | CFA WRITE EXT inline stub (`SETB bit_37`, falls through) |
| `0x96A8` | — | **PIO_Write_Handler** | Hot-path WRITE handler (inline table, opcodes `0x30`, `0x31`, `0x38`, `0xC5`) |
| `0x96CB` | — | **DMA_Read_EXT_Handler** | READ DMA EXT (inline table, opcode `0x25`) |
| `0x96CD` | — | **DMA_Read_Handler** | READ DMA / READ DMA no retry (inline table, `0xC8`–`0xC9`) |
| `0x9704` | — | **DMA_Write_EXT_Handler** | WRITE DMA EXT (inline table, opcode `0x35`) |
| `0x9706` | — | **DMA_Write_Handler** | WRITE DMA / WRITE DMA no retry (inline table, `0xCA`–`0xCB`) |
| `0x9591` | — | **Cmd_0xE8_WRITE_BUFFER** | Inline stub (`CLR bit_6C` + …) |
| `0x95BC` | — | **Cmd_0xE4_READ_BUFFER** | Inline stub (`CLR bit_6C` + …) |
| `0x95E7` | — | **Cmd_0xFE_Vendor** | `LCALL 0x8062` |

---

## 6. ATA Command Reference

### 6.1 Primary Dispatch Table (`0x9482`)

Each entry is **3 bytes**: `(handler_hi, handler_lo, opcode)`. The firmware scans this table linearly to find the handler for the host command byte.

| Opcode | Handler | Standard Command | Transfer Type |
|--------|---------|-----------------|---------------|
| `0x03` | `0x956B` | CFA REQUEST EXTENDED ERROR | none |
| `0x10` | `0x9554` | RECALIBRATE / Reserved | none |
| `0x11` | `0x9554` | RECALIBRATE / Reserved | none |
| `0x12` | `0x9554` | RECALIBRATE / Reserved | none |
| `0x13` | `0x9554` | RECALIBRATE / Reserved | none |
| `0x14` | `0x9554` | RECALIBRATE / Reserved | none |
| `0x15` | `0x9554` | RECALIBRATE / Reserved | none |
| `0x16` | `0x9554` | RECALIBRATE / Reserved | none |
| `0x17` | `0x9554` | RECALIBRATE / Reserved | none |
| `0x18` | `0x9554` | RECALIBRATE / Reserved | none |
| `0x19` | `0x9554` | RECALIBRATE / Reserved | none |
| `0x1A` | `0x9554` | RECALIBRATE / Reserved | none |
| `0x1B` | `0x9554` | RECALIBRATE / Reserved | none |
| `0x1C` | `0x9554` | RECALIBRATE / Reserved | none |
| `0x1D` | `0x9554` | RECALIBRATE / Reserved | none |
| `0x1E` | `0x9554` | RECALIBRATE / Reserved | none |
| `0x1F` | `0x9554` | RECALIBRATE / Reserved | none |
| `0x40` | `0x9571` | READ VERIFY SECTOR(S) | none |
| `0x41` | `0x956B` | Reserved / Vendor | none |
| `0x42` | `0x9571` | READ VERIFY SECTOR(S) EXT | none |
| `0x50` | `0x9550` | FORMAT TRACK | PIO |
| `0x70` | `0x956B` | SEEK / Reserved | none |
| `0x71` | `0x956B` | SEEK / Reserved | none |
| `0x72` | `0x956B` | SEEK / Reserved | none |
| `0x73` | `0x956B` | SEEK / Reserved | none |
| `0x74` | `0x956B` | SEEK / Reserved | none |
| `0x75` | `0x956B` | SEEK / Reserved | none |
| `0x76` | `0x956B` | SEEK / Reserved | none |
| `0x77` | `0x956B` | SEEK / Reserved | none |
| `0x78` | `0x956B` | SEEK / Reserved | none |
| `0x79` | `0x956B` | SEEK / Reserved | none |
| `0x7A` | `0x956B` | SEEK / Reserved | none |
| `0x7B` | `0x956B` | SEEK / Reserved | none |
| `0x7C` | `0x956B` | SEEK / Reserved | none |
| `0x7D` | `0x956B` | SEEK / Reserved | none |
| `0x7E` | `0x956B` | SEEK / Reserved | none |
| `0x7F` | `0x956B` | SEEK / Reserved | none |
| `0x87` | `0x9585` | CFA TRANSLATE SECTOR | PIO |
| `0x90` | `0x9575` | EXECUTE DEVICE DIAGNOSTIC | none |
| `0x91` | `0x954C` | INITIALIZE DEVICE PARAMETERS | none |
| `0x94` | `0x9579` | Vendor / STANDBY alias | none |
| `0x95` | `0x957D` | Vendor / IDLE alias | none |
| `0x96` | `0x9579` | Vendor / STANDBY alias | none |
| `0x97` | `0x957D` | Vendor / IDLE alias | none |
| `0x98` | `0x9581` | Vendor / CHECK POWER MODE alias | none |
| `0x99` | `0x956B` | Reserved (generic stub) | none |
| `0xB0` | `0x9589` | SMART | PIO |
| `0xC0` | `0x958D` | CFA ERASE SECTORS | none |
| `0xC6` | `0x9548` | SET MULTIPLE MODE | none |
| `0xE0` | `0x9579` | STANDBY IMMEDIATE | none |
| `0xE1` | `0x957D` | IDLE IMMEDIATE | none |
| `0xE2` | `0x9579` | STANDBY | none |
| `0xE3` | `0x957D` | IDLE | none |
| `0xE4` | `0x95BC` | READ BUFFER | PIO OUT |
| `0xE5` | `0x9581` | CHECK POWER MODE | none |
| `0xE6` | `0x956B` | SLEEP | none |
| `0xE7` | `0x956B` | FLUSH CACHE | none |
| `0xE8` | `0x9591` | WRITE BUFFER | PIO IN |
| `0xEA` | `0x956B` | FLUSH CACHE EXT | none |
| `0xEC` | `0x9540` | **IDENTIFY DEVICE** | **PIO OUT** |
| `0xEF` | `0x9544` | **SET FEATURES** | none |
| `0xFE` | `0x95E7` | Vendor Specific | varies |

> **Note:** The opcodes `0x20`–`0x23`, `0x24`, `0x29`, `0x30`–`0x34`, `0x38`, `0x39`, `0x3C`, `0x3D`, `0xC4`, `0xC5`, `0xCD` are **not** in the primary table. They are dispatched via the inline table at `0x962E` (§6.3) with dedicated handlers (`0x9669`, `0x96A8`, etc.), not the generic `0x956B` stub.

### 6.2 Secondary Dispatch Table (`0x2759`)

This table handles DMA-class opcodes after the primary dispatch has determined a DMA transfer is required.

| Opcode | Handler | Description |
|--------|---------|-------------|
| `0x20` | `0x278F` | READ SECTOR(S) → READ DMA |
| `0x21` | `0x278F` | READ SECTOR(S) → READ DMA |
| `0x24` | `0x278F` | READ SECTOR(S) EXT → READ DMA |
| `0x25` | `0x278D` | **READ DMA EXT** |
| `0x29` | `0x278F` | READ MULTIPLE EXT → READ DMA |
| `0x30` | `0x2796` | WRITE SECTOR(S) → WRITE DMA |
| `0x31` | `0x2796` | WRITE SECTOR(S) → WRITE DMA |
| `0x34` | `0x2796` | WRITE SECTOR(S) EXT → WRITE DMA |
| `0x35` | `0x2794` | **WRITE DMA EXT** |
| `0x39` | `0x2796` | CFA WRITE → WRITE DMA |
| `0xC4` | `0x278F` | READ MULTIPLE → READ DMA |
| `0xC5` | `0x2796` | WRITE MULTIPLE → WRITE DMA |
| `0xC8` | `0x278D` | **READ DMA** |
| `0xC9` | `0x278D` | **READ DMA (no retry)** |
| `0xCA` | `0x2794` | **WRITE DMA** |
| `0xCB` | `0x2794` | **WRITE DMA (no retry)** |

The handlers at `0x278D` and `0x2794` set up DMA flag (`bit 0x76`) and call into the same buffer setup as PIO, but completion goes through `0x26B8` instead of the PIO teardown.

---

### 6.3 Inline Dispatch Table (`0x962E`)

Used by the `0x9602` mode-0 dispatch path (§7.4). This table is embedded inline after the `LCALL 0x335D` at `0x962B`; `0x335D` pops the return address (`0x962E`) as its table base. Format is the same 3-byte `(handler_hi, handler_lo, opcode)` structure as the primary table.

| Opcode | Handler | Standard Command | Transfer Type |
|--------|---------|-----------------|---------------|
| `0x20` | `0x9669` | READ SECTOR(S) | PIO |
| `0x21` | `0x9669` | READ SECTOR(S) | PIO |
| `0x24` | `0x9665` | READ SECTOR(S) EXT | PIO |
| `0x25` | `0x96CB` | READ DMA EXT | DMA |
| `0x29` | `0x9667` | READ MULTIPLE EXT | PIO |
| `0x30` | `0x96A8` | WRITE SECTOR(S) | PIO |
| `0x31` | `0x96A8` | WRITE SECTOR(S) | PIO |
| `0x34` | `0x96A4` | WRITE SECTOR(S) EXT | PIO |
| `0x35` | `0x9704` | WRITE DMA EXT | DMA |
| `0x38` | `0x96A8` | CFA WRITE SECTORS WITHOUT ERASE | PIO |
| `0x39` | `0x96A6` | *(CFA-related)* | PIO |
| `0xC4` | `0x9669` | READ MULTIPLE | PIO |
| `0xC5` | `0x96A8` | WRITE MULTIPLE | PIO |
| `0xC8` | `0x96CD` | READ DMA | DMA |
| `0xC9` | `0x96CD` | READ DMA (no retry) | DMA |
| `0xCA` | `0x9706` | WRITE DMA | DMA |
| `0xCB` | `0x9706` | WRITE DMA (no retry) | DMA |

> **Key insight:** READ/WRITE sector opcodes are **not** in the primary table at `0x9482`. They are dispatched through this inline table by the main polling loop (`0x9602`). The handlers (`0x9669`, `0x96A8`, etc.) are inline code blocks that execute before falling through to common buffer-setup routines.

### 6.4 ATA Command `0xFE` FEATURES Dispatch Table (`0x27E3`)

This table is the **primary dispatch mechanism for ATA vendor command `0xFE`**. The flow is:

```
Host sends ATA cmd 0xFE with FEATURES register value
   ↓
0x95E7 (primary table stub) → LCALL 0x8062
   ↓
0x8062 copies FEATURES/LBA_MID/LBA_HI/SectorCount → ATA engine taskfile (0xA4–0xA7)
   ↓
0x95F3 → LCALL 0x27DE
   ↓
0x27DE reads RAM_39 (= FEATURES register) and calls 0x335D
   ↓
0x335D scans the inline table at 0x27E3 for a matching key and jumps to handler
```

The table is **also** called from the PIO READ handler at `0x278F` and the PIO WRITE handler at `0x27C9`, making it a dual-use dispatch: both the dedicated `0xFE` vendor command path and certain PIO data-transfer paths resolve through the same handler table. The value in `RAM_39` therefore carries FEATURES semantics even during normal PIO.

The `0x335D` generic lookup scans 3-byte `(handler_hi, handler_lo, key)` entries until it finds a matching key, then jumps to the handler. A 4-byte terminator (`00 00 default_hi default_lo`) provides the fallback handler (`0x2FD2`).

| Key (`RAM_39` = FEATURES) | Handler | Description | Direction |
|--------|---------|-------------|-----------|
| `0x00` | `0x2847` | **Read FW Version and SD CID/CSD** — copies firmware version / card ID data into `0x4000`–`0x41FF`, then PIO OUT | R |
| `0x01` | `0x2857` | **?** — minimal handler, PIO OUT zero-length buffer | R |
| `0x02` | `0x2864` | **SPI: Read Manufacturer and Device ID** (RDMDID, `0x90`) — 2-byte response + `0xAA` header at `0x4000`–`0x4002` | R |
| `0x03` | `0x2882` | **SPI: Read JEDEC ID** (RDJDID, `0x9F`) — 2-byte response + `0xAA` header at `0x4000`–`0x4002` | R |
| `0x04` | `0x28A0` | **SPI: Read 512 Bytes** (READ, `0x03`) — 2-sector read via `0x2615`. No `0xAA` header. | R |
| `0x05` | `0x28A0` | **SPI: Read 512 Bytes Fast Read** (FR, `0x0B`) — sets `bit_6B` (byte-address mode), 2-sector read. No `0xAA`. | R |
| `0x06` | `0x28DD` | **Read single byte from XMEM** at address `[0x30:0x31]` into `0x4001`. `0xAA` at `0x4000`. | R |
| `0x07` | `0x2903` | **?** — SPI cmd `0x60` (possibly DUAL_FAST_READ or vendor-specific), status poll + `0xAA` header | R |
| `0x08` | `0x293A` | **?** — large dual multi-sector read (`0x40` then `0x4040` sectors) with `0xAA` header | R |
| `0x09` | `0x2983` | **?** — XRAM-to-buffer copy using R0-indexed pointer, then PIO OUT | R |
| `0x0A` | `0x29DB` | **?** — buffer-to-XRAM copy (reverse of key `0x09`), then PIO IN teardown | W |
| `0x0B` | `0x2A2C` | **SPI: Write 512 Bytes** (PP, `0x02`) — single-sector SPI flash page program from buffer. | W |
| `0x0C` | `0x2A6F` | **?** — minimal no-op/status stub, teardown only | — |
| `0x0D` | `0x2A81` | **?** — multi-sector SPI write loop (`0x02` PP), 2 iterations, buffer sourced | W |
| `0x10` | `0x2B25` | **Write single byte to XMEM** at `[0x30:0x31]` = `0x3A` (LBA_LOW). `0xAA` header then PIO OUT (status). | W |
| `0x11` | `0x2B49` | **Set flag `bit_42`** | W |
| `0x12` | `0x2B51` | **Clear flag `bit_42`** | W |
| `0x13` | `0x2B59` | **?** — multi-sector read in 0x40-sector loops, copies buffer → XRAM at `0x4080+` | R |
| `0x14` | `0x2BDE` | **SPI: Sequential Write** (Auto Program, `0xAD`) — if key == `0x14` | W |
| `0x15` | `0x2BDE` | **SPI: Sequential Write** (Auto Program, `0xAF`) — if key == `0x15` | W |
| `0x16` | `0x2D0B` | **SPI: Read Status Register** (RDSR, `0x05`) — returns 1 status byte at `0x4001`. | R |
| `0x17` | `0x2D26` | **SPI: Write Status Register** (WRSR, `0x01`) — writes `0x3A` (LBA_LOW) to status reg. | W |
| `0x18` | `0x2D63` | **SPI: Volatile Write Enable** (WEVSR, `0x50`) | W |
| `0x19` | `0x2D8D` | **XMEM flag set** — `XRAM[0x2000] |= 0x01` | W |
| `0x1A` | `0x2D9A` | **SPI: Sector Erase** (SER, `0x20`) | W |
| `0x1B` | `0x2DDD` | **SPI: Block Erase 64K** (BER64K, `0xD8`) | W |
| `0x1C` | `0x2E20` | **SPI: Chip Erase** (CER, `0xC7`) | W |
| `0x1D` | `0x2E57` | **WRITE EEPROM** via `0x3142` (I2C write). Sets `bit_94` and `bit_95`. | W |
| `0x1E` | `0x2E9D` | **READ EEPROM** via `0x30CD` (I2C read), copied to buffer, PIO OUT | R |
| `0x30` | `0x2F0A` | *(v3.72 only)* — SETB `bit_6B`, build IDENTIFY device data, PIO OUT | R |
| `0x31` | `0x2F1C` | *(v3.72 only)* — CLR `bit_6B`, build IDENTIFY device data, PIO OUT | R |
| `0x32` | `0x2F2E` | *(v3.72 only)* — fill buffer with `0xFF` test pattern, PIO OUT | R |
| — | `0x2FD2` | **Default** — unimplemented | — |

> **Direction key:** **R** = PIO OUT (device → host), **W** = PIO IN (host → device) or write-side action with teardown.
>
> **How `RAM_39` is set before dispatch:** The value in `RAM_39` is the ATA FEATURES register. During normal READ/WRITE paths (`0x278F` / `0x27C9`), `RAM_39` is pre-loaded by the state machine at `0x10C3` or `0x9930` from EEPROM configuration. For the dedicated `0xFE` vendor command, `0x8062` explicitly copies the FEATURES register into `RAM_39` before dispatch.

## 7. Control Flow

### 7.1 Reset & Initialization

```
0x0000  RESET vector → SJMP 0x001F
0x001F  MOV R0, #0x20
0x0021  Clear IRAM 0x20-0xFF loop (256 iterations via CJNE R0, #0x00)
0x0027  MOV R0, #0x00
0x0029  Init stack pointer (SP=0xC2)
0x002C  Init timer registers (TH0=0xC0, TL0=0x63)
0x0032  Init timer mode (TMOD=0x11)
0x0035  Init timer control (TCON=0x04)
0x0038  Init serial control (SCON=0x00)
0x003B  Init interrupt priority (IP=0x01)
0x003E  Init interrupt enable (IE=0xCF)
0x0041  LJMP 0x0311
```

At `0x0311` the firmware:
1. Sets `0x6D = 0x0A` (retry count)
2. ANL `0x8E`, `#0xF8` (unidentified SFR — not TMOD, which was set at `0x0032`)
3. Sets `P1 = 0xFF`
4. Writes `0x09` to XRAM `0x2006`
5. Reads XRAM `0x4202` and checks for a signature (`0x42`, `0x41`, `0x4E`, `0x4B` → "BANK")
6. If signature missing, writes it
7. Clears XRAM `0x2002`
8. Sets `0x6E = 0x05`
9. Writes SD controller registers at `0x6000`–`0x6010`
10. Polls `0x6000` until ready (`JB 0xE0` loop at `0x039C`)
11. Polls `0x6010`
12. If retry counter `0x6D` hits zero, loops back

### 7.2 Main Polling Loop

```
0x03BF  CLR A
0x03C0  MOV 0x50, A          ; A is 0 here → adapter mode = SPEED (0)
0x03C2  JNB P1.0, wait
0x03C5  JNB P1.1, wait
0x03C8  JNB P1.2, wait
0x03CB  JB  P1.3, proceed
0x03CE  SJMP 0x03CE          ; P1.3 LOW → safe-mode hang
```

The firmware samples **Port 1 pins** as hardware strapping inputs. The exact electrical purpose (SD detect, power-good, board revision ID, or test-mode strap) is **not determined by the code alone**. Once `P1.3` is high:

```
0x03D0  Check XRAM 0x2044
0x03DA  LCALL 0x2FE0        ; EEPROM signature check
0x03DF  JNC fail
0x03E1  JNB bit_5E, fail
0x03E4  Read EEPROM offset 0x03 (adapter config)
...
```

After initialization, execution enters a background loop that:
- Reads SD card status
- Polls ATA engine flags in XRAM (`0x2000`–`0x2026`)
- Dispatches to ATA command handlers when the engine signals a new host command

### 7.3 Command Dispatch ISR (EXT0, `0x0044`)

When the host writes the ATA Command register, the FC1307 asserts **EXT0** on the 8051.

The EXT0 ISR (`0x0044`) with register bank 1:
1. Saves ACC and PSW
2. Checks `bit_2B`; if clear, jumps directly to the taskfile snapshot at `0x013F`
3. If `bit_2B` is set, updates sector-counters, increments `RAM_38` (sector index), and issues engine commands `0x0C` and `0x6C` to push sector addressing data into the engine
4. At `0x013F`: reads `0xA1`, masks with `0x03`, loops while non-zero (not-busy), then **restores** the host taskfile from IRAM into SFRs (`0x67→A2`, `0x68→A4`, `0x69→A5`, `0x6A→A6`, `0x6B→A7`)
5. Issues engine command `0x08` (read extended status → A4)
6. Checks error/ready flags in A4/A5 and sets bits (`0x32`, `0x50`, `0x4E`, `0x68`, `0x28`) accordingly
7. Issues engine command `0x44` (read additional flags → A4); copies result to `RAM_43` (`MOV 0x43, 0xA4` at `0x0199`)
8. Clears `bit_2A`, **snapshots** taskfile from SFRs back to IRAM (`A2→0x67`, `A4→0x68`, ... `A7→0x6B` at `0x019E`–`0x01AA`), and returns with `RETI`

**EXT1 ISR (`0x0217`)** handles SD card controller events. It saves registers (bank 3), calls `0x0903` (SD controller event handler), restores registers, and returns.

### 7.4 Background Command Dispatch

The main loop calls `0x9602` (mode 0 dispatch). When `bit_28` is set:
1. Opcode is loaded from `RAM_43` into A
2. `0x335D` is called with the inline dispatch table at `0x962E` (§6.3)
3. The handler executes and returns

A similar dispatch path at `0x947D` uses the primary dispatch table at `0x9482` (§6.1, called via `LCALL 0x335D`).

The `0x962E` inline table is specifically for sector-read/write opcodes (`0x20`, `0x24`, `0x25`, `0x29`, `0x30`–`0x31`, `0x34`–`0x35`, `0x38`–`0x39`, `0xC4`–`0xC5`, `0xC8`–`0xCB`). Because these commands are the firmware's hot path, they get their own inline dispatch rather than going through the generic `0x956B` stub.

#### PIO Write-Path Dispatch (`0x27C9` / `0x27DE`)

After the secondary table at `0x2759` routes a command to the PIO handlers (`0x278F` for READ, `0x2796` for WRITE), a further dispatch occurs via `0x27DE`:

1. Handler `0x278F` (READ PIO) or `0x2796` (WRITE PIO) is entered
2. Buffer setup is performed (sector address in `0x48`–`0x4B`, DMA controller config)
3. `0x27DE` is called, which loads `RAM_39` (= FEATURES register) and dispatches through the `0xFE` FEATURES table at `0x27E3` (§6.4)
4. The selected handler reads from SD card / XRAM into `0x4000`–`0x41FF`
5. For keys `0x02`, `0x03`, `0x06`, `0x07`, `0x08`, a `0xAA` marker is written to `0x4000` (and sector count to `0x4001`–`0x4002`)
6. `LCALL 0x26E7` initiates PIO OUT to the host

This means **the same READ/WRITE command can behave differently depending on `RAM_39`**, which is set during adapter initialization based on EEPROM configuration and boot-time state machine (`0x0FB4`, `0x10C3`, `0x9930`).

### 7.5 Handler Completion

All handlers finish with one of these patterns:

**PIO OUT (device → host):**
```
LCALL 0x05DF       ; refresh status
LCALL 0x8083       ; prepare PIO OUT (cmd 0x28)
LCALL 0x8DFE       ; begin PIO OUT (cmd 0x60)
wait_A9:
  MOV A, 0xA9
  JB ACC.1, wait_A9
wait_sync:
  MOV R7, #0x3C
  LCALL 0x057E
  MOV A, 0xA4
  JB ACC.3, wait_sync
MOV R7, #0x01
LCALL 0x058C       ; teardown PIO OUT
LCALL 0x05DF       ; final status
RET
```

**PIO IN (host → device):**
```
LCALL 0x05DF
LCALL 0x8083       ; prepare
LCALL 0x86C1       ; begin PIO IN (cmd 0x68, sets A9=1)
... wait for data ...
MOV R7, #0x02
LCALL 0x058C       ; teardown PIO IN
LCALL 0x05DF
RET
```

**DMA (autonomous):**
```
SETB bit_76        ; flag: DMA active
... setup buffer pages ...
LCALL 0x0575 / 0x057E with engine DMA commands
... return immediately; engine streams autonomously ...
; Completion interrupt or background poll calls 0x26B8
```

---

## 8. SD Card & EEPROM Interface

### 8.1 EEPROM (I2C) — `0x30CD`

The FC1307 uses **software I2C** on Port 1 pins:
- **P1.4** = Data (bidirectional)
- **P1.5** = Clock (output)

**Protocol:**
- Device address: `0xA0` (write), `0xA1` (read)
- All 3 address bits tied low

**Function `0x30CD` — `EEPROM_Read(len, offset, dev_addr)`:**
```
ARG R3 = bytes to read
ARG R5 = EEPROM offset
ARG R7 = device address (0xA0)
```

The function:
1. Calls `0x3028` (I2C Start)
2. Bitbangs out device address (0xA0)
3. Reads ACK on P1.4
4. Bitbangs out offset (R5)
5. Reads ACK
6. Calls `0x3028` (Restart)
7. Bitbangs out read address (0xA1)
8. Reads ACK
9. Loop: calls `0x308D` (read byte), stores to XRAM `0x5C00 + index`
10. Sends ACK/NACK after each byte
11. Calls `0x3040` (I2C Stop)
12. Returns with Carry set on success

**EEPROM Offsets Used:**

| Offset | Size | Purpose |
|--------|------|---------|
| `0x0A` | 3 | Status flags for Serial, FW, Model |
| `0x0D` | 2 | UDMA mode override (if first byte == `0x99`) |
| `0x10` | 20 | Serial number |
| `0x24` | 8 | Firmware revision |
| `0x2C` | 40 | Model name |

### 8.2 SD Card Controller

The SD interface is memory-mapped via XRAM at `0x6000`–`0x6010`. The firmware does **not** bitbang SPI for SD** — it uses a hardware SD controller.

Registers (inferred from MOVX patterns):

| XRAM | R/W | Purpose |
|------|-----|---------|
| `0x6000` | R/W | Command / status register |
| `0x6001` | W | Argument low byte |
| `0x6008` | W | Argument mid-low |
| `0x6009` | W | Argument mid-high |
| `0x600A` | W | Argument high |
| `0x600B` | W | Transfer control |
| `0x6010` | R | Response / busy status |

**Typical SD command sequence** (from `0x0236`):
```
MOV DPTR, #0x6001
MOV A, R7      ; arg[0]
MOVX @DPTR, A
INC DPTR       ; 0x6002
MOV A, R5      ; arg[1]
MOVX @DPTR, A
INC DPTR       ; 0x6003
MOV A, R3      ; arg[2]
MOVX @DPTR, A
```

The firmware writes a 32-bit argument into `0x6001`–`0x6004`, then issues the command via `0x6000`.

**Key SD functions:**
- `0x0236` — Write SD argument vector
- `0x07A5` — Read sector setup (sets up `0x200B`, calls `0x063A`)
- `0x063A` — Low-level SD buffer config
- `0x07E2` — Post-read cleanup / next sector prep

---

## 9. ATA Engine Deep Dive

### 9.1 Gateway Functions

| Address | Input | Action |
|---------|-------|--------|
| `0x0575` | R7 = engine cmd | R7 → IRAM 0x74 → `0xA2`, fire (`0xA1 = 1`). No busy-wait; returns immediately. |
| `0x057E` | R7 = engine cmd | R7 → IRAM 0x76 → `0xA2`, fire+wait (`0xA1 = 2`). Reads `0xA1` into ACC and polls `ACC.1` (bit 1 of the 0xA1 value) until cleared. |
| `0x058C` | R7 = teardown mode | R7=1: PIO OUT cleanup. R7=2: PIO IN cleanup. Updates TF0/TF1. |
| `0x05DF` | — | Status refresh: cmd `0x10` to engine, reads TF0+TF2, masks ERR/DRDY, writes back. |

### 9.2 Engine Command Codes (R7 values)

| Code | Type | Description |
|------|------|-------------|
| `0x00` | Write | Commit updated TF0/TF1 back to engine |
| `0x08` | Read | Fetch extended engine status → A4 |
| `0x0C` | Read | Fetch host taskfile → A4, A5 |
| `0x10` | Read/Write | Refresh ATA Status (TF0) and Error (TF2) registers |
| `0x14` | Read | Read engine register 0 → A4 |
| `0x1C` | Read | Read PIO parameters → A4 |
| `0x20` | Write | Push buffer param 0 (A4) |
| `0x28` | Read/Write | Prepare PIO OUT / push buffer params (A4+A5) |
| `0x3C` | Read | Transfer sync poll → A4.3 = "host still reading" |
| `0x44` | Read | Fetch additional flags → A4 |
| `0x60` | Write | **Arm PIO OUT** (device → host) |
| `0x64` | Write | **Commit PIO OUT** — assert DRQ, start streaming |
| `0x68` | Write | **Arm PIO IN** (host → device) |
| `0x6C` | Read/Write | Fetch full host taskfile (ISR) or commit PIO IN |

### 9.3 PIO OUT Choreography (IDENTIFY Device @ `0x821A`)

```
1. LCALL 0x05DF          ; refresh status
2. MOV 0xA4, #0x00
   MOV R7, #0x20
   LCALL 0x0575           ; push buffer param 0 = 0
3. MOV 0xA5, #0x00
   MOV 0xA4, #0x00
   MOV R7, #0x28
   LCALL 0x0575           ; prepare PIO OUT
4. MOV 0xAA, #0x00
   MOV 0xA9, #0x02       ; select buffer page 2 (IDENTIFY data)
   CLR 0xA7 / 0xA6 / 0xA5 / 0xA4
   MOV R7, #0x60
   LCALL 0x0575           ; arm PIO OUT
5. MOV 0xA4, #0x00
   MOV 0xA5, #0x02
   MOV 0xA7, #0x80
   MOV R7, #0x64
   LCALL 0x0575           ; commit PIO OUT
6. wait_saddr:
   MOV A, 0xA9
   JB ACC.1, wait_saddr   ; wait for buffer page stable
7. wait_sync:
   MOV R7, #0x3C
   LCALL 0x057E
   MOV A, 0xA4
   JB ACC.3, wait_sync    ; wait for host to finish reading
8. MOV R7, #0x01
   LCALL 0x058C           ; teardown
9. LCALL 0x05DF           ; final status
   RET
```

### 9.4 DMA/UDMA Transfer Path

**Dispatch:**
- DMA opcodes (`0xC8`–`0xCB`, `0x25`, `0x35`) are routed through the secondary table at `0x2759`.
- Handler `0x278D` (READ DMA) or `0x2794` (WRITE DMA) is called.

**Setup (simplified):**
```
SETB bit_76              ; DMA active flag
CLR bit_6C               ; clear PIO active flag
... set buffer page via A9 ...
LCALL 0x0575 (cmd 0x68 or similar)   ; arm DMA
... engine streams autonomously ...
```

**Completion (`0x26B8`):**
```
JB bit_76, 0x26C0        ; if DMA flag set, skip PIO cleanup
CLR bit_6C               ; clear PIO active
LCALL 0x05DF             ; status refresh
; ... DMA-specific teardown ...
```

### 9.5 UDMA Advertisement & Mode Selection

**IDENTIFY WORD 88 (UDMA modes supported):**
- Source: ROM constant at `0x3D2E`
- Default value: `0x3F` = modes 0–5 advertised
- Handler: `0x23AA` loads it via `MOVC` into XRAM `0x40B0`

**SET FEATURES UDMA path (`0x82C9`–`0x82F8`):**
```
; Check if mode class == UDMA (0x40)
MOV A, RAM_6F            ; Sector Count = mode byte
ANL A, #0xF8
XRL A, #0x40
JNZ check_MWDMA          ; if not UDMA, try MWDMA

SETB 0x51                ; UDMA active flag
MOV A, RAM_6F
ANL A, #0x07             ; isolate mode 0–7
MOV @R0, A               ; RAM_99 = mode (NO CLAMPING!)

; Update TF0/TF1 with UDMA enable bits
ANL 0xA4, #0xFC
ORL 0xA4, #0x02
ANL 0xA5, #0x81
SWAP A
ANL A, #0xF0
ORL 0xA5, A              ; A5 high nibble = UDMA mode
```

> **Critical finding:** There is **zero validation** against `0x3D2E`. The firmware takes `RAM_6F & 0x07` directly with no bounds check, accepting UDMA modes 0–7 regardless of the advertised mask at `0x3D2E`.

---

## 10. Data Tables

### 10.1 IDENTIFY Default Block (`0x3DD8`)

The firmware copies 0x128 (296) bytes from ROM `0x3DD8` to XRAM `0x4000` as the base IDENTIFY data. Key fields overwritten later:

| XRAM Offset | WORD | Source | Description |
|-------------|------|--------|-------------|
| `0x4000`–`0x4001` | 0 | ROM | General config |
| `0x4002`–`0x4003` | 1 | Computed | Logical cylinders |
| `0x400E`–`0x400F` | 7 | Computed | CFA reserved |
| `0x4014`–`0x4027` | 10–19 | EEPROM | Serial number |
| `0x402E`–`0x4035` | 23–26 | ROM / EEPROM | Firmware revision ("Rev 3.72") |
| `0x4036`–`0x405D` | 27–46 | ROM / EEPROM | Model name |
| `0x405E`–`0x405F` | 47 | Constant 0x01 | Max sectors per mult. transfer |
| `0x406A`–`0x406B` | 53 | Constant 0x03 | Validity flags |
| `0x406C`–`0x406F` | 54 | Computed | Current cylinders/heads |
| `0x4072`–`0x4075` | 60–61 | Computed | Total LBA sectors |
| `0x4076`–`0x4077` | 59 | RAM 0x7E | Current multiple sector count |
| `0x4078`–`0x407B` | 60–61 | Computed | Total sectors (alternative path) |
| `0x407E`–`0x407F` | 63 | Constant 0x0007 | MWDMA modes supported |
| `0x40B0`–`0x40B1` | 88 | ROM `0x3D2E` | **UDMA modes supported** |
| `0x40AA`–`0x40AB` | 85 | Computed | Enabled command sets |
| `0x40B0`–`0x40B1` | 88 | RAM 99 / EEPROM | Selected UDMA mode |
| `0x4140`–`0x4141` | 160 | Constant 0x81F4 | CFA power mode |
| `0x4146`–`0x4147` | 163 | Computed | Advanced power management |

### 10.2 String Table (`0x3F00`)

All strings are space-padded and loaded into IDENTIFY fields.

| ROM Offset | Content |
|------------|---------|
| `0x3F00` | `"Rev 3.72"` |
| `0x3F09` | `"FC-1307 SD to CF Adapter BACKUP V2.3"` |
| `0x3F32` | `"SD to CF Adapter 3rd Gen"` |
| `0x3F5B` | `"FC-1307 SD to CF Adapter SPEED V2.3"` |
| `0x3F84` | `"FC-1307 SD to CF Adapter JBOD V2.3"` |

### 10.3 EEPROM Layout

| Offset | Length | Description |
|--------|--------|-------------|
| `0x00` | 1 | Magic/status |
| `0x01` | 1 | |
| `0x02` | 1 | |
| `0x03` | 1 | Adapter mode? |
| `0x0A` | 3 | SN/FW/Model status flags |
| `0x0D` | 2 | UDMA override (`0x99` + mode mask) |
| `0x10` | 20 | Serial number ASCII |
| `0x24` | 8 | Firmware revision ASCII |
| `0x2C` | 40 | Model name ASCII |

---

## 11. Writing Custom Patches

### 11.1 Hook Points

| Location | Current | How to Hook |
|----------|---------|-------------|
| Primary dispatch table (`0x9482`–`0x953F`) | 3-byte entries | Replace `(handler, opcode)` pair with a new handler address. Handlers must end by updating status and returning. |
| `0x9540` (IDENTIFY stub) | `LCALL 0x821A` | This is a 3-byte stub. To hook, replace the entire stub with `LJMP my_handler`, save 3 bytes, and `LJMP` back or `LCALL` original. |
| `0x95E7` (ATA `0xFE`) | `LCALL 0x8062` | The `0xFE` vendor command stub. Copies FEATURES/LBA to taskfile, then calls `0x27DE`. Safe to replace entirely. |
| `0x3D2E` (UDMA mask) | `0x3F` | **Single-byte patch** → `0x1F` (limit to UDMA 0–4) or `0x07` (limit to UDMA 0–2). |
| `0x05DF` (Status gateway) | Fixed function | Call after your handler to ensure the host sees correct status. |
| `0x058C` (Teardown) | Fixed function | Call with R7=1 or R7=2 after PIO transfers. |

### 11.2 Adding a New Vendor Command

To add a new command (e.g., `0xF1`):

1. **Choose a slot:** Find an unused opcode in the primary dispatch table (`0x9482`, §6.1) or the inline table (`0x962E`, §6.3). For maximum compatibility, use the primary table and pick an opcode that's not used by standard ATA (e.g. an opcode not listed in §6.1 or §6.3).
2. **Write handler in patch region:**
   ```asm
   my_f1_handler:
       CLR  bit_6C
       LCALL 0x05DF
       ; ... do work ...
       LCALL 0x05DF
       RET
   ```
3. **Install dispatch entry:** At the table offset for your opcode, write the new handler address as `(hi, lo, opcode)`.
4. **Test:** Use `sg_raw` or `hdparm` to send the command and verify response.

### 11.3 ATA Engine Rules for Custom Handlers

1. **Always call `0x05DF` at start and end.** This refreshes the host Status register.
2. **For PIO OUT:** Use the exact sequence `0x20 → 0x28 → 0x60 → 0x64`, wait on `A9.1`, then poll `0x3C` / `A4.3`, then `0x058C(R7=1)`.
3. **For PIO IN:** Use `0x8083 → 0x86C1 → ... → 0x058C(R7=2)`.
4. **Do not modify `0xA1` directly.** Always use `0x0575` or `0x057E`.
5. **Do not write to `0xA2` while the engine is busy.** Always check `0xA1` (read into ACC, test `ACC.1`) or use the blocking gateway `0x057E`.

---
