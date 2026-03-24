#include "DppProvisioning.h"
#include "Arduino.h"
#include "common.h"

#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_dpp.h"
#include "nvs_flash.h"

#define DPP_URI_READY_BIT     BIT0
#define DPP_CONNECTED_BIT     BIT1
#define DPP_CONNECT_FAIL_BIT  BIT2
#define DPP_AUTH_FAIL_BIT     BIT3

#define DPP_MAX_CONNECT_RETRY 3
#define DPP_MAX_AUTH_RETRY    5

static EventGroupHandle_t s_dpp_event_group;
static wifi_config_t *s_dpp_wifi_config;
static char *s_dpp_uri;
static int s_retry_num;

#define DPP_URI_BUF_SIZE 300

static void dpp_event_handler(void *arg, esp_event_base_t event_base,
                              int32_t event_id, void *event_data)
{
    if (event_base == WIFI_EVENT) {
        switch (event_id) {
        case WIFI_EVENT_STA_START:
            ESP_ERROR_CHECK(esp_supp_dpp_start_listen());
            LOGI("DPP: WiFi started, listening for authentication");
            break;

        case WIFI_EVENT_STA_DISCONNECTED:
            if (s_retry_num < DPP_MAX_CONNECT_RETRY) {
                esp_wifi_connect();
                s_retry_num++;
                LOGI("DPP: WiFi disconnected, retry %d/%d", s_retry_num, DPP_MAX_CONNECT_RETRY);
            } else {
                xEventGroupSetBits(s_dpp_event_group, DPP_CONNECT_FAIL_BIT);
            }
            break;

        case WIFI_EVENT_DPP_URI_READY: {
            wifi_event_dpp_uri_ready_t *uri_data = (wifi_event_dpp_uri_ready_t *)event_data;
            if (uri_data && uri_data->uri) {
                strncpy(s_dpp_uri, (const char *)uri_data->uri, DPP_URI_BUF_SIZE - 1);
                s_dpp_uri[DPP_URI_BUF_SIZE - 1] = '\0';
                xEventGroupSetBits(s_dpp_event_group, DPP_URI_READY_BIT);
            }
            break;
        }

        case WIFI_EVENT_DPP_CFG_RECVD: {
            wifi_event_dpp_config_received_t *config = (wifi_event_dpp_config_received_t *)event_data;
            memcpy(s_dpp_wifi_config, &config->wifi_cfg, sizeof(*s_dpp_wifi_config));
            s_retry_num = 0;
            LOGI("DPP: credentials received, connecting to %s", s_dpp_wifi_config->sta.ssid);
            esp_wifi_set_config(WIFI_IF_STA, s_dpp_wifi_config);
            esp_wifi_connect();
            break;
        }

        case WIFI_EVENT_DPP_FAILED: {
            wifi_event_dpp_failed_t *fail = (wifi_event_dpp_failed_t *)event_data;
            if (s_retry_num < DPP_MAX_AUTH_RETRY) {
                LOGI("DPP: auth failed (%s), retry %d/%d",
                     esp_err_to_name((int)fail->failure_reason),
                     s_retry_num + 1, DPP_MAX_AUTH_RETRY);
                esp_supp_dpp_start_listen();
                s_retry_num++;
            } else {
                xEventGroupSetBits(s_dpp_event_group, DPP_AUTH_FAIL_BIT);
            }
            break;
        }

        default:
            break;
        }
    }
    if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        LOGI("DPP: got IP address");
        xEventGroupSetBits(s_dpp_event_group, DPP_CONNECTED_BIT);
    }
}

