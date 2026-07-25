#pragma once
// Minimal host stand-in for the IDF partition API (tools/hstest only).
#include <stdint.h>
#include <stddef.h>
typedef int esp_err_t;
#define ESP_OK 0
typedef enum { ESP_PARTITION_TYPE_DATA = 1 } esp_partition_type_t;
typedef enum { ESP_PARTITION_SUBTYPE_ANY = 0xff } esp_partition_subtype_t;
typedef struct { uint32_t size; } esp_partition_t;
const esp_partition_t *esp_partition_find_first(esp_partition_type_t,
                                                esp_partition_subtype_t,
                                                const char *label);
esp_err_t esp_partition_read(const esp_partition_t *, size_t off, void *dst, size_t n);
esp_err_t esp_partition_write(const esp_partition_t *, size_t off, const void *src, size_t n);
esp_err_t esp_partition_erase_range(const esp_partition_t *, size_t off, size_t n);
