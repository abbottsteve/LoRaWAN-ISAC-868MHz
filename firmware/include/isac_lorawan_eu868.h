/**
 * @file isac_lorawan_eu868.h
 * @brief Self-Contained LoRaWAN 1.0.3 EU868 Class A MAC, FIPS-197 AES-128 & RFC 4493 CMAC Stack
 *
 * Implements the full standards-compliant LoRaWAN 1.0.3 Class A link layer on the
 * RAK3172LP-SiP internal SX1262 (`SUBGHZSPI`) transceiver:
 *   - FIPS-197 AES-128 forward cipher + RFC 4493 AES-CMAC 32-bit Message Integrity Code (MIC)
 *   - OTAA `JoinRequest` / `JoinAccept` + `NwkSKey` / `AppSKey` session key derivation + `CFList`
 *   - ABP pre-provisioned fallback / factory bring-up session support
 *   - Encrypted `FPort 10` Unconfirmed Data Up (`MHDR=0x40`, `23`-byte PHYPayload)
 *   - Mandatory EU868 3-channel hopping (`868.1 / 868.3 / 868.5 MHz` + up to 5 `CFList` channels)
 *   - Real millisecond-timed `TxDone` completion + Class A `RX1` (`+1 s`) and `RX2` (`+2 s`, `869.525 MHz`)
 */
#ifndef ISAC_LORAWAN_EU868_H
#define ISAC_LORAWAN_EU868_H

#include <stdbool.h>
#include <stdint.h>
#include "isac_nvm.h"

/* LoRaWAN 1.0.3 MAC Header Types & EU868 Regional Parameters (RP002-1.0.3) */
#define ISAC_LORAWAN_MHDR_JOIN_REQUEST      0x00U  /* MType = 000, Major = 00 */
#define ISAC_LORAWAN_MHDR_JOIN_ACCEPT       0x20U  /* MType = 001, Major = 00 */
#define ISAC_LORAWAN_MHDR_UNCONF_DATA_UP    0x40U  /* MType = 010, Major = 00 */
#define ISAC_LORAWAN_MHDR_UNCONF_DATA_DOWN  0x60U  /* MType = 011, Major = 00 */
#define ISAC_LORAWAN_MHDR_CONF_DATA_UP      0x80U  /* MType = 100, Major = 00 */
#define ISAC_LORAWAN_MHDR_CONF_DATA_DOWN    0xA0U  /* MType = 101, Major = 00 */

#define ISAC_LORAWAN_FCTRL_ADR              0x80U
#define ISAC_LORAWAN_FCTRL_ACK              0x20U

#define ISAC_EU868_CH0_HZ                   868100000UL
#define ISAC_EU868_CH1_HZ                   868300000UL
#define ISAC_EU868_CH2_HZ                   868500000UL
#define ISAC_EU868_RX2_HZ                   869525000UL

#define ISAC_EU868_MAX_CHANNELS             8U
#define ISAC_LORAWAN_RECEIVE_DELAY1_MS      1000UL
#define ISAC_LORAWAN_RECEIVE_DELAY2_MS      2000UL
#define ISAC_LORAWAN_JOIN_ACCEPT_DELAY1_MS  5000UL
#define ISAC_LORAWAN_JOIN_ACCEPT_DELAY2_MS  6000UL
#define ISAC_LORAWAN_RX_WINDOW_MS           120UL
#define ISAC_LORAWAN_RX_PRESTAGE_LEAD_MS    25UL
#define ISAC_LORAWAN_RX_EARLY_OPEN_MS       15UL

/* 10-byte FPort 10 payload -> 1(MHDR) + 7(FHDR) + 1(FPort) + 10(FRMPayload) + 4(MIC) = 23 bytes */
#define ISAC_LORAWAN_FPORT10_PHY_LEN        23U
#define ISAC_LORAWAN_JOIN_REQ_PHY_LEN       23U
#define ISAC_LORAWAN_MAX_PHY_LEN            64U
#define ISAC_LORAWAN_MAX_FOPTS              15U
#define ISAC_LORAWAN_MAX_FCNT_GAP           16384UL /* LoRaWAN 1.0.3 §4.3.1.5 MAX_FCNT_GAP */

