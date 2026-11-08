#!/bin/bash
# By Maksieku
set -euo pipefail

usage() {
	echo "usage: sudo $0 OS.dmg SYSTEMOS.dmg APPOS.dmg OUT.img [SIZE]" >&2
	echo "  Builds the SWEET iOS root like mkiosroot.sh + sweet-root-tweaks.py, for hosts" >&2
	echo "  without the hfsplus kernel module: the tree is staged in a plain directory" >&2
	echo "  and copied into the HFS+ image by a throwaway QEMU guest over virtio-9p." >&2
	echo "  env: STAGE (staging dir, default OUT.stage), GUEST_DIR (cached guest kernel), DELETE_INPUTS=1 (remove the dmgs once staged)" >&2
	exit 2
}

[[ $# -ge 4 ]] || usage
[[ $(id -u) == 0 ]] || { echo "run as root" >&2; exit 1; }
here=$(cd "$(dirname "$0")" && pwd)
os=$(realpath "$1") sysos=$(realpath "$2") appos=$(realpath "$3") out=$(realpath -m "$4") size=${5:-16G}
stage=${STAGE:-$out.stage}
guest=${GUEST_DIR:-$(dirname "$out")/qemu-guest}
[[ ! -e $out ]] || { echo "refusing to overwrite $out" >&2; exit 1; }
[[ ! -e $stage ]] || { echo "refusing to reuse $stage" >&2; exit 1; }

missing=()
for t in apfs-fuse mkfs.hfsplus fsck.hfsplus rsync qemu-system-x86_64 busybox zstd cpio python3; do
	command -v "$t" >/dev/null 2>&1 || missing+=("$t")
done
if [[ ${#missing[@]} -gt 0 ]]; then
	echo "missing: ${missing[*]}" >&2
	echo "  Ubuntu: apt install hfsprogs rsync qemu-system-x86 busybox-static zstd cpio python3 (apfs-fuse: build github.com/sgan81/apfs-fuse)" >&2
	exit 1
fi
busybox --list | grep -qx tar || { echo "busybox without tar" >&2; exit 1; }

work=$(mktemp -d)
mounts=()
cleanup() {
	for m in "${mounts[@]}"; do
		mountpoint -q "$m" && umount "$m" 2>/dev/null || true
	done
	for m in "${mounts[@]}"; do
		mountpoint -q "$m" && { echo "still mounted: $m" >&2; return; }
	done
	rm -rf "$work"
}
trap cleanup EXIT

apfs_mount() {
	ln -s "$1" "$work/$2.dmg"
	mkdir "$work/$2"
	apfs-fuse "$work/$2.dmg" "$work/$2"
	mounts+=("$work/$2")
}

build_guest() {
	[[ -s $guest/vmlinuz && -s $guest/initrd.gz ]] && return
	mkdir -p "$guest/pkg"
	local kver
	kver=$(apt-cache depends linux-image-virtual | awk '/Depends: linux-image-[0-9]/{sub("linux-image-","",$2); print $2; exit}')
	[[ -n $kver ]] || { echo "cannot find an Ubuntu guest kernel" >&2; exit 1; }
	(cd "$guest/pkg" && apt-get download "linux-image-$kver" "linux-modules-$kver" "linux-modules-extra-$kver")
	for d in "$guest"/pkg/*.deb; do dpkg-deb -x "$d" "$guest/pkg/root"; done
	cp "$guest/pkg/root/boot/vmlinuz-$kver" "$guest/vmlinuz"
	local ird="$guest/initrd" kmod="$guest/pkg/root/lib/modules/$kver/kernel"
	rm -rf "$ird"
	mkdir -p "$ird"/{bin,proc,sys,dev,src,dst,lib/modules}
	cp "$(command -v busybox)" "$ird/bin/busybox"
	for a in sh mount umount insmod tar find wc df sync poweroff cat stat; do ln -s busybox "$ird/bin/$a"; done
	for k in fs/netfs/netfs net/9p/9pnet net/9p/9pnet_virtio fs/9p/9p fs/nls/nls_utf8 fs/hfsplus/hfsplus; do
		zstd -q -d -f "$kmod/$k.ko.zst" -o "$ird/lib/modules/${k##*/}.ko"
	done
	cat > "$ird/init" <<'EOF'
#!/bin/sh
mount -t proc proc /proc
mount -t sysfs sys /sys
mount -t devtmpfs dev /dev
for m in netfs 9pnet 9pnet_virtio 9p nls_utf8 hfsplus; do
	insmod /lib/modules/$m.ko || echo "GUEST: insmod $m failed"
done
if ! mount -t hfsplus -o force /dev/vda /dst; then
	echo "GUEST: RESULT FAIL mount hfsplus"
	poweroff -f
fi
if ! mount -t 9p -o trans=virtio,version=9p2000.L,msize=524288,ro src /src; then
	echo "GUEST: RESULT FAIL mount 9p"
	umount /dst
	poweroff -f
fi
echo "GUEST: copying"
(cd /src && tar -cf - .) | tar -xf - -C /dst
rc=$?
sync
echo "GUEST: files $(find /dst | wc -l)"
df -k /dst
umount /src
umount /dst
sync
if [ $rc -eq 0 ]; then echo "GUEST: RESULT OK"; else echo "GUEST: RESULT FAIL tar $rc"; fi
poweroff -f
EOF
	chmod +x "$ird/init"
	(cd "$ird" && find . | cpio -o -H newc --quiet | gzip -1 > "$guest/initrd.gz")
	rm -rf "$guest/pkg"
}

apfs_mount "$os" os
apfs_mount "$sysos" sysos
apfs_mount "$appos" appos

mkdir -p "$stage"
copy() {
	echo "copying $1 -> ${2#"$stage"}"
	mkdir -p "$2"
	rsync -aH --numeric-ids "$1/" "$2/"
}
copy "$work/os/root" "$stage"
copy "$work/sysos/root" "$stage/private/preboot/Cryptexes/OS"
copy "$work/appos/root" "$stage/private/preboot/Cryptexes/App"
for m in "${mounts[@]}"; do umount "$m"; done
mounts=()
if [[ ${DELETE_INPUTS:-0} == 1 ]]; then
	rm -f "$os" "$sysos" "$appos"
fi

dsc=private/preboot/Cryptexes/OS/System/Library/Caches/com.apple.dyld
mkdir -p "$stage/System/Library/Caches/com.apple.dyld"
for f in "$stage/$dsc"/*; do
	ln "$f" "$stage/System/Library/Caches/com.apple.dyld/${f##*/}"
done

for c in OS App; do
	(cd "$stage/private/preboot/Cryptexes/$c" && find . ! -type d ! -path './System/Library/Caches/com.apple.dyld/*') |
	while IFS= read -r f; do
		f=${f#./}
		if [[ ! -e $stage/$f && ! -L $stage/$f ]]; then
			mkdir -p "$stage/$(dirname "$f")"
			src="$stage/private/preboot/Cryptexes/$c/$f"
			if [[ -L $src ]]; then cp -P "$src" "$stage/$f"; else ln "$src" "$stage/$f"; fi
			echo "linked $c:/$f"
		fi
	done
done

db="$stage/private/var/db"
install -d -o 272 -g 272 -m 0751 "$db/diagnostics"
install -d -o 272 -g 272 -m 0755 "$db/uuidtext" "$db/diagnostics/timesync"
for d in diagnostics uuidtext diagnostics/timesync; do
	install -o 272 -g 272 -m 0644 /dev/null "$db/$d/.migrated"
done

install -d -m 0700 -o 0 -g 0 "$stage/private/var/keybags"
printf '%s\n' '<?xml version="1.0" encoding="UTF-8"?>' \
	'<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">' \
	'<plist version="1.0"><dict><key>KeyBagKeys</key><data>U1dFRVQ=</data></dict></plist>' |
	install -m 0600 -o 0 -g 0 /dev/stdin "$stage/private/var/keybags/systembag.kb"

python3 "$here/sweet-root-tweaks.py" "$stage"
du -sh "$stage"

build_guest
truncate -s "$size" "$out"
mkfs.hfsplus -s -J -v iOSRoot "$out"
log="$out.qemu.log"
qemu-system-x86_64 -m 1536 -smp 2 -nographic -no-reboot \
	-kernel "$guest/vmlinuz" -initrd "$guest/initrd.gz" -append "console=ttyS0 quiet" \
	-drive "file=$out,format=raw,if=virtio,cache=unsafe" \
	-virtfs "local,path=$stage,mount_tag=src,security_model=passthrough,readonly=on" > "$log" 2>&1 || true
grep -a 'GUEST' "$log" || true
grep -aq 'GUEST: RESULT OK' "$log" || { echo "guest copy failed, see $log" >&2; exit 1; }

fsck.hfsplus -f -y "$out" | grep -v 'Illegal name' || true
fsck.hfsplus -f -n "$out"
echo "done: $out (staging tree left in $stage; delete it when no longer needed)"
