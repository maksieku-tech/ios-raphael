#!/usr/bin/env python3
# By Maksieku
import hashlib
import json
import os
import plistlib
import struct
import sys
import time
import zipfile

PART = 390 * 1024 * 1024
WANT = {
    'OS': 'os.dmg',
    'Cryptex1,SystemOS': 'systemos.dmg',
    'Cryptex1,AppOS': 'appos.dmg',
    'DeviceTree': 'devicetree.im4p',
}


def pick_identity(manifest, board):
    for ident in manifest['BuildIdentities']:
        info = ident.get('Info', {})
        if info.get('DeviceClass', '').lower() != board:
            continue
        if 'erase' not in info.get('RestoreBehavior', '').lower():
            continue
        return ident
    raise SystemExit(f'no Erase identity for {board} in BuildManifest.plist')


def data_offset(f, info):
    f.seek(info.header_offset)
    hdr = f.read(30)
    if hdr[:4] != b'PK\x03\x04':
        raise SystemExit(f'bad local header for {info.filename}')
    nlen, xlen = struct.unpack('<HH', hdr[26:30])
    return info.header_offset + 30 + nlen + xlen


def plan(ipsw, outdir):
    z = zipfile.ZipFile(ipsw)
    manifest = plistlib.loads(z.read('BuildManifest.plist'))
    ident = pick_identity(manifest, 'd22ap')
    out = {'ipsw': os.path.basename(ipsw), 'ProductVersion': manifest.get('ProductVersion'),
           'ProductBuildVersion': manifest.get('ProductBuildVersion'), 'files': []}
    with open(ipsw, 'rb') as f:
        for key, name in WANT.items():
            path = ident['Manifest'][key]['Info']['Path']
            info = z.getinfo(path)
            if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                raise SystemExit(f'{path}: unsupported zip method {info.compress_type}')
            off = data_offset(f, info)
            parts = []
            pos = 0
            n = 0
            while pos < info.compress_size:
                size = min(PART, info.compress_size - pos)
                parts.append({'name': f'{name}.part{n:02d}', 'offset': off + pos, 'size': size})
                pos += size
                n += 1
            out['files'].append({'key': key, 'path': path, 'name': name, 'size': info.file_size,
                                 'compress_size': info.compress_size, 'method': info.compress_type,
                                 'crc32': info.CRC, 'parts': parts})
            print(f'{key}: {path} {info.file_size} bytes, method {info.compress_type}, {info.compress_size} stored, {len(parts)} parts')
    with open(os.path.join(outdir, 'manifest.json'), 'w') as f:
        json.dump(out, f, indent=1)
    return out


def done_ok(outdir, part):
    p = os.path.join(outdir, part['name'])
    s = os.path.join(outdir, part['name'] + '.sha256')
    return os.path.exists(p) and os.path.getsize(p) == part['size'] and os.path.exists(s)


def work(ipsw, outdir, budget):
    with open(os.path.join(outdir, 'manifest.json')) as f:
        m = json.load(f)
    start = time.time()
    with open(ipsw, 'rb') as src:
        for fe in m['files']:
            for part in fe['parts']:
                if done_ok(outdir, part):
                    continue
                if time.time() - start > budget:
                    print('budget used, run again')
                    return False
                h = hashlib.sha256()
                src.seek(part['offset'])
                left = part['size']
                with open(os.path.join(outdir, part['name']), 'wb') as dst:
                    while left:
                        chunk = src.read(min(8 * 1024 * 1024, left))
                        if not chunk:
                            raise SystemExit('short read from the IPSW')
                        dst.write(chunk)
                        h.update(chunk)
                        left -= len(chunk)
                with open(os.path.join(outdir, part['name'] + '.sha256'), 'w') as f:
                    f.write(h.hexdigest() + '\n')
                print(f"{part['name']} {part['size']} {time.time() - start:.0f}s", flush=True)
    print('all parts done')
    return True


def main():
    if len(sys.argv) < 3:
        raise SystemExit('usage: ipsw-split.py FIRMWARE.ipsw OUTDIR [SECONDS]')
    ipsw, outdir = sys.argv[1], sys.argv[2]
    budget = float(sys.argv[3]) if len(sys.argv) > 3 else 1e9
    os.makedirs(outdir, exist_ok=True)
    if not os.path.exists(os.path.join(outdir, 'manifest.json')):
        plan(ipsw, outdir)
    sys.exit(0 if work(ipsw, outdir, budget) else 3)


if __name__ == '__main__':
    main()
