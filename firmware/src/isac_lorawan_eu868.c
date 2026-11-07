/**
 * @file isac_lorawan_eu868.c
 * @brief LoRaWAN 1.0.3 EU868 Class A MAC, FIPS-197 AES-128, RFC 4493 CMAC & SX1262 PHY Driver
 */
#include "isac_lorawan_eu868.h"
#include "isac_hal.h"
#include "isac_sensing.h"

#include <stddef.h>

/* =========================================================================
 * 1. Constant-Table FIPS-197 AES-128 Forward Block Cipher
 * ========================================================================= */
static const uint8_t k_aes_sbox[256] = {
    0x63U,0x7CU,0x77U,0x7BU,0xF2U,0x6BU,0x6FU,0xC5U,0x30U,0x01U,0x67U,0x2BU,0xFEU,0xD7U,0xABU,0x76U,
    0xCAU,0x82U,0xC9U,0x7DU,0xFAU,0x59U,0x47U,0xF0U,0xADU,0xD4U,0xA2U,0xAFU,0x9CU,0xA4U,0x72U,0xC0U,
    0xB7U,0xFDU,0x93U,0x26U,0x36U,0x3FU,0xF7U,0xCCU,0x34U,0xA5U,0xE5U,0xF1U,0x71U,0xD8U,0x31U,0x15U,
    0x04U,0xC7U,0x23U,0xC3U,0x18U,0x96U,0x05U,0x9AU,0x07U,0x12U,0x80U,0xE2U,0xEBU,0x27U,0xB2U,0x75U,
    0x09U,0x83U,0x2CU,0x1AU,0x1BU,0x6EU,0x5AU,0xA0U,0x52U,0x3BU,0xD6U,0xB3U,0x29U,0xE3U,0x2FU,0x84U,
    0x53U,0xD1U,0x00U,0xEDU,0x20U,0xFCU,0xB1U,0x5BU,0x6AU,0xCBU,0xBEU,0x39U,0x4AU,0x4CU,0x58U,0xCFU,
    0xD0U,0xEFU,0xAAU,0xFBU,0x43U,0x4DU,0x33U,0x85U,0x45U,0xF9U,0x02U,0x7FU,0x50U,0x3CU,0x9FU,0xA8U,
    0x51U,0xA3U,0x40U,0x8FU,0x92U,0x9DU,0x38U,0xF5U,0xBCU,0xB6U,0xDAU,0x21U,0x10U,0xFFU,0xF3U,0xD2U,
    0xCDU,0x0CU,0x13U,0xECU,0x5FU,0x97U,0x44U,0x17U,0xC4U,0xA7U,0x7EU,0x3DU,0x64U,0x5DU,0x19U,0x73U,
    0x60U,0x81U,0x4FU,0xDCU,0x22U,0x2AU,0x90U,0x88U,0x46U,0xEEU,0xB8U,0x14U,0xDEU,0x5EU,0x0BU,0xDBU,
    0xE0U,0x32U,0x3AU,0x0AU,0x49U,0x06U,0x24U,0x5CU,0xC2U,0xD3U,0xACU,0x62U,0x91U,0x95U,0xE4U,0x79U,
    0xE7U,0xC8U,0x37U,0x6DU,0x8DU,0xD5U,0x4EU,0xA9U,0x6CU,0x56U,0xF4U,0xEAU,0x65U,0x7AU,0xAEU,0x08U,
    0xBAU,0x78U,0x25U,0x2EU,0x1CU,0xA6U,0xB4U,0xC6U,0xE8U,0xDDU,0x74U,0x1FU,0x4BU,0xBDU,0x8BU,0x8AU,
    0x70U,0x3EU,0xB5U,0x66U,0x48U,0x03U,0xF6U,0x0EU,0x61U,0x35U,0x57U,0xB9U,0x86U,0xC1U,0x1DU,0x9EU,
    0xE1U,0xF8U,0x98U,0x11U,0x69U,0xD9U,0x8EU,0x94U,0x9BU,0x1EU,0x87U,0xE9U,0xCEU,0x55U,0x28U,0xDFU,
    0x8CU,0xA1U,0x89U,0x0DU,0xBFU,0xE6U,0x42U,0x68U,0x41U,0x99U,0x2DU,0x0FU,0xB0U,0x54U,0xBBU,0x16U
};

static const uint8_t k_aes_rcon[10] = {
    0x01U, 0x02U, 0x04U, 0x08U, 0x10U, 0x20U, 0x40U, 0x80U, 0x1BU, 0x36U
};

static uint8_t gf_xtime(uint8_t x)
{
    return (uint8_t)((x << 1U) ^ (((x & 0x80U) != 0U) ? 0x1BU : 0x00U));
}

static void aes128_expand_key(const uint8_t key[16], uint8_t rk[176])
{
    uint32_t i;
    uint8_t  tmp[4];

    for (i = 0U; i < 16U; ++i) {
        rk[i] = key[i];
    }
    for (i = 4U; i < 44U; ++i) {
        tmp[0] = rk[4U * (i - 1U) + 0U];
        tmp[1] = rk[4U * (i - 1U) + 1U];
        tmp[2] = rk[4U * (i - 1U) + 2U];
        tmp[3] = rk[4U * (i - 1U) + 3U];
        if ((i & 3U) == 0U) {
            const uint8_t t = tmp[0];
            tmp[0] = (uint8_t)(k_aes_sbox[tmp[1]] ^ k_aes_rcon[(i >> 2U) - 1U]);
            tmp[1] = k_aes_sbox[tmp[2]];
            tmp[2] = k_aes_sbox[tmp[3]];
            tmp[3] = k_aes_sbox[t];
        }
        rk[4U * i + 0U] = (uint8_t)(rk[4U * (i - 4U) + 0U] ^ tmp[0]);
        rk[4U * i + 1U] = (uint8_t)(rk[4U * (i - 4U) + 1U] ^ tmp[1]);
        rk[4U * i + 2U] = (uint8_t)(rk[4U * (i - 4U) + 2U] ^ tmp[2]);
        rk[4U * i + 3U] = (uint8_t)(rk[4U * (i - 4U) + 3U] ^ tmp[3]);
    }
}

void ISAC_AES128_EncryptBlock(const uint8_t key[16], const uint8_t in[16], uint8_t out[16])
{
    uint8_t  rk[176];
    uint8_t  s[16];
    uint32_t r, i;

    aes128_expand_key(key, rk);
    for (i = 0U; i < 16U; ++i) {
        s[i] = (uint8_t)(in[i] ^ rk[i]);
    }

    for (r = 1U; r <= 10U; ++r) {
        uint8_t t;
        /* SubBytes */
        for (i = 0U; i < 16U; ++i) {
            s[i] = k_aes_sbox[s[i]];
        }
        /* ShiftRows (column-major state s[4*col + row]) */
        t = s[1];  s[1]  = s[5];  s[5]  = s[9];  s[9]  = s[13]; s[13] = t;
        t = s[2];  s[2]  = s[10]; s[10] = t;
        t = s[6];  s[6]  = s[14]; s[14] = t;
        t = s[15]; s[15] = s[11]; s[11] = s[7];  s[7]  = s[3];  s[3]  = t;

        /* MixColumns (omitted in final round 10) */
        if (r < 10U) {
            for (i = 0U; i < 16U; i += 4U) {
                const uint8_t a0 = s[i + 0U];
                const uint8_t a1 = s[i + 1U];
                const uint8_t a2 = s[i + 2U];
                const uint8_t a3 = s[i + 3U];
                const uint8_t xr = (uint8_t)(a0 ^ a1 ^ a2 ^ a3);
                s[i + 0U] ^= (uint8_t)(xr ^ gf_xtime((uint8_t)(a0 ^ a1)));
                s[i + 1U] ^= (uint8_t)(xr ^ gf_xtime((uint8_t)(a1 ^ a2)));
                s[i + 2U] ^= (uint8_t)(xr ^ gf_xtime((uint8_t)(a2 ^ a3)));
                s[i + 3U] ^= (uint8_t)(xr ^ gf_xtime((uint8_t)(a3 ^ a0)));
            }
        }

        /* AddRoundKey */
        for (i = 0U; i < 16U; ++i) {
            s[i] ^= rk[16U * r + i];
        }
    }

    for (i = 0U; i < 16U; ++i) {
        out[i] = s[i];
    }
}

/* =========================================================================
 * 2. RFC 4493 AES-128 CMAC & LoRaWAN 1.0.3 Payload / MIC Primitives
 * ========================================================================= */
static void cmac_leftshift_subkey(const uint8_t in[16], uint8_t out[16])
{
    uint8_t carry = 0U;
    int     i;
    for (i = 15; i >= 0; --i) {
        const uint8_t b = in[i];
        out[i] = (uint8_t)((b << 1U) | carry);
        carry  = (uint8_t)((b >> 7U) & 1U);
    }
    if ((in[0] & 0x80U) != 0U) {
        out[15] ^= 0x87U;
    }
}

