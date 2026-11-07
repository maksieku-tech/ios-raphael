#!/bin/bash
# By Maksieku
set -euo pipefail
cd "$(dirname "$0")"
DEVICE=${DEVICE:-sweet}
CC=aarch64-linux-gnu-gcc
OBJCOPY=aarch64-linux-gnu-objcopy
DEFS="-DDEVICE_$(echo "$DEVICE" | tr '[:lower:]' '[:upper:]')"
CFLAGS="-O2 -ffreestanding -nostdlib -fno-pic -mgeneral-regs-only -mstrict-align -fno-stack-protector -Wall -Wextra $DEFS"
case "$DEVICE" in
sweet)   DTB=${DTB:-../dtb/boot_unpacked/dtb} ;;
raphael) DTB=${DTB:-../dtb/raphael/kernel_dtb} ;;
*) echo "error: unknown DEVICE=$DEVICE (sweet, raphael)" >&2; exit 1 ;;
esac
SRCS="start.S shim.c console.c mmu.c fdt.c loader.c ufs.c panel.c"
mkdir -p out
OBJS=""
for f in $SRCS; do
	$CC $CFLAGS -c $f -o out/${f%.*}.o
	OBJS="$OBJS out/${f%.*}.o"
done
abs=$(aarch64-linux-gnu-readelf -r out/shim.o out/console.o out/mmu.o out/fdt.o out/loader.o out/ufs.o out/panel.o | grep -c ABS64 || true)
[ "$abs" = 0 ] || { echo "error: $abs absolute relocations in C objects" >&2; exit 1; }
$CC $CFLAGS -static -T shim.ld -Wl,--build-id=none -Wl,--no-warn-rwx-segments -Wl,-N \
	$OBJS -o out/shim.elf
$OBJCOPY -O binary out/shim.elf out/Image
size=$(aarch64-linux-gnu-nm out/shim.elf | awk '$3=="_end"{print strtonum("0x"$1)}')
truncate -s "$size" out/Image
if [ -n "${1:-}" ]; then
	cp "$1" out/ramdisk.bin
else
	(cd out && rm -rf rd && mkdir rd && cd rd && find . | cpio -o -H newc --quiet | gzip -9 > ../ramdisk.bin)
fi
[ -f "$DTB" ] || { echo "error: stock DTB $DTB missing (see docs/PORTING-raphael.md)" >&2; exit 1; }
HDR=${BOOT_HEADER:-2}
if [ "$DEVICE" = sweet ] || [ "$HDR" = 2 ]; then
	mkbootimg --header_version 2 --kernel out/Image --ramdisk out/ramdisk.bin \
		--dtb "$DTB" --base 0 --kernel_offset 0x8000 --ramdisk_offset 0x1000000 \
		--tags_offset 0x100 --dtb_offset 0x1f00000 --pagesize 4096 \
		--os_version "${OS_VERSION:-17.0.0}" --os_patch_level "${OS_PATCH_LEVEL:-2035-06}" \
		--cmdline "console=null" -o out/shim-boot.img
else
	gzip -9 -n -c out/Image > out/Image.gz
	cat out/Image.gz "$DTB" > out/Image.gz-dtb
	mkbootimg --header_version "$HDR" --kernel out/Image.gz-dtb --ramdisk out/ramdisk.bin \
		--base 0 --kernel_offset 0x8000 --ramdisk_offset 0x1000000 \
		--tags_offset 0x100 --pagesize 4096 \
		--os_version "${OS_VERSION:-11.0.0}" --os_patch_level "${OS_PATCH_LEVEL:-2021-08}" \
		--cmdline "console=null" -o out/shim-boot.img
fi
gcc -O1 -Wall $DEFS -o out/host_test console.c host_test.c panel_host.c && ./out/host_test
ls -l out/Image out/shim-boot.img
