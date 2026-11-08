<!-- By Maksieku -->
# ios-raphael

**Apple's iOS 16 running on a Xiaomi Mi 9T Pro / Redmi K20 Pro (`raphael`).**

This is a port of [dipa-studio/ios-sweet](https://github.com/dipa-studio/ios-sweet) to the Mi 9T Pro (Qualcomm SM8150 / Snapdragon 855). It runs Apple's open-source XNU kernel (xnu-8796, the iOS 16 generation). On top of it runs the **unmodified iOS 16.7.16 (20H392) userland of the iPhone X**: launchd, the system daemons, backboardd, SpringBoard and the stock apps.

As of **2026-11-08** the Mi 9T Pro boots to the **iOS lock screen** on all 8 CPU cores, and you can unlock it with the touchscreen. Rendering runs entirely on the CPU; there is no GPU driver yet (see [GPU](#gpu)).

> Experimental bring-up, not a usable phone OS. Many things are missing or stubbed (see below), and Apple's security model is mostly switched off. It installs into the `userdata` partition and so **erases Android's user data**. Android itself, recovery and all other partitions are left alone; *Format Data* in TWRP brings Android back.

## What works on raphael

| Area | State |
| --- | --- |
| Boot | Stock Xiaomi bootloader → `fastboot boot` of our shim → XNU. Nothing is flashed to the boot partitions. The boot image must be header v2 with a separate DTB |
| CPU | All 8 cores (4 × Cortex-A55, 4 × Cortex-A76) via PSCI, 16K pages, GICv3, timers |
| Memory | About 3.95 GiB of the upper DDR bank (`0x100000000` + `0xfcb00000`) |
| Storage | Own UFS host driver (UFSHCI 3.0); the iOS root is a journaled HFS+ volume in `userdata`, read/write |
| Display | Samsung EA8076 command-mode panel left in the bootloader's autorefresh; frames are copied by the CPU into the bootloader's framebuffer (`0x9c000000`, 1080×2340). Presented to iOS as an iPhone X panel (1125×2436) |
| GUI | backboardd, SpringBoard, lock screen, unlock by swipe |
| Touch | Goodix GT9889 (GTX8 "Normandy") at I²C `0x5d` on QUPv3 wrap2 SE2 (`0xc88000`); coordinates at `0x4100` (from the GTX8 config built into the stock kernel); multi-touch |
| Buttons | Power and volume over SPMI (PM8150); driver starts, lightly tested |
| Battery | Static IOPMPowerSource (100 %) |
| Device identity | iPhone X (`iPhone10,3` / `D22AP`), activation through mobileactivationd's native path, no Apple servers involved |

## What does not work (yet)

- **No GPU acceleration.** Everything is drawn by the CPU.
- **No Wi-Fi, Bluetooth, cellular, audio, camera, sensors, GPS or Face ID.** Their daemons start and fail or keep relaunching.
- **Few apps:** only what is on the system volume. No App Store, no Apple ID.
- **Security is off:** permissive code signing and sandbox, stub AppleKeyStore, no data protection. Do not put anything personal on it.
- Touch axis orientation and the hardware buttons inside iOS still need a full check.

## How it boots

```
ABL (stock Xiaomi bootloader, unlocked)
  -> fastboot boot raphael-ios-boot.img       (temporary; nothing is flashed to boot)
     -> shim: own MMU setup, reads the live FDT, loads the payload from the ramdisk
        -> XNU Mach-O + generated Apple Device Tree (ADT) + boot-args
           -> XNU -> UFS driver -> HFS+ root in the userdata partition
              -> dyld + shared cache -> launchd -> daemons -> backboardd + SpringBoard
```

There is no serial port. The kernel draws its console into the bootloader's framebuffer and keeps a persistent 4 MiB log ring at the end of `userdata`; read it from TWRP (see [Read the kernel log](#5-read-the-kernel-log)).

## How to do it yourself

You need a Mi 9T Pro / Redmi K20 Pro (`raphael`) with an **unlocked bootloader**, TWRP, `adb`/`fastboot`, and a GitHub account for the kernel build. **Everything on `userdata` is lost.**

### 0. Back up and collect the device tree

From TWRP, pull at least `persist`, `modemst1`, `modemst2`, `fsg`, `fsc`, `boot`, `dtbo` and `vbmeta`. They contain per-device calibration data; keep them off git. The shim needs your phone's DTB, which you extract from your `boot.img` with `tools/unpack_bootv2.py`. `tools/fdt2profile.py` checks the raphael hardware profile against your live device tree.

### 1. Build the kernel

The kernel builds on GitHub's macOS runners (`macos-15`) with [blacktop/darwin-xnu-build](https://github.com/blacktop/darwin-xnu-build). The workflow fetches xnu-8796 and applies `xnu/patches/` in order. Public repositories get free macOS minutes. Push to `main` (or run the workflow) and download the `xnu-kernel` artifact.

### 2. Build the iOS root image

Download the iPhone X (iPhone10,3) iOS **16.7.16 (20H392)** IPSW from Apple, e.g. via [ipsw.me](https://ipsw.me/iPhone10,3).

On a Linux PC with the `hfsplus` kernel module, use `tools/mkiosroot.sh` and `tools/sweet-root-tweaks.py` exactly as in [ios-sweet](https://github.com/dipa-studio/ios-sweet#2-build-the-ios-root-image).

Without `hfsplus` (containers, cloud machines), `tools/mkiosroot-qemu.sh` does the same job: it stages the tree with `apfs-fuse` and `rsync`, applies the tweaks to the plain directory, and copies it into the HFS+ image with a throwaway QEMU guest over virtio-9p:

```sh
sudo tools/mkiosroot-qemu.sh OS.dmg SystemOS.dmg AppOS.dmg ios16-root.img 16G
img2simg ios16-root.img ios16-root.simg
```

`tools/ipsw-split.py` extracts just the needed images (OS, SystemOS and AppOS cryptexes, DeviceTree) from the IPSW in resumable pieces, for moving them between machines. Decode `DeviceTree.d22ap.im4p` (LZFSE) to `research/ipsw-x/d22ap.adt`: the ADT builder copies its `/product` node, which MobileGestalt needs.

### 3. Build the boot image

Needs `aarch64-linux-gnu-gcc` and `mkbootimg`.

```sh
python3 tools/mkadt.py shim/out/raphael.adt --device raphael --highmem
python3 tools/mkpayload.py xnu/out/kernel.development.sweet shim/out/raphael.adt shim/out/payload.bin \
    --cmdline 'cpus=8 debug=0xc serial=3 keepsyms=1 -enable_kprintf_spam -noprogress rd=ufsroot0 unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin ufsrw=1 rootrw=1 launchd_unsecure_cache=1 wdt=-1 sweetfb_noconsole=1 sweetfb_hz=30 sweetsample=-'
cd shim && DEVICE=raphael DTB=../dtb/raphael/dtb.0 ./build.sh ../shim/out/payload.bin   # -> shim/out/shim-boot.img
```

`--highmem` is required on raphael: without it the payload asks for the wrong RAM bank and the shim refuses to load it.

| Boot-arg | Effect |
| --- | --- |
| `rd=ufsroot0 ufsrw=1 rootrw=1` | Root on the `userdata` partition, writable |
| `cpus=8` | All cores; `cpus=1` is the safe fallback |
| `sweetfb_noconsole=1` | Stop drawing kernel text over the GUI (it still goes to the persistent log) |
| `sweetsample=-` | Turn off the periodic SpringBoard/backboardd stack sampler |
| `startup_debug=1 sweethb=10` | Bring-up diagnostics: every kernel/BSD start-up step on screen, plus a heartbeat line |
| `sweetgpu=1` | Read-only GPU power/clock probe (patch 0087) |

### 4. Flash the root and boot

```sh
fastboot -S 512M flash userdata ios16-root.simg   # 7-10 minutes; do not unplug
fastboot boot shim/out/shim-boot.img
```

Xiaomi's fastboot can become very slow or stop responding after a large flash; re-enter fastboot with Power + Volume down. The first boot takes a few minutes before the lock screen appears. After a crash, power the phone fully off: some PMIC state survives a warm reboot.

### 5. Read the kernel log

Boot TWRP and read the last 1025 blocks of `userdata`:

```sh
tools/sweet-log-pull.sh logs/boot.txt
```

## GPU

The phone has an Adreno 640; iOS draws through Metal, which only drives Apple GPUs. Acceleration therefore needs our own stack, built in stages:

1. **Hardware bring-up in XNU:** GPU clock controller and power domains, GMU firmware (`a640_gmu.bin`), SMMU page tables, and a command ring that executes a test packet. Patch 0087 is the read-only first step.
2. **A userspace driver:** Mesa's Turnip (Vulkan for Adreno) ported to iOS on top of that kernel interface.
3. **Metal for CoreAnimation:** a Metal implementation over Vulkan that iOS accepts in place of Apple's.

This is a long-term effort; until it lands, more CPU cores and a lean software path are what make it faster.

## raphael kernel patches

The series starts with ios-sweet's patches 0001–0081 (see [Kernel patches](#kernel-patches-from-ios-sweet)).

| # | What |
| --- | --- |
| 0082 | Device profile (`/sweet-device` ADT node): per-board addresses for keys, touch, USB, SPMI, battery, framebuffer; raphael console geometry |
| 0084 | Boot checkpoints: heartbeat thread (`sweethb`), BSD start-up trace (`startup_debug=1`), UFS init steps and host register dumps |
| 0085 | Touch: skip the halt wait for hardware-gated clock branches |
| 0086 | Touch: GTX8 coordinate/version registers from the device profile |
| 0087 | Read-only Adreno 640 power/clock probe (`sweetgpu=1`) |

## raphael hardware facts

- RAM: upper bank `0x100000000` + `0xfcb00000`; the ADT must be built with `--highmem`.
- CPUs: 4 × A55 + 4 × A76 (Kryo 485), MPIDR core number in Aff1, PSCI through `smc`, ARMv8.2. The ADT CPU nodes carry `qcom,kryo485` plus `qcom,kryo470` so the CPU driver matches.
- Display: Samsung EA8076 command-mode panel; ABL leaves MDP autorefresh running with ARGB8888 at `0x9c000000`, stride 4320. Never touch the MDP: reprogramming it garbles or stalls the panel.
- UFS host `0x1d84000` (UFSHCI 3.0); `userdata` is LUN 0, about 47.9 GiB.
- Touch: GT9889 at `0x5d`, QUPv3 wrap2 SE2 `0xc88000` (GCC vote `0x52014` mask `0x4f`, RCG `0x1e3a8`, branches `0x1e004`/`0x1e008`/`0x1e3a4`), SDA/SCL GPIO 57/58 (mux 2), reset 54, IRQ 122, power GPIOs 98/100, all on the TLMM south tile `0x3d00000`. Register map from the GTX8 config bin (`coor 0x4100`, `version 0x452c`, `esd 0x30f3`, `command 0x6f68`).
- Keys: PM8150 PON on SPMI; volume up on PM8150 GPIO6.
- GPU: Adreno 640 v2 (chip ID `0x06040001`), GPU `0x2c00000`, GPUCC `0x2c90000`, GMU `0x2c6a000`, SMMU `0x2ca0000`.

More in [`docs/PORTING-raphael.md`](docs/PORTING-raphael.md) and the engineering log [`NOTES.md`](NOTES.md).

## Repository layout

| Path | What |
| --- | --- |
| `shim/` | Bare-metal boot shim (C + asm) packed as an Android boot.img v2 (`DEVICE=raphael` or sweet) |
| `xnu/patches/` | The XNU patch series (applied in order by CI), plus staging scripts for libpthread, HFS and BearSSL |
| `.github/workflows/xnu.yml` | Kernel CI build |
| `tools/mkadt.py` | Generates the Apple Device Tree and the per-board device profile (`--device raphael`) |
| `tools/mkpayload.py` | Packs kernel + ADT + boot-args into the shim payload |
| `tools/mkiosroot.sh`, `tools/mkiosroot-qemu.sh` | Build the HFS+ iOS root from the IPSW images (with or without the `hfsplus` module) |
| `tools/ipsw-split.py` | Resumable extraction of the needed IPSW images |
| `tools/sweet-root-tweaks.py` | Bring-up changes to the root (Setup skip, activation, daemons) |
| `tools/fdt2profile.py` | Check a board profile against a live device tree |
| `tools/sweet-log-pull.sh`, `sweet-log.py` | Read the persistent kernel log from recovery |
| `tools/sweet-crash.py` | Symbolicate console crash reports |
| `tools/qemu-sweet.py` | QEMU test boots with framebuffer text decoding |
| `docs/PORTING-raphael.md` | The raphael bring-up ladder and hardware differences |
| `NOTES.md` | Detailed engineering log: every boot, crash and decision |

Not in git: partition backups, live device trees, recovery images, Apple firmware and root images, and generated build trees. They contain device serials and calibration data, or Apple's copyrighted files.

## The original target: Redmi Note 10 Pro (`sweet`)

All of ios-sweet's sweet support is still here and builds byte-identically (default `tools/mkadt.py` device and shim `DEVICE`). On sweet the phone reaches the home screen, Settings, Control Center and the notification center on 6 cores, with GT9896 touch and PM6150 buttons. See [dipa-studio/ios-sweet](https://github.com/dipa-studio/ios-sweet) for its full guide.

### Kernel patches from ios-sweet

| # | What |
| --- | --- |
| 0001–0009 | Toolchain compatibility, SWEET machine config, non-PAC arm64, stubs for Apple-internal pieces |
| 0010–0018 | Early framebuffer console, physmap fix, PRNG without corecrypto, device-tree platform expert, timer PPI, boot CPU driver |
| 0019–0020 | Apple open-source libpthread kernel provider; BearSSL AES |
| 0021–0027 | RAM-disk root, mockfs, SHA-256, minimal AMFI, Apple open-source HFS+, MD5 |
| 0028–0034 | UFS host driver and root device, read/write root, DMA above 4 GiB |
| 0035–0045 | Entitlements, bindfs, AppleKeyStore stub, IOWatchdog, console crash reports |
| 0046 | IOSurface (IOCoreSurfaceRoot) and IOMobileFramebuffer (AppleCLCD) services |
| 0047–0055 | Diagnostics: persistent log, /dev/null tee, IOKit trace, heap strings and user stack sampler on crash; permissive Sandbox policy; HFS rename-swap; AppleKeyStore selectors |
| 0056–0057 | Throttled panel copy; no external identity resolver |
| 0058 | HID event services (Apple's IOHIDFamily-1915.140.3 user client and event queue) |
| 0059 | iPhone X identity (`hw.product` / `hw.target` from the device tree) |
| 0060 | Power and volume keys over SPMI; touch over GENI I²C |
| 0061 | Present the display as 1125×2436 |
| 0062 | RPMh regulator vote for the touch rail; battery power source |
| 0063 | GENI FIFO packing fix and the Goodix GT9896 protocol |
| 0064 | Grant PRIV_WORK_INTERVAL (UIKit's CoreAnimation work interval) |
| 0065 | SMP: secondary cores via PSCI CPU_ON |
| 0066–0081 | Crash info, console mute, IOSurface lookups, batched log flushes, USB, 8-core SMP, display power, network trace |

## Credits

- [dipa-studio/ios-sweet](https://github.com/dipa-studio/ios-sweet): the original port this work is based on (MIT, see [`LICENSE`](LICENSE)).
- Built on Apple's open-source releases (xnu, IOHIDFamily, libpthread, hfs), [BearSSL](https://bearssl.org), [blacktop/darwin-xnu-build](https://github.com/blacktop/darwin-xnu-build), [ipsw](https://github.com/blacktop/ipsw), [apfs-fuse](https://github.com/sgan81/apfs-fuse), Linux's Qualcomm clock, pinctrl and device-tree sources, and Xiaomi's published raphael kernel sources for the hardware details.
- iOS itself is Apple's and is not distributed here.