void ISAC_AES128_CMAC(const uint8_t key[16], const uint8_t *msg, uint32_t len, uint8_t mac[16])
{
    uint8_t  zero[16] = { 0U };
    uint8_t  L[16], K1[16], K2[16], X[16], Y[16], M_last[16];
    uint32_t n_blocks;
    bool     complete;
    uint32_t b, i;

    ISAC_AES128_EncryptBlock(key, zero, L);
    cmac_leftshift_subkey(L, K1);
    cmac_leftshift_subkey(K1, K2);

    n_blocks = (len + 15UL) / 16UL;
    if (n_blocks == 0UL) {
        n_blocks = 1UL;
        complete = false;
    } else {
        complete = ((len % 16UL) == 0UL);
    }

    if (complete) {
        const uint32_t off = (n_blocks - 1UL) * 16UL;
        for (i = 0U; i < 16U; ++i) {
            M_last[i] = (uint8_t)(msg[off + i] ^ K1[i]);
        }
    } else {
        const uint32_t off = (n_blocks - 1UL) * 16UL;
        const uint32_t rem = len - off;
        for (i = 0U; i < 16U; ++i) {
            uint8_t pad_b;
            if (i < rem) {
                pad_b = msg[off + i];
            } else if (i == rem) {
                pad_b = 0x80U;
            } else {
                pad_b = 0x00U;
            }
            M_last[i] = (uint8_t)(pad_b ^ K2[i]);
        }
    }

    for (i = 0U; i < 16U; ++i) {
        X[i] = 0U;
    }
    for (b = 0U; b < (n_blocks - 1UL); ++b) {
        for (i = 0U; i < 16U; ++i) {
            Y[i] = (uint8_t)(X[i] ^ msg[b * 16UL + i]);
        }
        ISAC_AES128_EncryptBlock(key, Y, X);
    }
    for (i = 0U; i < 16U; ++i) {
        Y[i] = (uint8_t)(X[i] ^ M_last[i]);
    }
    ISAC_AES128_EncryptBlock(key, Y, mac);
}

void ISAC_LoRaWAN_CryptPayload(const uint8_t key[16],
                               uint32_t dev_addr,
                               uint8_t dir,
                               uint32_t fcnt,
                               const uint8_t *in,
                               uint8_t *out,
                               uint8_t len)
{
    uint8_t a_blk[16] = { 0U };
    uint8_t s_blk[16];
    uint8_t ctr = 1U;
    uint8_t pos = 0U;

    a_blk[0]  = 0x01U;
    a_blk[5]  = dir & 0x01U;
    a_blk[6]  = (uint8_t)( dev_addr         & 0xFFU);
    a_blk[7]  = (uint8_t)((dev_addr >>  8U) & 0xFFU);
    a_blk[8]  = (uint8_t)((dev_addr >> 16U) & 0xFFU);
    a_blk[9]  = (uint8_t)((dev_addr >> 24U) & 0xFFU);
    a_blk[10] = (uint8_t)( fcnt             & 0xFFU);
    a_blk[11] = (uint8_t)((fcnt     >>  8U) & 0xFFU);
    a_blk[12] = (uint8_t)((fcnt     >> 16U) & 0xFFU);
    a_blk[13] = (uint8_t)((fcnt     >> 24U) & 0xFFU);

    while (pos < len) {
        uint8_t i;
        a_blk[15] = ctr++;
        ISAC_AES128_EncryptBlock(key, a_blk, s_blk);
        for (i = 0U; (i < 16U) && (pos < len); ++i, ++pos) {
            out[pos] = (uint8_t)(in[pos] ^ s_blk[i]);
        }
    }
}

uint32_t ISAC_LoRaWAN_ComputeDataMIC(const uint8_t nwk_skey[16],
                                     uint32_t dev_addr,
                                     uint8_t dir,
                                     uint32_t fcnt,
                                     const uint8_t *mhdr_and_mac,
                                     uint8_t len)
{
    uint8_t cmac_in[16U + ISAC_LORAWAN_MAX_PHY_LEN];
    uint8_t mac[16];
    uint8_t i;

    for (i = 0U; i < 16U; ++i) {
        cmac_in[i] = 0U;
    }
    cmac_in[0]  = 0x49U;
    cmac_in[5]  = dir & 0x01U;
    cmac_in[6]  = (uint8_t)( dev_addr         & 0xFFU);
    cmac_in[7]  = (uint8_t)((dev_addr >>  8U) & 0xFFU);
    cmac_in[8]  = (uint8_t)((dev_addr >> 16U) & 0xFFU);
    cmac_in[9]  = (uint8_t)((dev_addr >> 24U) & 0xFFU);
    cmac_in[10] = (uint8_t)( fcnt             & 0xFFU);
    cmac_in[11] = (uint8_t)((fcnt     >>  8U) & 0xFFU);
    cmac_in[12] = (uint8_t)((fcnt     >> 16U) & 0xFFU);
    cmac_in[13] = (uint8_t)((fcnt     >> 24U) & 0xFFU);
    cmac_in[15] = len;

    for (i = 0U; i < len; ++i) {
        cmac_in[16U + i] = mhdr_and_mac[i];
    }

    ISAC_AES128_CMAC(nwk_skey, cmac_in, (uint32_t)(16U + len), mac);
    return ((uint32_t)mac[0])
         | ((uint32_t)mac[1] <<  8U)
         | ((uint32_t)mac[2] << 16U)
         | ((uint32_t)mac[3] << 24U);
}

/* =========================================================================
 * 3. LoRaWAN 1.0.3 Frame Builders, OTAA Join & Exact LoRa Time-on-Air
 * ========================================================================= */
uint32_t ISAC_LoRaWAN_CalcTimeOnAirMs(uint8_t sf, uint8_t phy_len)
{
    /* Semtech SX1262 BW125, Explicit Header (H=0), CRC ON, CR=4/5, Preamble=8 symbols */
    uint32_t de;
    int32_t  num;
    int32_t  den;
    uint32_t payload_sym = 8UL;
    uint32_t sym_us;
    uint32_t total_us;

    if (sf < 7U) {
        sf = 7U;
    }
    if (sf > 12U) {
        sf = 12U;
    }
    de  = (sf >= 11U) ? 1UL : 0UL;
    num = (int32_t)(8UL * (uint32_t)phy_len) - (int32_t)(4UL * (uint32_t)sf) + 28 + 16;
    den = (int32_t)(4UL * ((uint32_t)sf - 2UL * de));
    if (num > 0) {
        const uint32_t blocks = ((uint32_t)num + (uint32_t)den - 1UL) / (uint32_t)den;
        payload_sym += blocks * 5UL; /* CR 4/5 -> 5 coded bits per 4 data bits */
    }

    /* T_sym = (2^sf) / 125,000 s = (2^sf * 8) us; Preamble = (8 + 4.25) = 12.25 symbols */
    sym_us   = (1UL << sf) * 8UL;
    total_us = ((4UL * payload_sym + 49UL) * sym_us) / 4UL;
    return (total_us + 999UL) / 1000UL;
}

static void init_default_eu868_channels(isac_lorawan_ctx_t *ctx)
{
    ctx->channel_hz[0]  = ISAC_EU868_CH0_HZ;
    ctx->channel_hz[1]  = ISAC_EU868_CH1_HZ;
    ctx->channel_hz[2]  = ISAC_EU868_CH2_HZ;
    ctx->num_channels   = 3U;
    ctx->next_ch_idx    = 0U;
    ctx->tx_sf          = 7U;
    ctx->rx1_dr_offset  = 0U;
    ctx->rx2_sf         = 12U;
    ctx->rx1_delay_ms   = (uint16_t)ISAC_LORAWAN_RECEIVE_DELAY1_MS;
    ctx->pending_ack    = false;
    ctx->persist_cb     = NULL;
    ctx->mac_ans_len    = 0U;
    ctx->sticky_mac_ans_len = 0U;
    ctx->battery_level  = 255U;
    ctx->last_downlink_fport  = 0U;
    ctx->last_downlink_len    = 0U;
    ctx->last_join_tx_end_ms  = 0UL;
    ctx->last_join_toa_ms     = 0UL;
    ctx->join_attempts        = 0U;
    ctx->next_join_allowed_ms = 0UL;
}

uint32_t ISAC_LoRaWAN_NextJoinBackoffMs(uint16_t attempt_num, uint32_t join_toa_ms)
{
    /* Enforce BOTH ETSI EN 300 220-1 <= 1% g1 sub-band off-time (100 * ToA)
     * AND sliding-window fencepost-exact LoRaWAN L2 1.0.3 §7 Retransmissions back-off across
     * ALL SF7..SF12 (including wet-boot SF12 JoinRequest = 1,483 ms):
     *   - Tier 1 (attempts 1..10, Hour 0..1, < 36 s / 1 h): >= 361 s spacing spans > 1.0 h
     *     (preventing Tier-2 bleed into Hour 1) and caps airtime at <= 14.83 s < 36.0 s.
     *   - Tier 2 (attempts 11..20, Hours 1..11, < 36 s / 10 h): >= 3,601 s spacing spans > 10.0 h
     *     and caps airtime at <= 14.83 s < 36.0 s.
     *   - Tier 3 (attempts > 20, Hours > 11, < 8.7 s / 24 h = 0.01%): max_tx_24h = floor(8699 / ToA)
     *     transmissions per 86,400,000 ms sliding window (e.g. 5 tx = 7.415 s < 8.700 s at SF12 ->
     *     T_min = 17,281,000 ms = 4.80 h; 1.00 h floor at SF7..SF9 = 1.49..5.14 s < 8.700 s). */
    const uint32_t eff_toa_ms  = (join_toa_ms > 0UL) ? join_toa_ms : 62UL;
    const uint32_t min_1pct_ms = ISAC_DutyCycle_MinBackoffMs(eff_toa_ms);

    if (attempt_num <= 10U) {
        return (min_1pct_ms > 361000UL) ? min_1pct_ms : 361000UL;
    }
    if (attempt_num <= 20U) {
        const uint32_t min_0p1pct_ms = min_1pct_ms * 10UL;
        return (min_0p1pct_ms > 3601000UL) ? min_0p1pct_ms : 3601000UL;
    }
    {
        const uint32_t max_tx_24h = (eff_toa_ms <= 8699UL) ? (8699UL / eff_toa_ms) : 1UL;
        const uint32_t min_24h_ms = (86400000UL / max_tx_24h) + 1000UL;
        return (min_24h_ms > 3601000UL) ? min_24h_ms : 3601000UL;
    }
}

