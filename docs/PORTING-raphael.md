# Porting ios-sweet to the Mi 9T Pro / Redmi K20 Pro (`raphael`, SM8150)

This branch adds a second target, `raphael`, to the ios-sweet bring-up. Nothing
here has run on a raphael yet. Every hardware fact below comes from Xiaomi's
`raphael-p-oss` kernel device tree, mainline Linux (`sm8150.dtsi`,
`gcc-sm8150.c`, `pinctrl-sm8150.c`) and the downstream SDE/Goodix drivers.
Each one is checked again on your phone in step 2 before anything boots.

Nothing changes for sweet: with no `--device`, `tools/mkadt.py` still produces
a byte-identical ADT, and every kernel lookup defaults to the sweet values that
were proven on hardware.

## Why raphael and not the Redmi Note 11 (`spes`)

| | sweet (works) | raphael (Mi 9T Pro) | spes (Redmi Note 11) |
| --- | --- | --- | --- |
| SoC | SM7150 | SM8150 | SM6225 |
| Cores | A76 + A55, ARMv8.2 | A76 + A55, ARMv8.2 | A73 + A53, **ARMv8.0** |
| GIC / timer PPIs | GICv3, vtimer INTID 19 | same | GICv3 |
| PMIC transport | SPMI arb v5 | same addresses | different PMICs |
| Regulators | RPMh | RPMh (same RSC) | **RPM (SMD)**, not RPMh |
| UFS host | 0x1d84000 | 0x1d84000 | different |
| USB | DWC3 0xa600000 | same | different |
| Panel | DSI video mode | **DSI command mode** | video mode |
| Touch | GT9896 on QUP SE7 | **GT9886** on QUP SE19 | other |

raphael shares almost every block, and every address, with sweet. The only real
new work is the command-mode panel and a different Goodix touch protocol.

spes has two problems:

- **The kernel.** `pexpert/arm64/SWEET.h` enables PAN (ARMv8.1), and A53/A73
  cores don't have it. spes would need its own machine config.
- **The userland, probably.** iOS 16 supports only A11 and newer, so the
  `arm64` shared cache may use ARMv8.1 LSE atomics. A53/A73 would hit
  undefined-instruction faults on those unless the kernel traps and emulates
  them. To check, run `tools/isa-scan.py research/dsc/dyld_shared_cache_arm64*`.
  If it finds LSE instructions, spes needs that emulator before anything else.

## What changed

**Kernel: `xnu/patches/0082-sweet-device-profile-raphael.patch`** (applies on 0001–0081; checked against a fresh xnu-8796.141.3)

- `bsd/dev/sweet_device.[ch]`: reads board facts from the ADT node `/sweet-device`. If a property is missing, it returns the sweet value.
- `sweet_keys.c`: the PMIC PON and volume-up GPIO come from the profile. On raphael, volume-up is PM8150 GPIO6 (SID 0, PPID 0x0c5, base 0xc500), not PM6150L GPIO2.
- `sweet_touch.c`: everything board-specific now comes from the profile: QUP SE, GCC votes, RCG and branches, TLMM tile, SDA/SCL pins and mux, reset and IRQ pins, power (an RPMh LDO or GPIO enables), maximum coordinates and axis flips.
  - Adds a **GT9886 "Normandy"** handler:
    - turns off doze mode at 0x30F0/0x3100
    - reads events at 0x824E (12-byte header, 8-byte points, 8-bit sum checksum)
    - acknowledges by writing 0 to 0x824E
    - polls only while the IRQ line (GPIO 122) is low
- `SweetFramebuffer.cpp`: **command-mode panels.** The kernel relies on ABL's autorefresh and never writes `CTL_START` by itself. `sweetfb_kick=1` (rate set with `sweetfb_kick_hz`) turns on software kicks for a bootloader that leaves autorefresh off.
- `SweetHID.cpp`: touch mapping, edge detection and surface size come from the real panel size (1080×2340 is shown centred in the 1125×2436 iPhone X canvas).
- `sweet_usb.c`: USB GCC clock offsets come from the profile. SM8150 uses `cfg-noc-axi` at 0xf078, `aggre-axi` at 0xf07c and `clkref` at 0x8c008. The QUSB2 dump is skipped because SM8150 has a SNPS PHY.
- `sweet_spmi.c`, `SweetBattery.cpp`: SPMI bases and the battery PMIC SID (PM8150B is SID 2) come from the profile.
- `start.s` and `sweet_early.c`: the early marker and early console stay above row 2340, so they are visible on both panels.

