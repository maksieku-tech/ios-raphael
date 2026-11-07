#!/usr/bin/env python3
# By Maksieku
"""Split a stock Image.gz-dtb kernel (Android boot header v0/v1) into the
gzip kernel and the appended DTB blob(s).

  split-kernel-dtb.py KERNEL OUTDIR

Writes OUTDIR/kernel_dtb (all appended DTBs, concatenated, as ABL expects
them after the kernel) and OUTDIR/dtb.N for each one."""
import os, struct, sys, zlib

src, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
data = open(src, 'rb').read()
if data[:2] == b'\x1f\x8b':
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    d.decompress(data)
    tail = d.unused_data
    kind = 'gzip'
else:
    if data[56:60] != b'ARM\x64':
        raise SystemExit('neither gzip nor an arm64 Image')
    image_size, = struct.unpack_from('<Q', data, 16)
    tail = data[image_size:]
    kind = 'Image'
start = tail.find(b'\xd0\x0d\xfe\xed')
if start < 0:
    raise SystemExit('no appended DTB found')
tail = tail[start:]
blobs, off = [], 0
while off + 8 <= len(tail) and tail[off:off + 4] == b'\xd0\x0d\xfe\xed':
    size, = struct.unpack_from('>I', tail, off + 4)
    blobs.append(tail[off:off + size])
    off += size
open(os.path.join(out, 'kernel_dtb'), 'wb').write(b''.join(blobs))
for i, b in enumerate(blobs):
    open(os.path.join(out, f'dtb.{i}'), 'wb').write(b)
print(f'{kind} kernel, {len(blobs)} DTB(s), {sum(map(len, blobs))} bytes -> {out}/kernel_dtb')