void ISAC_LoRaWAN_InitABP(isac_lorawan_ctx_t *ctx,
                          uint32_t dev_addr,
                          const uint8_t nwk_skey[16],
                          const uint8_t app_skey[16])
{
    uint8_t i;
    if ((ctx == NULL) || (nwk_skey == NULL) || (app_skey == NULL)) {
        return;
    }
    for (i = 0U; i < 8U; ++i) {
        ctx->dev_eui[i]  = 0U;
        ctx->join_eui[i] = 0U;
    }
    for (i = 0U; i < 16U; ++i) {
        ctx->app_key[i]  = 0U;
        ctx->nwk_skey[i] = nwk_skey[i];
        ctx->app_skey[i] = app_skey[i];
    }
    ctx->dev_addr     = dev_addr;
    ctx->fcnt_up      = 0UL;
    ctx->fcnt_down    = 0UL;
    ctx->dev_nonce    = 0U;
    ctx->joined       = true;
    ctx->otaa_enabled = false;
    init_default_eu868_channels(ctx);
}

void ISAC_LoRaWAN_InitOTAA(isac_lorawan_ctx_t *ctx,
                           const uint8_t dev_eui[8],
                           const uint8_t join_eui[8],
                           const uint8_t app_key[16])
{
    uint8_t i;
    if ((ctx == NULL) || (dev_eui == NULL) || (join_eui == NULL) || (app_key == NULL)) {
        return;
    }
    for (i = 0U; i < 8U; ++i) {
        ctx->dev_eui[i]  = dev_eui[i];
        ctx->join_eui[i] = join_eui[i];
    }
    for (i = 0U; i < 16U; ++i) {
        ctx->app_key[i]  = app_key[i];
        ctx->nwk_skey[i] = 0U;
        ctx->app_skey[i] = 0U;
    }
    ctx->dev_addr     = 0UL;
    ctx->fcnt_up      = 0UL;
    ctx->fcnt_down    = 0UL;
    ctx->dev_nonce    = 0U;
    ctx->joined       = false;
    ctx->otaa_enabled = true;
    init_default_eu868_channels(ctx);
}

uint8_t ISAC_LoRaWAN_BuildJoinRequest(isac_lorawan_ctx_t *ctx,
                                      uint8_t out_phy[ISAC_LORAWAN_JOIN_REQ_PHY_LEN])
{
    uint8_t  mac[16];
    uint16_t dn;
    uint8_t  i;

    if ((ctx == NULL) || (out_phy == NULL)) {
        return 0U;
    }
    ctx->dev_nonce = (uint16_t)(ctx->dev_nonce + 1U);
    dn = ctx->dev_nonce;
    if (ctx->persist_cb != NULL) {
        ctx->persist_cb(ctx); /* DevNonce MUST be stored before it goes on air (never reused) */
    }

    out_phy[0] = ISAC_LORAWAN_MHDR_JOIN_REQUEST;
    /* JoinEUI & DevEUI transmitted Little-Endian on air per LoRaWAN 1.0.3 §6.2.4 */
    for (i = 0U; i < 8U; ++i) {
        out_phy[1U + i] = ctx->join_eui[7U - i];
        out_phy[9U + i] = ctx->dev_eui[7U - i];
    }
    out_phy[17] = (uint8_t)( dn        & 0xFFU);
    out_phy[18] = (uint8_t)((dn >> 8U) & 0xFFU);

    ISAC_AES128_CMAC(ctx->app_key, out_phy, 19UL, mac);
    out_phy[19] = mac[0];
    out_phy[20] = mac[1];
    out_phy[21] = mac[2];
    out_phy[22] = mac[3];
    return ISAC_LORAWAN_JOIN_REQ_PHY_LEN;
}

bool ISAC_LoRaWAN_ProcessJoinAccept(isac_lorawan_ctx_t *ctx,
                                    const uint8_t *rx_phy,
                                    uint8_t rx_len)
{
    uint8_t dec[33];
    uint8_t mac[16];
    uint8_t k_in[16] = { 0U };
    uint8_t rx2_dr;
    uint8_t i;

    if ((ctx == NULL) || (rx_phy == NULL) || ((rx_len != 17U) && (rx_len != 33U))) {
        return false;
    }
    if (rx_phy[0] != ISAC_LORAWAN_MHDR_JOIN_ACCEPT) {
        return false;
    }

    /* LoRaWAN 1.0.3 §6.2.5: JoinAccept is decrypted on the end-device using AES-128 ENCRYPT */
    dec[0] = rx_phy[0];
    ISAC_AES128_EncryptBlock(ctx->app_key, &rx_phy[1], &dec[1]);
    if (rx_len == 33U) {
        ISAC_AES128_EncryptBlock(ctx->app_key, &rx_phy[17], &dec[17]);
    }

    ISAC_AES128_CMAC(ctx->app_key, dec, (uint32_t)(rx_len - 4U), mac);
    if ((mac[0] != dec[rx_len - 4U]) ||
        (mac[1] != dec[rx_len - 3U]) ||
        (mac[2] != dec[rx_len - 2U]) ||
        (mac[3] != dec[rx_len - 1U])) {
        return false;
    }

    /* Derive NwkSKey (0x01) & AppSKey (0x02): AES128_enc(AppKey, type || AppNonce[3] || NetID[3] || DevNonce[2] || pad) */
    for (i = 0U; i < 6U; ++i) {
        k_in[1U + i] = dec[1U + i];
    }
    k_in[7] = (uint8_t)( ctx->dev_nonce        & 0xFFU);
    k_in[8] = (uint8_t)((ctx->dev_nonce >> 8U) & 0xFFU);

    k_in[0] = 0x01U;
    ISAC_AES128_EncryptBlock(ctx->app_key, k_in, ctx->nwk_skey);
    k_in[0] = 0x02U;
    ISAC_AES128_EncryptBlock(ctx->app_key, k_in, ctx->app_skey);

    ctx->dev_addr = ((uint32_t)dec[7])
                  | ((uint32_t)dec[8]  <<  8U)
                  | ((uint32_t)dec[9]  << 16U)
                  | ((uint32_t)dec[10] << 24U);
    ctx->rx1_dr_offset = (uint8_t)((dec[11] >> 4U) & 0x07U);
    rx2_dr             = (uint8_t)(dec[11] & 0x0FU);
    ctx->rx2_sf        = (rx2_dr <= 5U) ? (uint8_t)(12U - rx2_dr) : 12U;
    ctx->rx1_delay_ms  = (uint16_t)(((dec[12] & 0x0FU) == 0U ? 1U : (dec[12] & 0x0FU)) * 1000U);

    /* Optional 16-byte EU868 CFList (5 x 24-bit channel frequencies in 100 Hz steps + CFListType=0) */
    ctx->num_channels = 3U;
    if ((rx_len == 33U) && (dec[28] == 0x00U)) {
        for (i = 0U; i < 5U; ++i) {
            const uint32_t f_100hz = ((uint32_t)dec[13U + 3U * i])
                                   | ((uint32_t)dec[14U + 3U * i] << 8U)
                                   | ((uint32_t)dec[15U + 3U * i] << 16U);
            const uint32_t f_hz = f_100hz * 100UL;
            if ((f_hz >= 863000000UL) && (f_hz <= 870000000UL) &&
                (ctx->num_channels < ISAC_EU868_MAX_CHANNELS)) {
                ctx->channel_hz[ctx->num_channels++] = f_hz;
            }
        }
    }

    ctx->fcnt_up   = 0UL;
    ctx->fcnt_down = 0UL;
    ctx->joined    = true;
    ctx->mac_ans_len        = 0U;
    ctx->sticky_mac_ans_len = 0U;
    if (ctx->persist_cb != NULL) {
        ctx->persist_cb(ctx);
    }
    return true;
}

static uint8_t mac_ans_cid_len(uint8_t cid)
{
    switch (cid) {
    case 0x03U: return 2U; /* LinkADRAns       */
    case 0x04U: return 1U; /* DutyCycleAns     */
    case 0x05U: return 2U; /* RXParamSetupAns  */
    case 0x06U: return 3U; /* DevStatusAns     */
    case 0x07U: return 2U; /* NewChannelAns    */
    case 0x08U: return 1U; /* RXTimingSetupAns */
    case 0x09U: return 1U; /* TxParamSetupAns  */
    case 0x0AU: return 2U; /* DlChannelAns     */
    default:    return 0U;
    }
}

static bool fopts_contains_cid(const uint8_t *buf, uint8_t len, uint8_t target_cid)
{
    uint8_t k = 0U;
    while (k < len) {
        const uint8_t clen = mac_ans_cid_len(buf[k]);
        if ((clen == 0U) || ((uint32_t)k + clen > len)) {
            break;
        }
        if (buf[k] == target_cid) {
            return true;
        }
        k = (uint8_t)(k + clen);
    }
    return false;
}