**Shim**

- `shim/device.h`: device profile chosen at build time (`DEVICE=raphael shim/build.sh`).
- `shim/panel.c`: **leaves the display controller alone.** Confirmed on a raphael on 2026-11-07: after `fastboot boot` of a v2-header image, ABL keeps the command-mode panel in autorefresh, ARGB8888 at `0x9c000000`, stride 4320. Writing pixels there is enough. Do not reprogram the SSPP format, and do not send `CTL_START` while autorefresh is on: both garble or stall the display. In diagnostic mode (no payload) the shim shows red, green and blue bands for 10 s, then a status line.
- `shim/fdt.c` + `loader.c`: the loader refuses to boot if the kernel's RAM is not inside a live `/memory` bank, or if it overlaps a `no-map` carve-out. This protects every device.
- `shim/build.sh`: raphael uses **boot header v2** with the stock DTB as a separate section, the same layout as sweet. With header v0/v1 (`Image.gz-dtb`, the layout custom ROM kernels use) ABL does not hand the display over: the screen stays stuck on a garbled partial fastboot frame. `BOOT_HEADER=0/1` is still available for experiments.
- The IMEM restart-reason address is per device (raphael: 0x146bf65c).

**Tools**

- `tools/mkadt.py --device raphael`: SM8150 CPUs (4×A55 + 3×A76 + 1×A76 prime), the 2340-line framebuffer, `xiaomi,raphael` / `qcom,sm8150` compatibles, and the full `/sweet-device` profile. It keeps the same synthetic ECID, so the IOPlatformUUID and **the existing v15 root image work unchanged**.
- `tools/fdt2profile.py`: reads a phone's live FDT and checks the profile. On the raphael DT it reports 0 mismatches. On sweet's DT it recovers every sweet constant the kernel uses (SE7 0xa84000, GT9896 @0x5d, GPIOs 8/9/90/6/7, PPID 0x4c1, IMEM 0x146aa65c).
- `tools/split-kernel-dtb.py`: pulls the appended DTBs out of a stock `Image.gz-dtb`.
- `tools/isa-scan.py`: counts ARMv8.1+ instructions in a dyld cache or Mach-O. Its bit patterns were tested on assembled instructions: 16 positives, 10 v8.0 negatives.

## Bring-up ladder

Run each step and report what you see before going on. Steps 0–5 leave
Android's data alone. Step 6 erases userdata.

### 0. Unlock and back up

1. Unlock the bootloader (Mi Unlock).
2. `fastboot boot` a raphael TWRP or OrangeFox.
3. Pull `persist`, `modemst1`, `modemst2`, `fsg`, `fsc`, `boot`, `dtbo`, `vbmeta` and the partition table into `backup/` (git ignores it).
4. Note which stock firmware is installed. ABL comes with it.

### 1. Stock DTB for the shim

```sh
python3 tools/unpack_bootv2.py backup/boot.img dtb/raphael/boot
python3 tools/split-kernel-dtb.py dtb/raphael/boot/kernel dtb/raphael  # -> dtb/raphael/dtb.0
```

`collect-raphael.bat` (in the work folder) does the backups and the live-FDT pull from TWRP on Windows.

### 2. Check the profile against your phone

```sh
adb pull /sys/firmware/fdt dtb/raphael/live.dtb      # from recovery
python3 tools/fdt2profile.py dtb/raphael/live.dtb --device raphael
```

You want `0 mismatch(es)`. The live FDT also has the real RAM banks and the
`msm_drm.dsi_display0=` panel ABL chose. If a check fails, change the matching
entry in `DEVICES['raphael']` in `tools/mkadt.py`. The kernel picks the change
up without a rebuild.

