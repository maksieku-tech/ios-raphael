/* By Maksieku */
/*
 * Just enough flattened-device-tree parsing to find what ABL put in
 * /chosen (initrd location). Big-endian, 4-byte aligned tokens.
 */
#include "fdt.h"

#define FDT_MAGIC	0xd00dfeed
#define FDT_BEGIN_NODE	1
#define FDT_END_NODE	2
#define FDT_PROP	3
#define FDT_NOP		4
#define FDT_END		9

static uint32_t be32(uintptr_t a)
{
	return __builtin_bswap32(*(volatile uint32_t *)a);
}

static int streq(const char *a, const char *b)
{
	while (*a && *a == *b)
		a++, b++;
	return *a == *b;
}

static uintptr_t align4(uintptr_t a)
{
	return (a + 3) & ~3UL;
}

static uintptr_t skip_str(uintptr_t p)
{
	/* byte loads are fine on Device memory as long as they are aligned to 1 */
	while (*(volatile char *)p)
		p++;
	return p + 1;
}

int fdt_chosen_u64(uintptr_t fdt, const char *prop, uint64_t *out)
{
	if (!fdt || be32(fdt) != FDT_MAGIC)
		return 0;
	uintptr_t p = fdt + be32(fdt + 8);		/* off_dt_struct */
	uintptr_t strings = fdt + be32(fdt + 12);	/* off_dt_strings */
	int depth = 0, in_chosen = 0;

	for (;;) {
		uint32_t tok = be32(p);
		p += 4;
		switch (tok) {
		case FDT_BEGIN_NODE: {
			const char *name = (const char *)p;
			depth++;
			in_chosen = depth == 2 && streq(name, "chosen");
			p = align4(skip_str(p));
			break;
		}
		case FDT_END_NODE:
			if (in_chosen)
				return 0;
			depth--;
			break;
		case FDT_PROP: {
			uint32_t len = be32(p), nameoff = be32(p + 4);
			uintptr_t val = p + 8;
			if (in_chosen && streq((const char *)(strings + nameoff), prop)) {
				if (len == 4)
					*out = be32(val);
				else if (len == 8)
					*out = (uint64_t)be32(val) << 32 | be32(val + 4);
				else
					return 0;
				return 1;
			}
			p = align4(val + len);
			break;
		}
		case FDT_NOP:
			break;
		default:	/* FDT_END or garbage */
			return 0;
		}
	}
}

static uint64_t cells(uintptr_t p, uint32_t n)
{
	uint64_t v = 0;
	for (uint32_t i = 0; i < n; i++)
		v = v << 32 | be32(p + 4 * i);
	return v;
}

static int prefix(const char *s, const char *pre)
{
	while (*pre && *s == *pre)
		s++, pre++;
	return *pre == 0 && (*s == 0 || *s == '@');
}

int fdt_check_range(uintptr_t fdt, uint64_t base, uint64_t size, uint64_t *hit)
{
	if (!fdt || be32(fdt) != FDT_MAGIC)
		return 0;
	uintptr_t p = fdt + be32(fdt + 8);
	uintptr_t strings = fdt + be32(fdt + 12);
	uint32_t ac = 2, sc = 2;
	int depth = 0, in_mem = 0, in_resv = 0, resv_depth = 0, nomap = 0;
	int mem_seen = 0, covered = 0, reserved = 0;
	uint64_t end = base + size, rbase = 0, rsize = 0;
	int have_reg = 0;

	for (;;) {
		uint32_t tok = be32(p);
		p += 4;
		switch (tok) {
		case FDT_BEGIN_NODE: {
			const char *name = (const char *)p;
			depth++;
			if (depth == 2) {
				in_mem = prefix(name, "memory");
				in_resv = prefix(name, "reserved-memory");
				resv_depth = depth;
			}
			nomap = 0;
			have_reg = 0;
			p = align4(skip_str(p));
			break;
		}
		case FDT_END_NODE:
			if (in_resv && depth == resv_depth + 1 && have_reg && nomap &&
			    rbase < end && base < rbase + rsize) {
				reserved = 1;
				*hit = rbase;
			}
			if (depth == 2)
				in_mem = in_resv = 0;
			depth--;
			if (depth == 0)
				goto done;
			break;
		case FDT_PROP: {
			uint32_t len = be32(p), nameoff = be32(p + 4);
			uintptr_t val = p + 8;
			const char *pname = (const char *)(strings + nameoff);
			if (depth == 1 && streq(pname, "#address-cells"))
				ac = be32(val);
			else if (depth == 1 && streq(pname, "#size-cells"))
				sc = be32(val);
			else if (in_mem && depth == 2 && streq(pname, "reg")) {
				for (uint32_t off = 0; off + 4 * (ac + sc) <= len; off += 4 * (ac + sc)) {
					uint64_t mb = cells(val + off, ac), ms = cells(val + off + 4 * ac, sc);
					if (ms)
						mem_seen = 1;
					if (base >= mb && end <= mb + ms)
						covered = 1;
				}
			} else if (in_resv && depth == resv_depth + 1 && streq(pname, "reg") && len >= 4 * (ac + sc)) {
				rbase = cells(val, ac);
				rsize = cells(val + 4 * ac, sc);
				have_reg = 1;
			} else if (in_resv && depth == resv_depth + 1 && streq(pname, "no-map"))
				nomap = 1;
			p = align4(val + len);
			break;
		}
		case FDT_NOP:
			break;
		default:
			goto done;
		}
	}
done:
	if (!mem_seen)
		return FDT_RANGE_NO_MEMORY;
	if (!covered)
		return FDT_RANGE_OUTSIDE;
	if (reserved)
		return FDT_RANGE_RESERVED;
	return 0;
}