uint8_t ISAC_LoRaWAN_BuildUnconfirmedUplink(isac_lorawan_ctx_t *ctx,
                                            uint8_t fport,
                                            const uint8_t *app_payload,
                                            uint8_t app_len,
                                            uint8_t out_phy[ISAC_LORAWAN_MAX_PHY_LEN])
{
    uint8_t        fopts[ISAC_LORAWAN_MAX_FOPTS];
    uint8_t        fopts_len = 0U;
    uint8_t        fctrl;
    uint32_t       mic;
    const uint8_t *enc_key;
    uint8_t        pos = 0U;
    uint8_t        k;

    if ((ctx == NULL) || (out_phy == NULL) || !ctx->joined || (fport == 0U)) {
        return 0U;
    }

    /* Assemble outgoing FOpts: queued MAC answers first, then any sticky 0x05/0x08/0x09/0x0A
     * answers not yet acknowledged by a valid network downlink (LoRaWAN 1.0.3 §5). */
    for (k = 0U; (k < ctx->mac_ans_len) && (fopts_len < ISAC_LORAWAN_MAX_FOPTS); ++k) {
        fopts[fopts_len++] = ctx->mac_ans[k];
    }
    k = 0U;
    while (k < ctx->sticky_mac_ans_len) {
        const uint8_t cid  = ctx->sticky_mac_ans[k];
        const uint8_t clen = mac_ans_cid_len(cid);
        if ((clen == 0U) || ((uint32_t)k + clen > ctx->sticky_mac_ans_len)) {
            break;
        }
        if (!fopts_contains_cid(fopts, fopts_len, cid) &&
            (((uint32_t)fopts_len + clen) <= ISAC_LORAWAN_MAX_FOPTS)) {
            uint8_t j;
            for (j = 0U; j < clen; ++j) {
                fopts[fopts_len++] = ctx->sticky_mac_ans[k + j];
            }
        }
        k = (uint8_t)(k + clen);
    }

    if (((uint32_t)app_len + 13UL + fopts_len) > ISAC_LORAWAN_MAX_PHY_LEN) {
        return 0U;
    }

    /* ADR is intentionally OFF (static data rate): LinkADRReq is then never solicited. */
    fctrl = 0U;
    if (ctx->pending_ack) {
        fctrl |= ISAC_LORAWAN_FCTRL_ACK;
        ctx->pending_ack = false;
    }

    out_phy[pos++] = ISAC_LORAWAN_MHDR_UNCONF_DATA_UP;
    out_phy[pos++] = (uint8_t)( ctx->dev_addr         & 0xFFU);
    out_phy[pos++] = (uint8_t)((ctx->dev_addr >>  8U) & 0xFFU);
    out_phy[pos++] = (uint8_t)((ctx->dev_addr >> 16U) & 0xFFU);
    out_phy[pos++] = (uint8_t)((ctx->dev_addr >> 24U) & 0xFFU);
    out_phy[pos++] = (uint8_t)(fctrl | (fopts_len & 0x0FU));
    out_phy[pos++] = (uint8_t)( ctx->fcnt_up          & 0xFFU);
    out_phy[pos++] = (uint8_t)((ctx->fcnt_up  >>  8U) & 0xFFU);
    for (k = 0U; k < fopts_len; ++k) {
        out_phy[pos++] = fopts[k];
    }
    ctx->mac_ans_len = 0U;
    out_phy[pos++] = fport;

    enc_key = ctx->app_skey;
    if ((app_payload != NULL) && (app_len > 0U)) {
        ISAC_LoRaWAN_CryptPayload(enc_key,
                                  ctx->dev_addr,
                                  0U, /* Dir = 0 (Uplink) */
                                  ctx->fcnt_up,
                                  app_payload,
                                  &out_phy[pos],
                                  app_len);
        pos = (uint8_t)(pos + app_len);
    }

    mic = ISAC_LoRaWAN_ComputeDataMIC(ctx->nwk_skey,
                                      ctx->dev_addr,
                                      0U,
                                      ctx->fcnt_up,
                                      out_phy,
                                      pos);
    out_phy[pos++] = (uint8_t)( mic         & 0xFFU);
    out_phy[pos++] = (uint8_t)((mic >>  8U) & 0xFFU);
    out_phy[pos++] = (uint8_t)((mic >> 16U) & 0xFFU);
    out_phy[pos++] = (uint8_t)((mic >> 24U) & 0xFFU);

    ctx->fcnt_up = ctx->fcnt_up + 1UL;
    if (ctx->persist_cb != NULL) {
        ctx->persist_cb(ctx); /* store NEXT counter before the frame is transmitted */
    }
    return pos;
}

void ISAC_LoRaWAN_RestoreSession(isac_lorawan_ctx_t *ctx,
                                 uint16_t dev_nonce, bool joined, uint32_t dev_addr,
                                 uint32_t fcnt_up, uint32_t fcnt_down,
                                 const uint8_t nwk_skey[16], const uint8_t app_skey[16])
{
    uint8_t i;
    if ((ctx == NULL) || (nwk_skey == NULL) || (app_skey == NULL)) {
        return;
    }
    ctx->dev_nonce = dev_nonce;
    if (joined) {
        ctx->dev_addr  = dev_addr;
        ctx->fcnt_up   = fcnt_up;
        ctx->fcnt_down = fcnt_down;
        for (i = 0U; i < 16U; ++i) {
            ctx->nwk_skey[i] = nwk_skey[i];
            ctx->app_skey[i] = app_skey[i];
        }
        ctx->joined = true;
    }
}

void ISAC_LoRaWAN_SaveToNvmSession(const isac_lorawan_ctx_t *ctx,
                                   isac_nvm_session_t *out_sess)
{
    uint8_t i;
    if ((ctx == NULL) || (out_sess == NULL)) {
        return;
    }
    for (i = 0U; i < (uint8_t)sizeof(*out_sess); ++i) {
        ((uint8_t *)out_sess)[i] = 0U;
    }
    out_sess->dev_nonce     = ctx->dev_nonce;
    out_sess->joined        = ctx->joined ? 1U : 0U;
    out_sess->pending_ack   = ctx->pending_ack ? 1U : 0U;
    out_sess->rx1_delay_ms  = ctx->rx1_delay_ms;
    out_sess->rx1_dr_offset = ctx->rx1_dr_offset;
    out_sess->rx2_sf        = ctx->rx2_sf;
    out_sess->num_channels  = ctx->num_channels;
    out_sess->dev_addr      = ctx->dev_addr;
    out_sess->fcnt_up       = ctx->fcnt_up;
    out_sess->fcnt_down     = ctx->fcnt_down;
    for (i = 0U; i < 16U; ++i) {
        out_sess->nwk_skey[i] = ctx->nwk_skey[i];
        out_sess->app_skey[i] = ctx->app_skey[i];
    }
    for (i = 0U; i < 5U; ++i) {
        const uint8_t ch_idx = (uint8_t)(3U + i);
        out_sess->channel_hz[i] = (ch_idx < ctx->num_channels) ? ctx->channel_hz[ch_idx] : 0UL;
    }
    out_sess->sticky_mac_ans_len = (ctx->sticky_mac_ans_len <= ISAC_NVM_MAX_STICKY_MAC_ANS)
                                 ? ctx->sticky_mac_ans_len
                                 : ISAC_NVM_MAX_STICKY_MAC_ANS;
    for (i = 0U; i < out_sess->sticky_mac_ans_len; ++i) {
        out_sess->sticky_mac_ans[i] = ctx->sticky_mac_ans[i];
    }
}

void ISAC_LoRaWAN_RestoreFromNvmSession(isac_lorawan_ctx_t *ctx,
                                        const isac_nvm_session_t *sess)
{
    uint8_t i;
    if ((ctx == NULL) || (sess == NULL)) {
        return;
    }
    ctx->dev_nonce = sess->dev_nonce;
    if (sess->joined != 0U) {
        ctx->dev_addr    = sess->dev_addr;
        ctx->fcnt_up     = sess->fcnt_up;
        ctx->fcnt_down   = sess->fcnt_down;
        ctx->pending_ack = (sess->pending_ack != 0U);
        for (i = 0U; i < 16U; ++i) {
            ctx->nwk_skey[i] = sess->nwk_skey[i];
            ctx->app_skey[i] = sess->app_skey[i];
        }
        ctx->rx1_delay_ms = ((sess->rx1_delay_ms >= 1000U) && (sess->rx1_delay_ms <= 15000U))
                          ? sess->rx1_delay_ms
                          : (uint16_t)ISAC_LORAWAN_RECEIVE_DELAY1_MS;
        ctx->rx1_dr_offset = (sess->rx1_dr_offset <= 5U) ? sess->rx1_dr_offset : 0U;
        ctx->rx2_sf        = ((sess->rx2_sf >= 7U) && (sess->rx2_sf <= 12U)) ? sess->rx2_sf : 12U;

        ctx->channel_hz[0] = ISAC_EU868_CH0_HZ;
        ctx->channel_hz[1] = ISAC_EU868_CH1_HZ;
        ctx->channel_hz[2] = ISAC_EU868_CH2_HZ;
        ctx->num_channels  = 3U;
        if ((sess->num_channels > 3U) && (sess->num_channels <= ISAC_EU868_MAX_CHANNELS)) {
            const uint8_t extra = (uint8_t)(sess->num_channels - 3U);
            for (i = 0U; i < extra; ++i) {
                const uint32_t f_hz = sess->channel_hz[i];
                if ((f_hz >= 863000000UL) && (f_hz <= 870000000UL) &&
                    (ctx->num_channels < ISAC_EU868_MAX_CHANNELS)) {
                    ctx->channel_hz[ctx->num_channels++] = f_hz;
                }
            }
        }
        ctx->sticky_mac_ans_len = (sess->sticky_mac_ans_len <= ISAC_NVM_MAX_STICKY_MAC_ANS)
                                ? sess->sticky_mac_ans_len
                                : 0U;
        for (i = 0U; i < ctx->sticky_mac_ans_len; ++i) {
            ctx->sticky_mac_ans[i] = sess->sticky_mac_ans[i];
        }
        ctx->joined = true;
    }
}