typedef enum {
    ISAC_LORAWAN_TX_OK            = 0,
    ISAC_LORAWAN_ERR_PARAM        = 1,
    ISAC_LORAWAN_ERR_NOT_JOINED   = 2,
    ISAC_LORAWAN_ERR_TX_TIMEOUT   = 3,
    ISAC_LORAWAN_ERR_RADIO_BUSY   = 4
} isac_lorawan_status_t;

typedef struct isac_lorawan_ctx_s {
    /* OTAA Root Credentials (big-endian IEEE EUI-64 & 128-bit AppKey; reversed to LE on air) */
    uint8_t  dev_eui[8];
    uint8_t  join_eui[8];
    uint8_t  app_key[16];

    /* Active Session Context */
    uint32_t dev_addr;                          /**< 32-bit network address                    */
    uint8_t  nwk_skey[16];                      /**< Network session key (MIC + MAC commands)  */
    uint8_t  app_skey[16];                      /**< Application session key (FPort 1..223)    */
    uint32_t fcnt_up;                           /**< 32-bit monotonic uplink frame counter     */
    uint32_t fcnt_down;                         /**< 32-bit last valid downlink counter        */
    uint16_t dev_nonce;                         /**< Monotonic OTAA JoinRequest DevNonce       */

    /* EU868 Channel & Data-Rate Plan */
    uint32_t channel_hz[ISAC_EU868_MAX_CHANNELS];
    uint8_t  num_channels;
    uint8_t  next_ch_idx;
    uint8_t  tx_sf;                             /**< Spreading Factor 7..12 (default SF7 = DR5)*/
    uint8_t  rx1_dr_offset;                     /**< EU868 RX1DROffset 0..5                    */
    uint8_t  rx2_sf;                            /**< EU868 RX2 SF (default SF12 = DR0)         */
    uint16_t rx1_delay_ms;                      /**< RECEIVE_DELAY1 in ms (default 1000 ms)    */

    bool     joined;                            /**< True when OTAA JoinAccept or ABP active   */
    bool     otaa_enabled;                      /**< True to attempt OTAA Join before uplinks  */
    bool     pending_ack;                       /**< Set if last downlink requested ACK        */
    uint8_t  last_downlink_fport;
    uint8_t  last_downlink_len;
    uint8_t  last_downlink[32];

    /* Session persistence callback + one-shot & sticky MAC-command answers (LoRaWAN 1.0.3 §5) */
    void   (*persist_cb)(const struct isac_lorawan_ctx_s *ctx); /**< Called BEFORE any TX that consumes a nonce/counter */
    uint8_t  mac_ans[ISAC_LORAWAN_MAX_FOPTS];
    uint8_t  mac_ans_len;
    uint8_t  sticky_mac_ans[ISAC_NVM_MAX_STICKY_MAC_ANS]; /**< Sticky 0x05/0x08/0x09/0x0A until DL ack */
    uint8_t  sticky_mac_ans_len;
    uint8_t  battery_level;                     /**< DevStatusAns battery: 0=ext power,1..254,255=unknown */

    /* ETSI 1% post-Join off-time & LoRaWAN 1.0.3 §7 Join back-off state */
    uint32_t last_join_tx_end_ms;
    uint32_t last_join_toa_ms;
    uint16_t join_attempts;
    uint32_t next_join_allowed_ms;
} isac_lorawan_ctx_t;

/** Restore a persisted session (OTAA keys/addr/counters/DevNonce). Safe to call after Init*(). */
void ISAC_LoRaWAN_RestoreSession(isac_lorawan_ctx_t *ctx,
                                 uint16_t dev_nonce, bool joined, uint32_t dev_addr,
                                 uint32_t fcnt_up, uint32_t fcnt_down,
                                 const uint8_t nwk_skey[16], const uint8_t app_skey[16]);

