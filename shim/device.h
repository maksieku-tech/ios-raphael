/* By Maksieku */
#pragma once

#if defined(DEVICE_RAPHAEL)

#define DEVICE_NAME		"raphael"
#define DEVICE_FB_W		1080
#define DEVICE_FB_H		2340
#define DEVICE_FB_STRIDE	(1080 * 4)
#define DEVICE_IMEM_RESTART	0x146bf65cUL
#define DEVICE_PANEL_CMD	1
#define DEVICE_MDP_CTL0		0x0ae02000UL
#define DEVICE_MDP_PP0		0x0ae71000UL
#define DEVICE_MDP_BASE		0x0ae00000UL

#else

#define DEVICE_NAME		"sweet"
#define DEVICE_FB_W		1080
#define DEVICE_FB_H		2400
#define DEVICE_FB_STRIDE	(1080 * 4)
#define DEVICE_IMEM_RESTART	0x146aa65cUL
#define DEVICE_PANEL_CMD	0
#define DEVICE_MDP_CTL0		0UL
#define DEVICE_MDP_PP0		0UL
#define DEVICE_MDP_BASE		0UL

#endif