static void mac_push(isac_lorawan_ctx_t *ctx, const uint8_t *b, uint8_t n)
{
    uint8_t i;
    if (((uint32_t)ctx->mac_ans_len + n) > ISAC_LORAWAN_MAX_FOPTS) {
        return; /* answers that do not fit are dropped; the network will re-request */
    }
    for (i = 0U; i < n; ++i) {
        ctx->mac_ans[ctx->mac_ans_len++] = b[i];
    }
}

static void mac_push_sticky(isac_lorawan_ctx_t *ctx, const uint8_t *b, uint8_t n)
{
    uint8_t k = 0U;
    uint8_t j;

    mac_push(ctx, b, n);
    while (k < ctx->sticky_mac_ans_len) {
        const uint8_t clen = mac_ans_cid_len(ctx->sticky_mac_ans[k]);
        if ((clen == 0U) || ((uint32_t)k + clen > ctx->sticky_mac_ans_len)) {
            ctx->sticky_mac_ans_len = k;
            break;
        }
        if ((ctx->sticky_mac_ans[k] == b[0]) && (clen == n)) {
            for (j = 0U; j < n; ++j) {
                ctx->sticky_mac_ans[k + j] = b[j];
            }
            return;
        }
        k = (uint8_t)(k + clen);
    }
    if (((uint32_t)ctx->sticky_mac_ans_len + n) <= ISAC_NVM_MAX_STICKY_MAC_ANS) {
        for (j = 0U; j < n; ++j) {
            ctx->sticky_mac_ans[ctx->sticky_mac_ans_len++] = b[j];
        }
    }
}

/*
 * EU868 MAC command handling (LoRaWAN 1.0.3 §5):
 *   - Strict per-CID remaining-length bounds checks BEFORE mutating state or queueing answers.
 *   - Sticky MAC answers (0x05 RXParamSetupAns, 0x08 RXTimingSetupAns, 0x09 TxParamSetupAns,
 *     0x0A DlChannelAns) repeat on subsequent uplinks until a valid downlink advances fcnt_down.
 */
void ISAC_LoRaWAN_ProcessMacCommands(isac_lorawan_ctx_t *ctx, const uint8_t *cmds, uint8_t len)
{
    uint8_t i = 0U;
    uint8_t ans[3];

    if ((ctx == NULL) || (cmds == NULL)) {
        return;
    }
    while (i < len) {
        const uint8_t rem = (uint8_t)(len - i);
        switch (cmds[i]) {
        case 0x02U: /* LinkCheckAns (2 B) - informational */
            if (rem < 3U) { return; }
            i = (uint8_t)(i + 3U);
            break;
        case 0x03U: /* LinkADRReq (4 B) -> NACK all three status bits (power/DR/channel mask) */
            if (rem < 5U) { return; }
            ans[0] = 0x03U; ans[1] = 0x00U;
            mac_push(ctx, ans, 2U);
            i = (uint8_t)(i + 5U);
            break;
        case 0x04U: /* DutyCycleReq (1 B) -> we are far below any limit; acknowledge */
            if (rem < 2U) { return; }
            ans[0] = 0x04U;
            mac_push(ctx, ans, 1U);
            i = (uint8_t)(i + 2U);
            break;
        case 0x05U: /* RXParamSetupReq (4 B, LoRaWAN 1.0.3 §5.4): DLSettings + 24-bit Freq (100 Hz) */
            if (rem < 5U) { return; }
            {
                const uint8_t  dl_set  = cmds[i + 1U];
                const uint8_t  dr_off  = (uint8_t)((dl_set >> 4U) & 0x07U);
                const uint8_t  rx2_dr  = (uint8_t)(dl_set & 0x0FU);
                const uint32_t raw24   = ((uint32_t)cmds[i + 2U])
                                       | ((uint32_t)cmds[i + 3U] << 8U)
                                       | ((uint32_t)cmds[i + 4U] << 16U);
                const uint32_t freq_hz = raw24 * 100UL;
                uint8_t        status  = 0U;

                if (dr_off <= 5U)                    { status |= 0x04U; } /* RX1DROffsetACK */
                if (rx2_dr <= 5U)                    { status |= 0x02U; } /* RX2DataRateACK (DR0..DR5 = SF12..SF7) */
                if (freq_hz == ISAC_EU868_RX2_HZ)    { status |= 0x01U; } /* ChannelACK (869.525 MHz EU868 RX2) */
                if (status == 0x07U) {
                    ctx->rx1_dr_offset = dr_off;
                    ctx->rx2_sf        = (uint8_t)(12U - rx2_dr);
                }
                ans[0] = 0x05U; ans[1] = status;
                mac_push_sticky(ctx, ans, 2U);
            }
            i = (uint8_t)(i + 5U);
            break;
        case 0x06U: /* DevStatusReq (0 B) -> battery level, SNR margin unknown (0) */
            ans[0] = 0x06U; ans[1] = ctx->battery_level; ans[2] = 0x00U;
            mac_push(ctx, ans, 3U);
            i = (uint8_t)(i + 1U);
            break;
        case 0x07U: /* NewChannelReq (5 B) -> NACK (channel plan is fixed) */
            if (rem < 6U) { return; }
            ans[0] = 0x07U; ans[1] = 0x00U;
            mac_push(ctx, ans, 2U);
            i = (uint8_t)(i + 6U);
            break;
        case 0x08U: /* RXTimingSetupReq (1 B) -> apply RX1 delay (0 => 1 s) + sticky Ans */
            if (rem < 2U) { return; }
            {
                const uint8_t del = (uint8_t)(cmds[i + 1U] & 0x0FU);
                ctx->rx1_delay_ms = (uint16_t)((del == 0U) ? 1000U : (uint16_t)(del * 1000U));
            }
            ans[0] = 0x08U;
            mac_push_sticky(ctx, ans, 1U);
            i = (uint8_t)(i + 2U);
            break;
        case 0x09U: /* TxParamSetupReq (1 B) -> no dwell/EIRP limits in EU868; sticky Ans */
            if (rem < 2U) { return; }
            ans[0] = 0x09U;
            mac_push_sticky(ctx, ans, 1U);
            i = (uint8_t)(i + 2U);
            break;
        case 0x0AU: /* DlChannelReq (4 B) -> sticky NACK */
            if (rem < 5U) { return; }
            ans[0] = 0x0AU; ans[1] = 0x00U;
            mac_push_sticky(ctx, ans, 2U);
            i = (uint8_t)(i + 5U);
            break;
        default:   /* unknown CID: length unknown, stop parsing (spec §5) */
            return;
        }
    }
}