/** Serialize / restore full LoRaWAN session including CFList channels, RX1 delay/offset, RX2 SF & ACK. */
void ISAC_LoRaWAN_SaveToNvmSession(const isac_lorawan_ctx_t *ctx, isac_nvm_session_t *out);
void ISAC_LoRaWAN_RestoreFromNvmSession(isac_lorawan_ctx_t *ctx, const isac_nvm_session_t *in);

/** Parse MAC commands (FOpts or decrypted FPort-0 payload) and queue answers for next uplink. */
void ISAC_LoRaWAN_ProcessMacCommands(isac_lorawan_ctx_t *ctx, const uint8_t *cmds, uint8_t len);

/* Cryptographic Primitives (Exposed for Host HIL NIST / RFC 4493 Verification) */
void     ISAC_AES128_EncryptBlock(const uint8_t key[16], const uint8_t in[16], uint8_t out[16]);
void     ISAC_AES128_CMAC(const uint8_t key[16], const uint8_t *msg, uint32_t len, uint8_t mac[16]);
void     ISAC_LoRaWAN_CryptPayload(const uint8_t key[16],
                                   uint32_t dev_addr,
                                   uint8_t dir,
                                   uint32_t fcnt,
                                   const uint8_t *in,
                                   uint8_t *out,
                                   uint8_t len);
uint32_t ISAC_LoRaWAN_ComputeDataMIC(const uint8_t nwk_skey[16],
                                     uint32_t dev_addr,
                                     uint8_t dir,
                                     uint32_t fcnt,
                                     const uint8_t *mhdr_and_mac,
                                     uint8_t len);

/* Frame Builders / Parsers & Time-on-Air */
uint32_t ISAC_LoRaWAN_CalcTimeOnAirMs(uint8_t sf, uint8_t phy_len);
uint32_t ISAC_LoRaWAN_NextJoinBackoffMs(uint16_t attempt_num, uint32_t join_toa_ms);
void     ISAC_LoRaWAN_TickBackoff(isac_lorawan_ctx_t *ctx, uint32_t now_ms);
uint8_t  ISAC_LoRaWAN_BuildUnconfirmedUplink(isac_lorawan_ctx_t *ctx,
                                             uint8_t fport,
                                             const uint8_t *app_payload,
                                             uint8_t app_len,
                                             uint8_t out_phy[ISAC_LORAWAN_MAX_PHY_LEN]);
uint8_t  ISAC_LoRaWAN_BuildJoinRequest(isac_lorawan_ctx_t *ctx,
                                       uint8_t out_phy[ISAC_LORAWAN_JOIN_REQ_PHY_LEN]);
bool     ISAC_LoRaWAN_ProcessJoinAccept(isac_lorawan_ctx_t *ctx,
                                        const uint8_t *rx_phy,
                                        uint8_t rx_len);
bool     ISAC_LoRaWAN_ProcessDataDownlink(isac_lorawan_ctx_t *ctx,
                                          const uint8_t *rx_phy,
                                          uint8_t rx_len);

/* Session Provisioning & Full Class A Radio Transaction (TX + RX1 + RX2 + Sleep) */
void                  ISAC_LoRaWAN_InitABP(isac_lorawan_ctx_t *ctx,
                                           uint32_t dev_addr,
                                           const uint8_t nwk_skey[16],
                                           const uint8_t app_skey[16]);
void                  ISAC_LoRaWAN_InitOTAA(isac_lorawan_ctx_t *ctx,
                                            const uint8_t dev_eui[8],
                                            const uint8_t join_eui[8],
                                            const uint8_t app_key[16]);
bool                  ISAC_LoRaWAN_JoinOTAA(isac_lorawan_ctx_t *ctx);
isac_lorawan_status_t ISAC_LoRaWAN_SendClassA(isac_lorawan_ctx_t *ctx,
                                              uint8_t fport,
                                              const uint8_t *payload,
                                              uint8_t len,
                                              uint32_t *out_airtime_ms);

#endif /* ISAC_LORAWAN_EU868_H */
