#!/usr/bin/env python3
# By Maksieku
"""Count post-ARMv8.0 instructions in iOS code, to decide whether an
ARMv8.0 phone (Cortex-A53/A73, e.g. Redmi Note 11 "spes", SM6225) can run
the iPhone X userland without trapping and emulating them in the kernel.

  isa-scan.py FILE [FILE ...]

FILE is a Mach-O (thin arm64 or fat) or a dyld shared cache file, e.g.
research/dsc/dyld_shared_cache_arm64 and its .01 .02 ... subcaches.
Only executable mappings / __TEXT pure-instruction sections are scanned.
Counts are pattern matches on 32-bit words and can include a few false
positives from data inside code; a large LSE count is conclusive."""
import struct, sys

try:
    import numpy as np
except ImportError:
    raise SystemExit('needs numpy: pip install numpy')

PATTERNS = [
    ('v8.1 LSE atomics (LDADD/LDSET/SWP...)', 0x3f200c00, 0x38200000, (0x3fbffc00, 0x38bfc000)),
    ('v8.1 LSE CAS', 0x3fa07c00, 0x08a07c00, None),
    ('v8.1 LSE CASP', 0xbfa07c00, 0x08207c00, None),
    ('v8.1 RDM SQRDMLAH/SH (vector)', 0xbf20f400, 0x2e008400, None),
    ('v8.2 FP16 scalar arithmetic', 0xffe0cc00, 0x1ee00800, None),
    ('v8.2 DotProd SDOT/UDOT (vector)', 0x9fe0fc00, 0x0e809400, None),
    ('v8.2 DC CVAP', 0xffffffe0, 0xd50b7c20, None),
    ('v8.3 LDAPR (RCpc)', 0x3fbffc00, 0x38bfc000, None),
    ('v8.3 PAC (PACI[AB]SP/AUTI[AB]SP)', 0xffffff3f, 0xd503233f, None),
]


def ranges_macho(buf, base=0):
    magic, = struct.unpack_from('<I', buf, base)
    if magic == 0xbebafeca:
        n, = struct.unpack_from('>I', buf, 4)
        out = []
        for i in range(n):
            cputype, _, off, size, _ = struct.unpack_from('>5I', buf, 8 + 20 * i)
            if cputype == 0x0100000c:
                out += ranges_macho(buf, off)
        return out
    if magic != 0xfeedfacf:
        return None
    ncmds, = struct.unpack_from('<I', buf, base + 16)
    off, out = base + 32, []
    for _ in range(ncmds):
        cmd, size = struct.unpack_from('<II', buf, off)
        if cmd == 0x19:
            nsects, = struct.unpack_from('<I', buf, off + 64)
            for s in range(nsects):
                so = off + 72 + 80 * s
                sname = buf[so:so + 16].split(b'\0')[0].decode()
                ssize, soff = struct.unpack_from('<QI', buf, so + 40)[0], struct.unpack_from('<I', buf, so + 48)[0]
                flags, = struct.unpack_from('<I', buf, so + 64)
                if flags & 0x80000000 and ssize:
                    out.append((sname, base + soff, ssize))
        off += size
    return out


def ranges_cache(buf):
    if not buf.startswith(b'dyld_v1'):
        return None
    moff, mcount = struct.unpack_from('<II', buf, 0x10)
    out = []
    for i in range(mcount):
        addr, size, foff, maxp, initp = struct.unpack_from('<QQQII', buf, moff + 32 * i)
        if initp & 4 and size:
            out.append((f'mapping {i} @{addr:#x}', foff, min(size, len(buf) - foff)))
    return out


def scan(path):
    buf = open(path, 'rb').read()
    ranges = ranges_cache(buf) or ranges_macho(buf)
    if not ranges:
        print(f'{path}: not a Mach-O or dyld cache, or no code')
        return
    total = {name: 0 for name, *_ in PATTERNS}
    words = 0
    for name, off, size in ranges:
        size &= ~3
        w = np.frombuffer(buf, dtype='<u4', count=size // 4, offset=off)
        words += w.size
        for pname, mask, val, excl in PATTERNS:
            hit = (w & mask) == val
            if excl:
                hit &= (w & excl[0]) != excl[1]
            total[pname] += int(hit.sum())
    print(f'{path}: {words} instruction words in {len(ranges)} code range(s)')
    for pname, n in total.items():
        print(f'  {n:>10}  {pname}')


for f in sys.argv[1:] or sys.exit(__doc__):
    scan(f)