bool ISAC_LoRaWAN_ProcessDataDownlink(isac_lorawan_ctx_t *ctx, const uint8_t *rx, uint8_t rx_len)
{
    uint8_t  mhdr, fctrl, fopts_len, mac_hdr_end;
    uint32_t addr, mic_rx, mic_calc, fcnt32;
    uint16_t fcnt16;

    if ((ctx == NULL) || !ctx->joined || (rx == NULL) || (rx_len < 12U)) {
        return false;
    }
    mhdr = rx[0];
    if ((mhdr != ISAC_LORAWAN_MHDR_UNCONF_DATA_DOWN) &&
        (mhdr != ISAC_LORAWAN_MHDR_CONF_DATA_DOWN)) {
        return false;
    }
    addr = ((uint32_t)rx[1])
         | ((uint32_t)rx[2] <<  8U)
         | ((uint32_t)rx[3] << 16U)
         | ((uint32_t)rx[4] << 24U);
    if (addr != ctx->dev_addr) {
        return false;
    }
    fctrl       = rx[5];
    fopts_len   = (uint8_t)(fctrl & 0x0FU);
    mac_hdr_end = (uint8_t)(8U + fopts_len);
    if ((mac_hdr_end + 4U) > rx_len) {
        return false;
    }

    /* (LoRaWAN 1.0.3 §4.3.1.6) — Reject malformed frames carrying BOTH FOpts (FOptsLen > 0)
     * and FPort == 0 (or empty FPort 0 payload) BEFORE advancing fcnt_down or setting pending_ack */
    if ((mac_hdr_end + 4U) < rx_len) {
        const uint8_t fport_chk = rx[mac_hdr_end];
        const uint8_t plen_chk  = (uint8_t)(rx_len - 4U - (mac_hdr_end + 1U));
        if ((fport_chk == 0U) && ((fopts_len > 0U) || (plen_chk == 0U))) {
            return false;
        }
    }

    fcnt16 = (uint16_t)(((uint16_t)rx[6]) | ((uint16_t)rx[7] << 8U));
    fcnt32 = (ctx->fcnt_down & 0xFFFF0000UL) | (uint32_t)fcnt16;
    if (fcnt32 < ctx->fcnt_down) {
        fcnt32 += 0x10000UL;
    }
    /* (LoRaWAN 1.0.3 §4.3.1.5) — Reject downlinks exceeding MAX_FCNT_GAP (16384) */
    if ((fcnt32 - ctx->fcnt_down) >= ISAC_LORAWAN_MAX_FCNT_GAP) {
        return false;
    }

    mic_calc = ISAC_LoRaWAN_ComputeDataMIC(ctx->nwk_skey,
                                           ctx->dev_addr,
                                           1U, /* Dir = 1 (Downlink) */
                                           fcnt32,
                                           rx,
                                           (uint8_t)(rx_len - 4U));
    mic_rx = ((uint32_t)rx[rx_len - 4U])
           | ((uint32_t)rx[rx_len - 3U] <<  8U)
           | ((uint32_t)rx[rx_len - 2U] << 16U)
           | ((uint32_t)rx[rx_len - 1U] << 24U);
    if (mic_calc != mic_rx) {
        return false;
    }

    /* Valid authenticated downlink received: clear previous sticky MAC answers (LoRaWAN 1.0.3 §5) */
    ctx->sticky_mac_ans_len = 0U;
    ctx->fcnt_down          = fcnt32 + 1UL;
    if (mhdr == ISAC_LORAWAN_MHDR_CONF_DATA_DOWN) {
        ctx->pending_ack = true;
    }
    if (fopts_len > 0U) {
        ISAC_LoRaWAN_ProcessMacCommands(ctx, &rx[8], fopts_len);
    }

    if ((mac_hdr_end + 4U) < rx_len) {
        const uint8_t fport = rx[mac_hdr_end];
        uint8_t       plen  = (uint8_t)(rx_len - 4U - (mac_hdr_end + 1U));
        if (plen > sizeof(ctx->last_downlink)) {
            plen = (uint8_t)sizeof(ctx->last_downlink);
        }
        ctx->last_downlink_fport = fport;
        ctx->last_downlink_len   = plen;
        if (plen > 0U) {
            ISAC_LoRaWAN_CryptPayload((fport == 0U) ? ctx->nwk_skey : ctx->app_skey,
                                      ctx->dev_addr,
                                      1U,
                                      fcnt32,
                                      &rx[mac_hdr_end + 1U],
                                      ctx->last_downlink,
                                      plen);
            if (fport == 0U) {
                ISAC_LoRaWAN_ProcessMacCommands(ctx, ctx->last_downlink, plen);
            }
        }
    }
    /* Immediately persist updated fcnt_down, pending_ack, and MAC RX timing to NVM */
    if (ctx->persist_cb != NULL) {
        ctx->persist_cb(ctx);
    }
    return true;
}

/* =========================================================================
 * 4. SX1262 LoRa PHY Driver & Class A TX -> RX1 -> RX2 State Machine
 * ========================================================================= */
static bool sx1262_set_rf_freq(uint32_t freq_hz)
{
    const uint32_t pll = ISAC_FreqHz_To_PllStep(freq_hz);
    uint8_t buf[4];
    buf[0] = (uint8_t)((pll >> 24U) & 0xFFU);
    buf[1] = (uint8_t)((pll >> 16U) & 0xFFU);
    buf[2] = (uint8_t)((pll >>  8U) & 0xFFU);
    buf[3] = (uint8_t)( pll         & 0xFFU);
    return ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_SET_RF_FREQUENCY, buf, 4U);
}

static bool sx1262_config_lora_frame(uint32_t freq_hz,
                                     uint8_t sf,
                                     uint8_t len,
                                     bool is_downlink)
{
    const uint8_t pkt_lora   = ISAC_SUBGHZ_PKT_TYPE_LORA;
    const uint8_t sync_pub[2]= { ISAC_SUBGHZ_LORA_PUBLIC_SYNC_MSB, ISAC_SUBGHZ_LORA_PUBLIC_SYNC_LSB };
    const uint8_t base_addr[2]= { 0x00U, 0x80U }; /* TX @ 0x00, RX @ 0x80 */
    const uint8_t mod_prm[4] = {
        sf,
        0x04U,                        /* BW_125 (125 kHz) */
        0x01U,                        /* CR_4_5 */
        (sf >= 11U) ? 0x01U : 0x00U   /* LDRO mandatory for SF11/SF12 @ BW125 */
    };
    const uint8_t pkt_prm[6] = {
        0x00U, 0x08U,                 /* 8-symbol LoRaWAN preamble */
        0x00U,                        /* Explicit header */
        len,
        is_downlink ? 0x00U : 0x01U,  /* LoRaWAN: Uplink CRC ON, Downlink CRC OFF */
        is_downlink ? 0x01U : 0x00U   /* LoRaWAN: Uplink Standard IQ, Downlink Inverted IQ */
    };
    const uint16_t irq_mask  = (uint16_t)(ISAC_SUBGHZ_IRQ_TX_DONE |
                                          ISAC_SUBGHZ_IRQ_RX_DONE |
                                          ISAC_SUBGHZ_IRQ_CRC_ERR |
                                          ISAC_SUBGHZ_IRQ_TIMEOUT);
    const uint8_t dio_irq[8] = {
        (uint8_t)(irq_mask >> 8U), (uint8_t)(irq_mask & 0xFFU),
        (uint8_t)(irq_mask >> 8U), (uint8_t)(irq_mask & 0xFFU),
        0x00U, 0x00U, 0x00U, 0x00U
    };
    const uint8_t clr_all[2] = { 0xFFU, 0xFFU };
    uint8_t iq_pol = 0x0DU;
    uint8_t tx_mod = 0x00U;
    bool    ok;

    ok = ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_SET_PACKET_TYPE, &pkt_lora, 1U) &&
         ISAC_HAL_SubGhz_WriteReg(ISAC_SUBGHZ_REG_LORA_SYNC_MSB, sync_pub, 2U) &&
         ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_SET_BUFFER_BASE_ADDR, base_addr, 2U) &&
         sx1262_set_rf_freq(freq_hz) &&
         ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_SET_MODULATION_PARAMS, mod_prm, 4U) &&
         ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_SET_PACKET_PARAMS, pkt_prm, 6U);

    /* Apply Semtech SX1262 §15.4 Inverted-IQ (0x0736 bit 2) & §15.1 BW125 TxModulation (0x0889 bit 2) */
    if (ok && ISAC_HAL_SubGhz_ReadReg(ISAC_SUBGHZ_REG_IQ_POLARITY, &iq_pol, 1U)) {
        if (is_downlink) {
            iq_pol &= (uint8_t)~(1U << 2);
        } else {
            iq_pol |= (uint8_t)(1U << 2);
        }
        ok = ISAC_HAL_SubGhz_WriteReg(ISAC_SUBGHZ_REG_IQ_POLARITY, &iq_pol, 1U);
    } else {
        ok = false;
    }

    if (ok && !is_downlink) {
        if (ISAC_HAL_SubGhz_ReadReg(ISAC_SUBGHZ_REG_TX_MODULATION, &tx_mod, 1U)) {
            tx_mod |= (uint8_t)(1U << 2); /* BW125 != 500 kHz: set bit 2 */
            ok = ISAC_HAL_SubGhz_WriteReg(ISAC_SUBGHZ_REG_TX_MODULATION, &tx_mod, 1U);
        } else {
            ok = false;
        }
    }

    return ok &&
           ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_SET_DIO_IRQ_PARAMS, dio_irq, 8U) &&
           ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_CLEAR_IRQ_STATUS, clr_all, 2U);
}

static bool sx1262_get_irq_status(uint16_t *out_irq)
{
    uint8_t buf[2] = { 0U, 0U };
    if (!ISAC_HAL_SubGhz_ReadCmd(ISAC_SUBGHZ_CMD_GET_IRQ_STATUS, buf, 2U)) {
        if (out_irq != NULL) {
            *out_irq = 0U;
        }
        return false;
    }
    if (out_irq != NULL) {
        *out_irq = (uint16_t)(((uint16_t)buf[0] << 8U) | (uint16_t)buf[1]);
    }
    return true;
}

