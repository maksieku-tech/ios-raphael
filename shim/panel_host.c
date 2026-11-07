/* By Maksieku */
#include "panel.h"

struct panel_state panel;

void panel_flush(void)
{
	panel.kicks++;
}
