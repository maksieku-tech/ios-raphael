/* By Maksieku */
#pragma once
#include <stdint.h>

/* Read a u32/u64 (cell-size agnostic) property of /chosen. Returns 0 if absent. */
int fdt_chosen_u64(uintptr_t fdt, const char *prop, uint64_t *out);

#define FDT_RANGE_NO_MEMORY	1
#define FDT_RANGE_OUTSIDE	2
#define FDT_RANGE_RESERVED	3

int fdt_check_range(uintptr_t fdt, uint64_t base, uint64_t size, uint64_t *hit);