static isac_lorawan_status_t sx1262_tx_blocking(uint32_t freq_hz,
                                                uint8_t sf,
                                                const uint8_t *phy,
                                                uint8_t phy_len,
                                                uint32_t *out_toa_ms,
                                                uint32_t *out_tx_done_ms)
{
    const uint8_t  stdby_xosc = ISAC_SUBGHZ_STDBY_XOSC;
    const uint8_t  stdby_rc   = ISAC_SUBGHZ_STDBY_RC;
    const uint8_t  tx_prm[2]  = { (uint8_t)ISAC_LORAWAN_TX_DBM, ISAC_SUBGHZ_RAMP_40_US };
    const uint8_t  clr_all[2] = { 0xFFU, 0xFFU };
    const uint32_t toa_ms     = ISAC_LoRaWAN_CalcTimeOnAirMs(sf, phy_len);
    const uint32_t guard_ms   = toa_ms + 150UL;
    const uint32_t hw_ticks   = guard_ms * 64UL; /* 64 ticks/ms @ 15.625 us */
    const uint8_t  tx_tmo[3]  = {
        (uint8_t)((hw_ticks >> 16U) & 0xFFU),
        (uint8_t)((hw_ticks >>  8U) & 0xFFU),
        (uint8_t)( hw_ticks         & 0xFFU)
    };
    uint32_t t0_ms;
    isac_lorawan_status_t st = ISAC_LORAWAN_ERR_TX_TIMEOUT;

    if (out_toa_ms != NULL) {
        *out_toa_ms = toa_ms;
    }

    if (!ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_SET_STANDBY, &stdby_xosc, 1U) ||
        !ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_SET_TX_PARAMS, tx_prm, 2U) ||
        !sx1262_config_lora_frame(freq_hz, sf, phy_len, false) ||
        !ISAC_HAL_SubGhz_WriteBuffer(0x00U, phy, phy_len)) {
        ISAC_HAL_RFSwitch_SetMode(ISAC_RFSW_OFF);
        return ISAC_LORAWAN_ERR_RADIO_BUSY;
    }

    ISAC_HAL_RFSwitch_SetMode(ISAC_RFSW_TX_LP); /* PA0=0, PA1=1 -> Pin 37 RF_OUT */
    if (!ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_SET_TX, tx_tmo, 3U)) {
        ISAC_HAL_RFSwitch_SetMode(ISAC_RFSW_OFF);
        return ISAC_LORAWAN_ERR_RADIO_BUSY;
    }

    t0_ms = ISAC_HAL_GetTickMs();
    for (;;) {
        uint16_t irq = 0U;
        if (!sx1262_get_irq_status(&irq)) {
            st = ISAC_LORAWAN_ERR_RADIO_BUSY;
            break;
        }
        if ((irq & ISAC_SUBGHZ_IRQ_TX_DONE) != 0U) {
            /* Timestamp TX completion immediately upon IRQ_TX_DONE before SPI teardown */
            if (out_tx_done_ms != NULL) {
                *out_tx_done_ms = ISAC_HAL_GetTickMs();
            }
            st = ISAC_LORAWAN_TX_OK;
            break;
        }
        if (((irq & ISAC_SUBGHZ_IRQ_TIMEOUT) != 0U) ||
            ((ISAC_HAL_GetTickMs() - t0_ms) >= guard_ms)) {
            break;
        }
        ISAC_HAL_DelayMs(1UL);
    }

    ISAC_HAL_RFSwitch_SetMode(ISAC_RFSW_OFF);
    if (!ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_CLEAR_IRQ_STATUS, clr_all, 2U) ||
        !ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_SET_STANDBY, &stdby_rc, 1U)) {
        return ISAC_LORAWAN_ERR_RADIO_BUSY;
    }
    return st;
}

static bool sx1262_timed_rx_slot(uint32_t t_tx_end_ms,
                                 uint32_t slot_delay_ms,
                                 uint32_t freq_hz,
                                 uint8_t sf,
                                 uint32_t min_window_ms,
                                 uint8_t out_rx[ISAC_LORAWAN_MAX_PHY_LEN],
                                 uint8_t *out_rx_len)
{
    const uint8_t  stdby_xosc       = ISAC_SUBGHZ_STDBY_XOSC;
    const uint8_t  stdby_rc         = ISAC_SUBGHZ_STDBY_RC;
    const uint8_t  stop_on_preamble = 0x01U; /* Freeze RX timer on preamble detection */
    const uint8_t  clr_all[2]       = { 0xFFU, 0xFFU };
    const uint32_t sym_us           = (1UL << ((sf < 7U) ? 7U : ((sf > 12U) ? 12U : sf))) * 8UL;
    const uint32_t ten_sym_ms       = (10UL * sym_us + 999UL) / 1000UL;
    const uint32_t prestage_ms      = (slot_delay_ms > ISAC_LORAWAN_RX_PRESTAGE_LEAD_MS)
                                    ? (slot_delay_ms - ISAC_LORAWAN_RX_PRESTAGE_LEAD_MS)
                                    : 0UL;
    const uint32_t open_ms          = (slot_delay_ms > ISAC_LORAWAN_RX_EARLY_OPEN_MS)
                                    ? (slot_delay_ms - ISAC_LORAWAN_RX_EARLY_OPEN_MS)
                                    : 0UL;
    uint32_t       search_ms        = (ten_sym_ms > min_window_ms) ? ten_sym_ms : min_window_ms;
    uint32_t       hw_ticks;
    uint32_t       guard_ms;
    uint8_t        rx_tmo[3];
    uint32_t       t0_ms;
    uint8_t        rx_len   = 0U;
    bool           radio_ok = true;

    if (out_rx_len != NULL) {
        *out_rx_len = 0U;
    }

    /* Expand preamble search window by early-open margin (+/-20 ms crystal tolerance) */
    search_ms += ISAC_LORAWAN_RX_EARLY_OPEN_MS;
    hw_ticks   = search_ms * 64UL;
    rx_tmo[0]  = (uint8_t)((hw_ticks >> 16U) & 0xFFU);
    rx_tmo[1]  = (uint8_t)((hw_ticks >>  8U) & 0xFFU);
    rx_tmo[2]  = (uint8_t)( hw_ticks         & 0xFFU);

    /* Software guard accommodates full max-length LoRaWAN frame after preamble lock */
    guard_ms   = search_ms
               + ISAC_LoRaWAN_CalcTimeOnAirMs(sf, ISAC_LORAWAN_MAX_PHY_LEN)
               + 250UL;

    /* 1 ms polling to pre-stage XOSC + LoRa registers 25 ms before nominal slot */
    while ((ISAC_HAL_GetTickMs() - t_tx_end_ms) < prestage_ms) {
        ISAC_HAL_DelayMs(1UL);
    }

    if (!ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_SET_STANDBY, &stdby_xosc, 1U) ||
        !ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_SET_STOP_RX_TIMER_ON_PREAMBLE, &stop_on_preamble, 1U) ||
        !sx1262_config_lora_frame(freq_hz, sf, ISAC_LORAWAN_MAX_PHY_LEN, true)) {
        ISAC_HAL_RFSwitch_SetMode(ISAC_RFSW_OFF);
        return false;
    }

    /* Fine 1 ms wait and open SET_RX 15 ms early to guarantee RX1/RX2 preamble capture */
    while ((ISAC_HAL_GetTickMs() - t_tx_end_ms) < open_ms) {
        ISAC_HAL_DelayMs(1UL);
    }

    ISAC_HAL_RFSwitch_SetMode(ISAC_RFSW_RX); /* PA0=1, PA1=0 -> Pin 37 RF_OUT to LNA */
    if (!ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_SET_RX, rx_tmo, 3U)) {
        ISAC_HAL_RFSwitch_SetMode(ISAC_RFSW_OFF);
        return false;
    }

    t0_ms = ISAC_HAL_GetTickMs();
    for (;;) {
        uint16_t irq = 0U;
        if (!sx1262_get_irq_status(&irq)) {
            radio_ok = false;
            break;
        }
        if ((irq & ISAC_SUBGHZ_IRQ_RX_DONE) != 0U) {
            if ((irq & ISAC_SUBGHZ_IRQ_CRC_ERR) == 0U) {
                uint8_t rx_stat[2] = { 0U, 0U };
                if (!ISAC_HAL_SubGhz_ReadCmd(ISAC_SUBGHZ_CMD_GET_RX_BUFFER_STATUS, rx_stat, 2U)) {
                    radio_ok = false;
                    break;
                }
                rx_len = rx_stat[0];
                if (rx_len > ISAC_LORAWAN_MAX_PHY_LEN) {
                    rx_len = ISAC_LORAWAN_MAX_PHY_LEN;
                }
                if ((rx_len > 0U) &&
                    !ISAC_HAL_SubGhz_ReadBuffer(rx_stat[1], out_rx, rx_len)) {
                    radio_ok = false;
                    rx_len   = 0U;
                    break;
                }
            }
            break;
        }
        if (((irq & ISAC_SUBGHZ_IRQ_TIMEOUT) != 0U) ||
            ((ISAC_HAL_GetTickMs() - t0_ms) >= guard_ms)) {
            break;
        }
        ISAC_HAL_DelayMs(1UL);
    }

    ISAC_HAL_RFSwitch_SetMode(ISAC_RFSW_OFF);
    radio_ok = ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_CLEAR_IRQ_STATUS, clr_all, 2U) && radio_ok;
    radio_ok = ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_SET_STANDBY, &stdby_rc, 1U) && radio_ok;
    if (out_rx_len != NULL) {
        *out_rx_len = rx_len;
    }
    return radio_ok;
}

static uint32_t select_next_eu868_channel(isac_lorawan_ctx_t *ctx)
{
    uint32_t f_hz;
    if (ctx->num_channels == 0U) {
        init_default_eu868_channels(ctx);
    }
    if (ctx->next_ch_idx >= ctx->num_channels) {
        ctx->next_ch_idx = 0U;
    }
    f_hz = ctx->channel_hz[ctx->next_ch_idx];
    ctx->next_ch_idx = (uint8_t)((ctx->next_ch_idx + 1U) % ctx->num_channels);
    return f_hz;
}

void ISAC_LoRaWAN_TickBackoff(isac_lorawan_ctx_t *ctx, uint32_t now_ms)
{
    if (ctx == NULL) {
        return;
    }
    if ((ctx->join_attempts == 0U) ||
        ((int32_t)(now_ms - ctx->next_join_allowed_ms) >= 0)) {
        ctx->next_join_allowed_ms = now_ms;
    }
}

