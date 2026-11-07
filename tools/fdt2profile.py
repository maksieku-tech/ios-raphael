#!/usr/bin/env python3
# By Maksieku
"""Read a phone's live Android FDT and check the port's device profile.

  fdt2profile.py LIVE.dtb [--device raphael|sweet] [--json OUT.json]

Get LIVE.dtb from a recovery shell:  adb pull /sys/firmware/fdt live.dtb
Prints the hardware facts the SWEET port family depends on (RAM banks,
no-map carve-outs, splash framebuffer, GIC, UFS, SPMI, IMEM restart
reason, touchscreen bus and GPIOs, volume-up PMIC GPIO, selected panel and
its DSI mode, CPU MPIDRs) and, with --device, compares them against the
profile tools/mkadt.py builds. Exit status 1 if anything disagrees."""
import json, os, re, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class Node:
    def __init__(self, name, parent=None):
        self.name, self.parent, self.props, self.children = name, parent, {}, []

    def path(self):
        if self.parent is None:
            return '/'
        p = self.parent.path()
        return (p if p != '/' else '') + '/' + self.name

    def u32s(self, key):
        v = self.props.get(key)
        return list(struct.unpack('>%dI' % (len(v) // 4), v[:len(v) // 4 * 4])) if v else []

    def strs(self, key):
        v = self.props.get(key)
        return [x.decode(errors='replace') for x in v.split(b'\0') if x] if v else []

    def str(self, key):
        s = self.strs(key)
        return s[0] if s else None

    def cells(self, key='reg'):
        p = self.parent
        ac = p.u32s('#address-cells')[0] if p and '#address-cells' in p.props else 2
        sc = p.u32s('#size-cells')[0] if p and '#size-cells' in p.props else 1
        v, out = self.u32s(key), []
        step = ac + sc
        for i in range(0, len(v) - step + 1, step):
            a = 0
            for c in v[i:i + ac]:
                a = a << 32 | c
            s = 0
            for c in v[i + ac:i + step]:
                s = s << 32 | c
            out.append((a, s))
        return out

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


def parse(blob):
    magic, total, off_struct, off_strings = struct.unpack_from('>4I', blob, 0)
    if magic != 0xd00dfeed:
        raise SystemExit('not an FDT')
    p, root, cur = off_struct, None, None
    while True:
        tok, = struct.unpack_from('>I', blob, p)
        p += 4
        if tok == 1:
            end = blob.index(b'\0', p)
            name = blob[p:end].decode(errors='replace')
            p = (end + 4) & ~3
            n = Node(name, cur)
            if cur is None:
                root = n
            else:
                cur.children.append(n)
            cur = n
        elif tok == 2:
            cur = cur.parent
        elif tok == 3:
            ln, nameoff = struct.unpack_from('>II', blob, p)
            p += 8
            key = blob[off_strings + nameoff:blob.index(b'\0', off_strings + nameoff)].decode()
            cur.props[key] = blob[p:p + ln]
            p = (p + ln + 3) & ~3
        elif tok == 4:
            continue
        elif tok == 9:
            break
        else:
            raise SystemExit(f'bad FDT token {tok}')
    return root


def by_compat(root, *compats):
    return [n for n in root.walk() if any(c in n.strs('compatible') for c in compats)]


def okay(n):
    return n.str('status') in (None, 'ok', 'okay')


def analyse(root):
    facts, ph = {}, {}
    for n in root.walk():
        for k in ('phandle', 'linux,phandle'):
            if k in n.props:
                ph[n.u32s(k)[0]] = n
    mem = [n for n in root.children if n.name.split('@')[0] == 'memory']
    facts['memory'] = [(hex(a), hex(s)) for n in mem for a, s in n.cells() if s]
    resv = [n for n in root.children if n.name == 'reserved-memory']
    carve, splash = [], None
    for r in resv:
        for c in r.children:
            for a, s in c.cells():
                if 'no-map' in c.props:
                    carve.append((c.name, hex(a), hex(s)))
                if 'splash' in c.name or 'splash' in (c.str('label') or ''):
                    splash = (hex(a), hex(s))
    facts['no_map'] = carve
    facts['splash'] = splash
    for key, compats in (('gic', ('arm,gic-v3',)), ('ufs', ('qcom,ufshc',)),
                         ('spmi', ('qcom,spmi-pmic-arb',)), ('rsc', ('qcom,rpmh-rsc',))):
        nodes = [n for n in by_compat(root, *compats) if okay(n)]
        if nodes:
            n = nodes[0]
            names = n.strs('reg-names')
            regs = n.cells()
            facts[key] = {(names[i] if i < len(names) else str(i)): hex(a) for i, (a, s) in enumerate(regs)}
    imem = by_compat(root, 'qcom,msm-imem')
    if imem:
        base = imem[0].cells()[0][0]
        for c in imem[0].children:
            if c.name.startswith('restart_reason'):
                facts['imem_restart_reason'] = hex(base + c.u32s('reg')[0])
    cpus = [n for n in root.walk() if n.str('device_type') == 'cpu']
    facts['cpus'] = [(n.u32s('reg')[-1] if n.u32s('reg') else None, n.str('compatible')) for n in cpus]
    facts['cpus'] = [(hex(r) if r is not None else None, c) for r, c in facts['cpus']]
    touches = []
    for n in root.walk():
        c = n.str('compatible') or ''
        if okay(n) and n.parent is not None and re.match(r'(goodix|focaltech|fts|synaptics|novatek|st,|xiaomi,touch)', c) \
                and 'i2c' in ' '.join(n.parent.strs('compatible')):
            bus = n.parent
            t = {'compatible': c, 'addr': hex(n.u32s('reg')[0]) if n.u32s('reg') else None,
                 'bus': bus.path(), 'bus_reg': hex(bus.cells()[0][0]) if bus.cells() else None}
            for k, v in n.props.items():
                if k.endswith('-gpio') or k.endswith('-gpios'):
                    cells = n.u32s(k)
                    ctl = ph.get(cells[0])
                    t[k] = (ctl.name if ctl else hex(cells[0]), cells[1] if len(cells) > 1 else None)
            for k in ('goodix,panel-max-x', 'goodix,panel-max-y'):
                if k in n.props:
                    t[k] = n.u32s(k)[0]
            pins = []
            for pk in ('pinctrl-0',):
                for h in bus.u32s(pk):
                    st = ph.get(h)
                    for sub in ([st] + st.children) if st else []:
                        if 'pins' in sub.props:
                            pins.append((sub.strs('pins'), sub.str('function')))
            t['bus_pins'] = pins
            touches.append(t)
    facts['touch'] = touches
    keys = []
    for n in by_compat(root, 'gpio-keys'):
        for c in n.children:
            if 'gpios' in c.props:
                cells = c.u32s('gpios')
                ctl = ph.get(cells[0])
                entry = {'label': c.str('label'), 'code': c.u32s('linux,code')[0] if 'linux,code' in c.props else None,
                         'controller': ctl.path() if ctl else None, 'gpio': cells[1]}
                if ctl is not None and ctl.u32s('reg'):
                    base = ctl.u32s('reg')[0]
                    pmic = ctl.parent
                    sid = pmic.u32s('reg')[0] if pmic is not None and pmic.u32s('reg') else None
                    entry['pmic_sid'] = sid
                    entry['gpio_base'] = hex(base + (cells[1] - 1) * 0x100)
                    if sid is not None:
                        entry['ppid'] = hex((sid << 8) | ((base + (cells[1] - 1) * 0x100) >> 8))
                keys.append(entry)
    facts['keys'] = keys
    chosen = [n for n in root.children if n.name == 'chosen']
    boot = chosen[0].str('bootargs') if chosen else None
    m = re.search(r'msm_drm\.dsi_display0=([^ :]+)', boot or '')
    facts['bootargs_display'] = m.group(1) if m else None
    panels = []
    for n in root.walk():
        if 'qcom,mdss-dsi-panel-type' in n.props:
            w = h = None
            for c in n.walk():
                if 'qcom,mdss-dsi-panel-width' in c.props:
                    w, h = c.u32s('qcom,mdss-dsi-panel-width')[0], c.u32s('qcom,mdss-dsi-panel-height')[0]
                    break
            panels.append({'node': n.name, 'name': n.str('qcom,mdss-dsi-panel-name'),
                           'type': n.str('qcom,mdss-dsi-panel-type'), 'size': (w, h)})
    if facts['bootargs_display']:
        disp = [n for n in root.walk() if n.str('label') == facts['bootargs_display']]
        if disp and 'qcom,dsi-panel' in disp[0].props:
            pn = ph.get(disp[0].u32s('qcom,dsi-panel')[0])
            panels = [p for p in panels if pn is not None and p['node'] == pn.name] or panels
            facts['panel_selected'] = True
    facts['panels'] = panels
    return facts


def compare(facts, device):
    import mkadt
    prof = {k: v for k, kind, v in mkadt.DEVICES[device]['profile']}
    dev = mkadt.DEVICES[device]
    bad = []

    def check(what, ok, detail):
        print(f'  [{"ok" if ok else "MISMATCH"}] {what}: {detail}')
        if not ok:
            bad.append(what)

    h = lambda v: int(v, 16) if isinstance(v, str) else v
    if facts.get('memory'):
        lo, size = mkadt.HIGH_PHYS_BASE, mkadt.HIGH_MEM_SIZE
        inside = any(h(a) <= lo and lo + size <= h(a) + h(s) for a, s in facts['memory'])
        check('highmem kernel RAM inside a bank', inside, f'{lo:#x}+{size:#x} vs {facts["memory"]}')
        hits = [c for c in facts['no_map'] if h(c[1]) < lo + size and lo < h(c[1]) + h(c[2])]
        check('highmem kernel RAM clear of no-map carve-outs', not hits, hits or 'none')
    else:
        print('  [skip] no RAM banks (compiled DT, not a live FDT)')
    if facts.get('splash'):
        check('splash framebuffer at 0x9c000000', h(facts['splash'][0]) == mkadt.FB, facts['splash'])
    if 'gic' in facts:
        vals = list(facts['gic'].values())
        check('GICD/GICR', h(vals[0]) == mkadt.GICD and h(vals[1]) == mkadt.GICR, facts['gic'])
    if 'ufs' in facts:
        check('UFS host', h(list(facts['ufs'].values())[0]) == mkadt.UFS, facts['ufs'])
    if 'spmi' in facts and 'spmi-core' in prof:
        s = facts['spmi']
        check('SPMI core/obsrvr/cnfg', h(s.get('core')) == prof['spmi-core'] and h(s.get('obsrvr')) == prof['spmi-obsrvr']
              and h(s.get('cnfg')) == prof['spmi-cnfg'], s)
    if facts['touch'] and 'touch-se' in prof:
        t = facts['touch'][0]
        check('touch bus (QUP SE)', h(t['bus_reg']) == prof['touch-se'], f'{t["bus"]} {t["bus_reg"]}')
        check('touch I2C address', h(t['addr']) == prof['touch-addr'], t['addr'])
        rst = [v for k, v in t.items() if 'reset' in k and isinstance(v, tuple)]
        irq = [v for k, v in t.items() if 'irq' in k and isinstance(v, tuple)]
        if rst:
            check('touch reset GPIO', rst[0][1] == prof['touch-reset'], rst[0])
        if irq:
            check('touch IRQ GPIO', irq[0][1] == prof['touch-irq'], irq[0])
        pw = sorted(v[1] for k, v in t.items() if ('vdd' in k) and isinstance(v, tuple))
        if pw:
            check('touch power GPIOs', pw == sorted(prof['touch-power-gpios']), pw)
        pins = [int(p[4:]) for ps, f in t['bus_pins'] for p in ps if p.startswith('gpio')]
        if pins:
            check('touch SDA/SCL pins', sorted(set(pins)) == sorted({prof['touch-sda'], prof['touch-scl']}), t['bus_pins'])
        if 'goodix,panel-max-y' in t:
            check('touch max y', t['goodix,panel-max-y'] == prof['touch-max-y'], t['goodix,panel-max-y'])
    volup = [k for k in facts['keys'] if k['code'] == 115]
    if volup and 'keys-volup-ppid' in prof:
        k = volup[0]
        check('volume-up PMIC GPIO', h(k.get('ppid')) == prof['keys-volup-ppid'] and h(k.get('gpio_base')) == prof['keys-volup-base'], k)
    if facts['panels']:
        p = facts['panels'][0]
        cmd = p['type'] == 'dsi_cmd_mode'
        check('panel mode matches profile', cmd == ('panel-ctl-start' in prof and prof['panel-ctl-start'] != 0),
              f'{p["name"]} {p["type"]} {p["size"]}' + ('' if facts.get('panel_selected') else ' (not selected by bootargs; first candidate)'))
        if p['size'][1]:
            check('panel height matches profile', p['size'] == (dev['fb_w'], dev['fb_h']), p['size'])
    if facts['cpus']:
        regs = [int(r, 16) & 0xffff for r, c in facts['cpus'] if r]
        check('CPU MPIDRs core<<8', regs == [i << 8 for i in range(len(regs))], facts['cpus'])
    return bad


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    facts = analyse(parse(open(sys.argv[1], 'rb').read()))
    for k, v in facts.items():
        print(f'{k}: {v}')
    if '--json' in sys.argv:
        json.dump(facts, open(sys.argv[sys.argv.index('--json') + 1], 'w'), indent=1, default=str)
    if '--device' in sys.argv:
        device = sys.argv[sys.argv.index('--device') + 1]
        print(f'\nchecking against the {device} profile:')
        bad = compare(facts, device)
        print(f'\n{len(bad)} mismatch(es)' + (': ' + ', '.join(bad) if bad else ''))
        sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
