/* By Maksieku */
#include <stdint.h>
#include "device.h"
#include "console.h"
#include "panel.h"

#define CTL_FLUSH		0x018
#define CTL_START		0x01c
#define PP_TEAR_CHECK_EN	0x000
#define PP_AUTOREFRESH		0x030
#define PP_AUTOREFRESH_EN	(1U << 31)
#define SPLASH_BASE		0x9c000000UL

struct panel_state panel;

static inline uint32_t rd32(uintptr_t a)
{
	return *(volatile uint32_t *)a;
}

static inline void wr32(uintptr_t a, uint32_t v)
{
	__asm__ volatile("dsb sy" ::: "memory");
	*(volatile uint32_t *)a = v;
	__asm__ volatile("dsb sy" ::: "memory");
}

static void panel_delay_ms(unsigned ms)
{
	uint64_t f, t0, t;
	__asm__ volatile("isb; mrs %0, cntfrq_el0" : "=r"(f));
	__asm__ volatile("isb; mrs %0, cntpct_el0" : "=r"(t0));
	do
		__asm__ volatile("isb; mrs %0, cntpct_el0" : "=r"(t));
	while (t - t0 < f / 1000 * ms);
}

static void panel_kick(void)
{
	if (!DEVICE_PANEL_CMD || panel.autorefresh)
		return;
	wr32(DEVICE_MDP_CTL0 + CTL_START, 1);
	panel.kicks++;
}

void panel_init(void)
{
	panel.cmd_mode = DEVICE_PANEL_CMD;
	panel.pipe = -1;
	panel.autorefresh = 1;
	con_fb = (volatile uint32_t *)SPLASH_BASE;
	con_mode(4, DEVICE_FB_STRIDE);
}

void panel_flush(void)
{
	if (!panel.hold)
		panel_kick();
}

void panel_report(void)
{
	con_str("PANEL", panel.cmd_mode ? "cmd mode, MDP untouched" : "video mode");
}

static void bands(void)
{
	static const uint32_t colors[3] = { 0xffff0000U, 0xff00ff00U, 0xff0000ffU };
	for (int y = 0; y < DEVICE_FB_H; y++) {
		uint32_t c = colors[y * 3 / DEVICE_FB_H];
		volatile uint32_t *line = (volatile uint32_t *)SPLASH_BASE + (uintptr_t)y * (DEVICE_FB_STRIDE / 4);
		for (int x = 0; x < DEVICE_FB_W; x++)
			line[x] = x < 120 ? 0xffffffffU : c;
	}
	panel_kick();
}

void panel_probe(void)
{
	if (!DEVICE_PANEL_CMD)
		return;
	bands();
	panel_delay_ms(10000);
	con_clear(0xff000000U);
	con_str("PANEL", "status");
	con_skip();
	panel_report();
	panel_delay_ms(20000);
}
