/* By Maksieku */
#include "console.h"
#include "font.h"
#include "panel.h"

#define SCALE		3
#define CH_W		(8 * SCALE)
#define CH_H		(16 * SCALE)
#define MARGIN		24
#define LABEL_COLS	8

volatile uint32_t *con_fb = (volatile uint32_t *)FB_BASE;
static uint32_t con_bpp = 4;
static uint32_t con_stride = FB_STRIDE;
static uint32_t con_bg;
static int row;

void con_mode(uint32_t bpp, uint32_t stride)
{
	con_bpp = bpp == 3 ? 3 : 4;
	con_stride = stride ? stride : FB_W * con_bpp;
}

uint32_t con_get_bpp(void)
{
	return con_bpp;
}

static void fill_run(int x, int y, int n, uint32_t c)
{
	volatile uint8_t *base = (volatile uint8_t *)con_fb + (uintptr_t)y * con_stride;
	if (con_bpp == 4) {
		volatile uint32_t *p = (volatile uint32_t *)(base + (uintptr_t)x * 4);
		for (int i = 0; i < n; i++)
			p[i] = c;
		return;
	}
	volatile uint8_t *p = base + (uintptr_t)x * 3;
	uint8_t b = c & 0xff, g = (c >> 8) & 0xff, r = (c >> 16) & 0xff;
	for (int i = 0; i < n; i++) {
		p[0] = b;
		p[1] = g;
		p[2] = r;
		p += 3;
	}
}

void con_clear(uint32_t bg)
{
	for (int y = 0; y < FB_H; y++)
		fill_run(0, y, FB_W, bg);
	con_bg = bg;
	row = 0;
	panel_flush();
}

static void put_char(int col, char ch, uint32_t fg)
{
	if (ch < 0x20 || ch > 0x7e)
		ch = '?';
	const unsigned char *g = font8x16[ch - 0x20];
	int x0 = MARGIN + col * CH_W, y0 = MARGIN + row * CH_H;
	if (x0 + CH_W > FB_W || y0 + CH_H > FB_H)
		return;
	for (int gy = 0; gy < 16; gy++)
		for (int gx = 0; gx < 8; gx++) {
			uint32_t c = (g[gy] & (0x80 >> gx)) ? fg : con_bg;
			for (int sy = 0; sy < SCALE; sy++)
				fill_run(x0 + gx * SCALE, y0 + gy * SCALE + sy, SCALE, c);
		}
}

static int put_str(int col, const char *s, uint32_t fg)
{
	while (*s)
		put_char(col++, *s++, fg);
	return col;
}

static void fmt_hex(char *buf, uint64_t v, int digits)
{
	static const char hex[] = "0123456789ABCDEF";
	for (int i = 0; i < digits; i++)
		buf[i] = hex[(v >> (4 * (digits - 1 - i))) & 0xf];
	buf[digits] = 0;
}

void con_skip(void)
{
	row++;
}

void con_str(const char *label, const char *s)
{
	put_str(0, label, YELLOW);
	put_str(LABEL_COLS, s, WHITE);
	row++;
	panel_flush();
}

void con_hex(const char *label, uint64_t v)
{
	char buf[17];
	fmt_hex(buf, v, 16);
	con_str(label, buf);
}

void con_hex2(const char *label, const char *a, uint32_t va, const char *b, uint32_t vb)
{
	char buf[9];
	int col = put_str(0, label, YELLOW);
	col = col < LABEL_COLS ? LABEL_COLS : col + 1;
	col = put_str(col, a, YELLOW);
	fmt_hex(buf, va, 8);
	col = put_str(col, buf, WHITE);
	if (b) {
		col = put_str(col + 1, b, YELLOW);
		fmt_hex(buf, vb, 8);
		put_str(col, buf, WHITE);
	}
	row++;
	panel_flush();
}