bool ISAC_LoRaWAN_JoinOTAA(isac_lorawan_ctx_t *ctx)
{
    uint8_t  phy_tx[ISAC_LORAWAN_JOIN_REQ_PHY_LEN];
    uint8_t  phy_rx[ISAC_LORAWAN_MAX_PHY_LEN];
    uint8_t  warm_sleep  = ISAC_SUBGHZ_SLEEP_WARM_START;
    uint32_t now_ms;
    uint32_t tx_freq_hz;
    uint32_t join_toa_ms = 0UL;
    uint32_t t_tx_end    = 0UL;
    uint8_t  rx_len;
    bool     joined = false;

    if ((ctx == NULL) || !ctx->otaa_enabled) {
        return false;
    }
    now_ms = ISAC_HAL_GetTickMs();
    /* Enforce LoRaWAN 1.0.3 §7 & ETSI 1% back-off and latch once expired */
    if (ctx->join_attempts > 0U) {
        if ((int32_t)(now_ms - ctx->next_join_allowed_ms) < 0) {
            return false;
        }
        ctx->next_join_allowed_ms = now_ms;
    }
    if (ISAC_LoRaWAN_BuildJoinRequest(ctx, phy_tx) != ISAC_LORAWAN_JOIN_REQ_PHY_LEN) {
        return false;
    }

    /* JoinRequest hops across the 3 mandatory EU868 join channels (868.1 / 868.3 / 868.5 MHz) */
    tx_freq_hz = ctx->channel_hz[ctx->dev_nonce % 3U];
    if (sx1262_tx_blocking(tx_freq_hz, ctx->tx_sf, phy_tx, ISAC_LORAWAN_JOIN_REQ_PHY_LEN,
                           &join_toa_ms, &t_tx_end) != ISAC_LORAWAN_TX_OK) {
        (void)ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_SET_SLEEP, &warm_sleep, 1U);
        return false;
    }
    ctx->last_join_tx_end_ms = t_tx_end;
    ctx->last_join_toa_ms    = join_toa_ms;
    if (ctx->join_attempts < 65535U) {
        ctx->join_attempts = (uint16_t)(ctx->join_attempts + 1U);
    }

    /* JOIN_ACCEPT_DELAY1 (5,000 ms) on same channel & SF */
    if (!sx1262_timed_rx_slot(t_tx_end, ISAC_LORAWAN_JOIN_ACCEPT_DELAY1_MS,
                              tx_freq_hz, ctx->tx_sf, ISAC_LORAWAN_RX_WINDOW_MS,
                              phy_rx, &rx_len)) {
        ctx->next_join_allowed_ms = t_tx_end + ISAC_LoRaWAN_NextJoinBackoffMs(ctx->join_attempts, join_toa_ms);
        (void)ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_SET_SLEEP, &warm_sleep, 1U);
        return false;
    }
    if ((rx_len > 0U) && ISAC_LoRaWAN_ProcessJoinAccept(ctx, phy_rx, rx_len)) {
        joined = true;
    } else {
        /* JOIN_ACCEPT_DELAY2 (6,000 ms) on 869.525 MHz RX2 (SF12BW125 up to 1,810 ms JoinAccept) */
        if (!sx1262_timed_rx_slot(t_tx_end, ISAC_LORAWAN_JOIN_ACCEPT_DELAY2_MS,
                                  ISAC_EU868_RX2_HZ, ctx->rx2_sf, ISAC_LORAWAN_RX_WINDOW_MS,
                                  phy_rx, &rx_len)) {
            ctx->next_join_allowed_ms = t_tx_end + ISAC_LoRaWAN_NextJoinBackoffMs(ctx->join_attempts, join_toa_ms);
            (void)ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_SET_SLEEP, &warm_sleep, 1U);
            return false;
        }
        if ((rx_len > 0U) && ISAC_LoRaWAN_ProcessJoinAccept(ctx, phy_rx, rx_len)) {
            joined = true;
        }
    }

    if (joined) {
        ctx->join_attempts        = 0U;
        ctx->next_join_allowed_ms = t_tx_end + ISAC_DutyCycle_MinBackoffMs(join_toa_ms);
    } else {
        ctx->next_join_allowed_ms = t_tx_end + ISAC_LoRaWAN_NextJoinBackoffMs(ctx->join_attempts, join_toa_ms);
    }

    if (!ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_SET_SLEEP, &warm_sleep, 1U)) {
        return false;
    }
    return joined;
}

isac_lorawan_status_t ISAC_LoRaWAN_SendClassA(isac_lorawan_ctx_t *ctx,
                                              uint8_t fport,
                                              const uint8_t *payload,
                                              uint8_t len,
                                              uint32_t *out_airtime_ms)
{
    uint8_t  phy_tx[ISAC_LORAWAN_MAX_PHY_LEN];
    uint8_t  phy_rx[ISAC_LORAWAN_MAX_PHY_LEN];
    uint8_t  warm_sleep = ISAC_SUBGHZ_SLEEP_WARM_START;
    uint8_t  phy_len;
    uint8_t  rx1_sf;
    uint8_t  rx_len = 0U;
    uint32_t tx_freq_hz;
    uint32_t t_tx_end = 0UL;
    isac_lorawan_status_t tx_st;

    if ((ctx == NULL) || (payload == NULL) || (fport == 0U)) {
        return ISAC_LORAWAN_ERR_PARAM;
    }
    if (!ctx->joined) {
        if (!ctx->otaa_enabled) {
            return ISAC_LORAWAN_ERR_NOT_JOINED;
        }
        if (!ISAC_LoRaWAN_JoinOTAA(ctx)) {
            return ISAC_LORAWAN_ERR_NOT_JOINED;
        }
    }

    /* Guarantee ETSI EN 300 220-1 <= 1% g1 sub-band off-time (100 * T_JoinReq)
     * before the first post-Join DataUp (vital when JoinAccept arrived on RX1 @ +5.06 s < 6.20 s) */
    if (ctx->last_join_toa_ms > 0UL) {
        const uint32_t min_ul_ms = ctx->last_join_tx_end_ms
                                 + ISAC_DutyCycle_MinBackoffMs(ctx->last_join_toa_ms);
        uint32_t wdt_ticks = 0UL;
        while ((int32_t)(ISAC_HAL_GetTickMs() - min_ul_ms) < 0) {
            ISAC_HAL_DelayMs(1UL);
            if ((++wdt_ticks & 0xFFUL) == 0UL) {
                ISAC_HAL_Watchdog_Kick();
            }
        }
        ctx->last_join_toa_ms = 0UL;
    }

    phy_len = ISAC_LoRaWAN_BuildUnconfirmedUplink(ctx, fport, payload, len, phy_tx);
    if (phy_len == 0U) {
        return ISAC_LORAWAN_ERR_PARAM;
    }

    tx_freq_hz = select_next_eu868_channel(ctx);
    tx_st      = sx1262_tx_blocking(tx_freq_hz, ctx->tx_sf, phy_tx, phy_len, out_airtime_ms, &t_tx_end);
    if (tx_st != ISAC_LORAWAN_TX_OK) {
        (void)ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_SET_SLEEP, &warm_sleep, 1U);
        return tx_st;
    }

    /* Class A RX1 window: RECEIVE_DELAY1 (1,000 ms default), same channel, SF + rx1_dr_offset */
    rx1_sf = (uint8_t)(ctx->tx_sf + ctx->rx1_dr_offset);
    if (rx1_sf > 12U) {
        rx1_sf = 12U;
    }
    if (!sx1262_timed_rx_slot(t_tx_end, (uint32_t)ctx->rx1_delay_ms,
                              tx_freq_hz, rx1_sf, ISAC_LORAWAN_RX_WINDOW_MS,
                              phy_rx, &rx_len)) {
        ISAC_HAL_RFSwitch_SetMode(ISAC_RFSW_OFF);
        (void)ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_SET_SLEEP, &warm_sleep, 1U);
        return ISAC_LORAWAN_ERR_RADIO_BUSY;
    }
    if (!((rx_len > 0U) && ISAC_LoRaWAN_ProcessDataDownlink(ctx, phy_rx, rx_len))) {
        /* Class A RX2 window: RECEIVE_DELAY2 (RX1 + 1,000 ms), 869.525 MHz, RX2 SF */
        const uint32_t rx2_delay_ms = (uint32_t)ctx->rx1_delay_ms + 1000UL;
        if (!sx1262_timed_rx_slot(t_tx_end, rx2_delay_ms,
                                  ISAC_EU868_RX2_HZ, ctx->rx2_sf, ISAC_LORAWAN_RX_WINDOW_MS,
                                  phy_rx, &rx_len)) {
            ISAC_HAL_RFSwitch_SetMode(ISAC_RFSW_OFF);
            (void)ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_SET_SLEEP, &warm_sleep, 1U);
            return ISAC_LORAWAN_ERR_RADIO_BUSY;
        }
        if (rx_len > 0U) {
            (void)ISAC_LoRaWAN_ProcessDataDownlink(ctx, phy_rx, rx_len);
        }
    }

    /* Park internal SX1262 in warm-start sleep (~500 nA) with PA0=0, PA1=0 */
    ISAC_HAL_RFSwitch_SetMode(ISAC_RFSW_OFF);
    if (!ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_SET_SLEEP, &warm_sleep, 1U)) {
        return ISAC_LORAWAN_ERR_RADIO_BUSY;
    }
    return ISAC_LORAWAN_TX_OK;
}