DppResult run_dpp_provisioning(uint32_t timeout_ms,
                               void (*display_cb)(const char *uri))
{
    DppResult result = {};
    s_retry_num = 0;

    // Heap-allocate buffers to avoid permanent BSS (pioarduino's ~48KB DRAM ceiling)
    s_dpp_uri = (char *)calloc(DPP_URI_BUF_SIZE, 1);
    s_dpp_wifi_config = (wifi_config_t *)calloc(1, sizeof(wifi_config_t));
    if (!s_dpp_uri || !s_dpp_wifi_config) {
        free(s_dpp_uri); free(s_dpp_wifi_config);
        s_dpp_uri = NULL; s_dpp_wifi_config = NULL;
        LOGI("DPP: failed to allocate buffers");
        return result;
    }

    // NVS is required by WiFi — initialize if not already done (e.g. after flash erase)
    esp_err_t nvs_err = nvs_flash_init();
    if (nvs_err == ESP_ERR_NVS_NO_FREE_PAGES || nvs_err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        nvs_flash_erase();
        nvs_flash_init();
    }

    // Ensure WiFi is started (may already be running from a prior WiFi.begin attempt)
    esp_err_t err = esp_wifi_start();
    if (err != ESP_OK && err != ESP_ERR_WIFI_CONN) {
        LOGI("DPP: esp_wifi_start failed: %s (may already be started)", esp_err_to_name(err));
    }

    s_dpp_event_group = xEventGroupCreate();

    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID,
                                               &dpp_event_handler, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP,
                                               &dpp_event_handler, NULL));

    ESP_ERROR_CHECK(esp_supp_dpp_init(NULL));
    // Listen on all common 2.4GHz channels (ESP32 doesn't support 5GHz).
    // Max 5 channels per ESP_DPP_MAX_CHAN_COUNT — cover the most common ones.
    ESP_ERROR_CHECK(esp_supp_dpp_bootstrap_gen("1,4,6,9,11", DPP_BOOTSTRAP_QR_CODE, NULL, NULL));
    // Don't call start_listen here — wait for STA_START event (see event handler)

    LOGI("DPP: listening for provisioning (timeout %lu ms)", (unsigned long)timeout_ms);

    // Wait for the bootstrap URI to be generated
    EventBits_t bits = xEventGroupWaitBits(s_dpp_event_group,
                                           DPP_URI_READY_BIT,
                                           pdFALSE, pdFALSE,
                                           pdMS_TO_TICKS(5000));
    if (bits & DPP_URI_READY_BIT) {
        LOGI("DPP URI: %s", s_dpp_uri);
        if (display_cb) {
            display_cb(s_dpp_uri);
        }
    } else {
        LOGI("DPP: URI not ready within 5s, continuing without display");
    }

    // Wait for connection result or timeout
    bits = xEventGroupWaitBits(s_dpp_event_group,
                               DPP_CONNECTED_BIT | DPP_CONNECT_FAIL_BIT | DPP_AUTH_FAIL_BIT,
                               pdFALSE, pdFALSE,
                               pdMS_TO_TICKS(timeout_ms));

    if (bits & DPP_CONNECTED_BIT) {
        result.success = true;
        strncpy(result.ssid, (const char *)s_dpp_wifi_config->sta.ssid, sizeof(result.ssid) - 1);
        strncpy(result.password, (const char *)s_dpp_wifi_config->sta.password, sizeof(result.password) - 1);
        LOGI("DPP: provisioned successfully for SSID: %s", result.ssid);
    } else if (bits & DPP_CONNECT_FAIL_BIT) {
        LOGI("DPP: failed to connect to provisioned network");
    } else if (bits & DPP_AUTH_FAIL_BIT) {
        LOGI("DPP: authentication failed after %d retries", DPP_MAX_AUTH_RETRY);
    } else {
        LOGI("DPP: timed out waiting for provisioning");
    }

    // Cleanup
    esp_supp_dpp_deinit();
    esp_event_handler_unregister(IP_EVENT, IP_EVENT_STA_GOT_IP, &dpp_event_handler);
    esp_event_handler_unregister(WIFI_EVENT, ESP_EVENT_ANY_ID, &dpp_event_handler);
    vEventGroupDelete(s_dpp_event_group);
    s_dpp_event_group = NULL;
    free(s_dpp_uri); s_dpp_uri = NULL;
    free(s_dpp_wifi_config); s_dpp_wifi_config = NULL;

    return result;
}
