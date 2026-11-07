/* By Maksieku */
#pragma once
#include <stdint.h>

struct panel_state {
	uint32_t cmd_mode;
	uint32_t te_before, ar_before, ar_after, ctl_flush;
	uint32_t autorefresh;
	uint32_t kicks;
	uint32_t hold;
	int32_t pipe;
	uint32_t pipe_addr, fmt_before, fmt_after, stride_before, stride_after;
	uint32_t src_size, out_size, out_xy, unpack_before, fetch, opmode;
};

extern struct panel_state panel;

void panel_init(void);
void panel_flush(void);
void panel_report(void);
void panel_probe(void);
