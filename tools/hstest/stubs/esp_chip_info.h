#pragma once
typedef struct { int model; int revision; } esp_chip_info_t;
void esp_chip_info(esp_chip_info_t *out);
