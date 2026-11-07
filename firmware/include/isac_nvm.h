/**
 * @file isac_nvm.h
 * @brief Power-fail-safe non-volatile storage for LoRaWAN session state (Rev E.2, audit B3)
 *        and per-unit provisioning block reader.
 *
 * Session store: two 2 KB flash pages (A/B), append-only log of 96-byte CRC-protected
 * records (payload + CRC written first, header MAGIC + sequence committed last). A new page
 * is erased only after the other page holds the newest record, so a power loss or STM32WLE5
 * 72-bit Flash ECC fault at any point leaves at least one valid record and self-heals.
 *
 * Provisioning block: one dedicated page written ONCE per unit by the production script
 * (tools/provision_unit.py). Erased flash (0xFF) means "not provisioned": firmware must not
 * join or transmit. No credential is ever compiled into the image.
 */
#ifndef ISAC_NVM_H
#define ISAC_NVM_H

#include <stdbool.h>
#include <stdint.h>

#define ISAC_FLASH_PAGE_SIZE      2048UL
#define ISAC_NVM_PROVISION_ADDR   0x0803E000UL   /* page 124 */
#define ISAC_NVM_PAGE_A_ADDR      0x0803E800UL   /* page 125 */
#define ISAC_NVM_PAGE_B_ADDR      0x0803F000UL   /* page 126 */
#define ISAC_NVM_RECORD_SIZE      96U            /* 12 x 8-byte doublewords (21 records / 2 KB page) */
#define ISAC_NVM_RECORDS_PER_PAGE (ISAC_FLASH_PAGE_SIZE / ISAC_NVM_RECORD_SIZE)

#define ISAC_NVM_REC_MAGIC        0x5345534EUL   /* "NSES" */
#define ISAC_PROV_MAGIC           0x56504F52UL   /* "ROPV" */
#define ISAC_PROV_VERSION         2U
#define ISAC_PROV_FLAG_CAL_DRY_VALID (1U << 0)
#define ISAC_PROV_FLAG_CAL_REF_VALID (1U << 1)
#define ISAC_NVM_MAX_STICKY_MAC_ANS  7U

/* HAL flash primitives (target: isac_hal_stm32wl.c, host: mock in test) */
bool ISAC_HAL_Flash_ErasePage(uint32_t page_addr);
bool ISAC_HAL_Flash_ProgramDoubleWord(uint32_t addr, uint32_t lo, uint32_t hi);
void ISAC_HAL_Flash_Read(uint32_t addr, void *dst, uint32_t len);
bool ISAC_HAL_Flash_ConsumeEccFault(void);

/** Session record payload (what is persisted across resets / brownouts -- HIGH-04 / HIGH-05). */
typedef struct {
    uint16_t dev_nonce;        /**< Last DevNonce used in a JoinRequest (persisted BEFORE TX) */
    uint8_t  joined;           /**< 1 = nwk_skey/app_skey/dev_addr valid                      */
    uint8_t  pending_ack;      /**< 1 = send ACK bit on next uplink (persisted on ConfirmedDL)*/
    uint32_t dev_addr;
    uint32_t fcnt_up;          /**< NEXT uplink counter to use (persisted BEFORE TX)          */
    uint32_t fcnt_down;        /**< NEXT expected downlink counter (persisted ON RX)          */
    uint16_t rx1_delay_ms;     /**< RECEIVE_DELAY1 [ms] (default 1000; 1000..15000)           */
    uint8_t  rx1_dr_offset;    /**< RX1DROffset (0..5)                                        */
    uint8_t  rx2_sf;           /**< RX2 spreading factor (default 12; 7..12)                  */
    uint8_t  num_channels;     /**< Active channel count (default 3; up to 8 with CFList)     */
    uint32_t channel_hz[5];    /**< Dynamic EU868 CFList / NewChannel frequencies ch[3..7]    */
    uint8_t  nwk_skey[16];
    uint8_t  app_skey[16];
    uint8_t  sticky_mac_ans_len; /**< LoRaWAN 1.0.3 §5 sticky MAC answers awaiting DL ack     */
    uint8_t  sticky_mac_ans[ISAC_NVM_MAX_STICKY_MAC_ANS];
} isac_nvm_session_t;

/** Per-unit provisioning block (one flash page, written by production tooling -- HIGH-02 / HIGH-06). */
typedef struct {
    uint32_t magic;            /**< ISAC_PROV_MAGIC                                           */
    uint8_t  version;          /**< ISAC_PROV_VERSION (2)                                     */
    uint8_t  use_otaa;         /**< 1 = OTAA, 0 = ABP                                         */
    uint16_t cal_flags;        /**< Bit 0: CAL_DRY_VALID, Bit 1: CAL_REF_VALID (2-pt cal)     */
    uint8_t  dev_eui[8];       /**< Big-endian; all-zero => use STM32 UID64                   */
    uint8_t  join_eui[8];
    uint8_t  app_key[16];
    uint32_t abp_dev_addr;
    uint8_t  abp_nwk_skey[16];
    uint8_t  abp_app_skey[16];
    uint16_t cal_dry_mv[3];    /**< Point-1 factory dry-air tare V_det(f1,f2,f3) [mV]         */
    int16_t  cal_ref_cdb;      /**< Point-2 factory Al2O3/load gain+intercept offset [0.01 dB]*/
    uint32_t crc32;            /**< CRC-32 (IEEE) over all preceding 84 bytes                 */
} isac_provision_t;

uint32_t ISAC_NVM_Crc32(const void *data, uint32_t len);

/** Read + validate the provisioning block. Returns false if erased / corrupt / wrong version. */
bool ISAC_NVM_ReadProvision(isac_provision_t *out);

/** Load newest valid session record. Returns false if none (fresh/erased/corrupt). */
bool ISAC_NVM_LoadSession(isac_nvm_session_t *out);

/** Append a session record (power-fail safe). Returns false on flash error. */
bool ISAC_NVM_SaveSession(const isac_nvm_session_t *in);

#endif /* ISAC_NVM_H */