### 3. Shim diagnostics (nothing written anywhere) — **passed 2026-11-07**

```sh
DEVICE=raphael DTB=../dtb/raphael/dtb.0 shim/build.sh && fastboot boot shim/out/shim-boot.img
```

Expected and observed: a red start screen, then red, green and blue bands across the full 1080×2340 with a white strip on the left, then `PANEL cmd mode, MDP untouched`, then the UFS probe. Power the phone fully off before re-entering fastboot after any crash (the PMIC keeps state over warm resets).

### 4. Build the kernel

1. Push this branch to a public fork.
2. Run `gh workflow run xnu.yml`, which builds 0001–0082 (about 8 min).
3. Download the `xnu-kernel` artifact.

### 5. First kernel boot, root read-only (Android data untouched)

```sh
python3 tools/mkadt.py shim/out/raphael.adt --highmem --device raphael
python3 tools/mkpayload.py xnu/out/kernel.development.sweet shim/out/raphael.adt shim/out/payload-r1.bin \
    --cmdline 'debug=0xc serial=3 cpus=1 keepsyms=1 -enable_kprintf_spam -noprogress rd=ufsroot0 wdt=-1 sweetlog=0'
DEVICE=raphael shim/build.sh ../shim/out/payload-r1.bin
fastboot boot shim/out/shim-boot.img
```

Without `ufsrw=1`, the UFS driver refuses every write, and the persistent log
stays off. The boot is expected to end at the root mount, because userdata
still holds Android's filesystem. Check the following:

- the loader shows `RAM inside /memory`
- kernel text appears on screen (the panel path works)
- `SWEET UFS: "userdata" on LUN 0`
- `SWEET KEYS: raphael … volup-apid=…` (press the buttons; key lines should show)
- `SWEET TOUCH: raphael profile …` and then `GT9886 probe wake=0 coord=0`

Touch normally starts 45 s after boot, which is later than the expected
root-mount panic. Add `sweettouchdelay=5` to this command line so the touch
probe runs first.

### 6. Root image and GUI (erases Android userdata)

1. Flash the same v15 `ios16-root-20H392-*.simg` used on sweet: `fastboot -S 512M flash userdata …`
2. Boot with the full sweet cmdline from the README, keeping `cpus=1`.
3. Once SpringBoard is up, try `cpus=4` (the A55s), then `cpus=8`.

Touch axes: tap the top-left corner and read `SWEET HID: touch 0 down at x,y`.
If x or y is mirrored, boot with `sweettouchflip=1` (x), `=2` (y) or `=3` (both),
then make it permanent with `touch-flip` in the profile. The vendor DT flips
both axes for one of its two sensor IDs.

## Known risks, most likely first

1. **The command-mode panel: solved** (v2 header, MDP untouched).
2. **The GT9886 coordinate register.** 0x824E is the downstream driver's default for this IC. The vendor driver can override it from `goodix_gt9886_cfg_f11.bin`. If `coord` fails or the checksums fail, look at the `probe raw 0x8240` lines in the log.
3. **The QUP SE19 firmware.** The touch driver needs XBL/TZ to have loaded I2C firmware into SE19. If it hasn't, the log says "need ABL-loaded I2C firmware" and touch stays off. The GUI still runs.
4. **Boot header.** Must be v2. The v0/v1 layout boots the shim but leaves the display garbled.
5. **Battery readout.** PM8150B has a newer fuel gauge than PM6150, so `SweetBattery`'s real readout (off by default) will not work. The static 100 % path is unaffected.
6. **The big cores.** CPUs 4–7 are A76s at higher clocks. Like sweet they form one homogeneous cluster. Start with `cpus=4`.

## Related work

- **ios-raphael** (Gsjsjzhznsz, GitHub) is an independent ios-sweet port to this same phone. It reached the iOS lock screen with GT9886 touch. It has no licence, so this port takes only facts from its notes (v2 header requirement, ABL autorefresh, full power-off between attempts) and copies no code.
- **UniXNU-cepheus** (Mi 9, SM8150, same EA8076 panel) documents that sending kicks while ABL autorefresh is running stalls the pipeline.
