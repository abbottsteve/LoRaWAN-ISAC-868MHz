/**
 * @file isac_nvm.c
 * @brief Power-fail-safe LoRaWAN session store + provisioning reader (see isac_nvm.h)
 */
#include "isac_nvm.h"

#include <stddef.h>
#include <string.h>

/* Wire layout shared with tools/provision_unit.py (struct "<IBBH8s8s16sI16s16s3HhI") */
_Static_assert(sizeof(isac_provision_t) == 88U, "isac_provision_t layout");
_Static_assert(offsetof(isac_provision_t, crc32) == 84U, "isac_provision_t crc offset");
_Static_assert(offsetof(isac_provision_t, cal_ref_cdb) == 82U, "isac_provision_t cal_ref_cdb offset");
_Static_assert(offsetof(isac_provision_t, cal_dry_mv) == 76U, "isac_provision_t cal_dry_mv offset");
_Static_assert(offsetof(isac_provision_t, abp_dev_addr) == 40U, "isac_provision_t abp offset");
_Static_assert((ISAC_NVM_RECORD_SIZE % 8U) == 0U, "ISAC_NVM_RECORD_SIZE must be 8-byte aligned");

/* ---- little-endian helpers --------------------------------------------------------- */
static void put_u32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)(v);
    p[1] = (uint8_t)(v >> 8);
    p[2] = (uint8_t)(v >> 16);
    p[3] = (uint8_t)(v >> 24);
}

static uint32_t get_u32(const uint8_t *p)
{
    return ((uint32_t)p[0]) | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

uint32_t ISAC_NVM_Crc32(const void *data, uint32_t len)
{
    const uint8_t *p   = (const uint8_t *)data;
    uint32_t       crc = 0xFFFFFFFFUL;
    uint32_t       i;
    uint8_t        b;

    for (i = 0U; i < len; ++i) {
        crc ^= p[i];
        for (b = 0U; b < 8U; ++b) {
            crc = (crc >> 1) ^ (0xEDB88320UL & (0UL - (crc & 1UL)));
        }
    }
    return ~crc;
}

/* ---- provisioning ------------------------------------------------------------------ */
bool ISAC_NVM_ReadProvision(isac_provision_t *out)
{
    isac_provision_t p;

    if (out == NULL) {
        return false;
    }
    ISAC_HAL_Flash_Read(ISAC_NVM_PROVISION_ADDR, &p, (uint32_t)sizeof(p));
    if ((p.magic != ISAC_PROV_MAGIC) || (p.version != ISAC_PROV_VERSION)) {
        return false;
    }
    if (ISAC_NVM_Crc32(&p, (uint32_t)(sizeof(p) - sizeof(p.crc32))) != p.crc32) {
        return false;
    }
    *out = p;
    return true;
}

/* ---- session log ------------------------------------------------------------------- */
typedef struct {
    bool     valid;
    uint32_t page_addr;
    uint32_t slot;
    uint32_t seq;
} rec_pos_t;

static uint32_t page_base(uint32_t idx)
{
    return (idx == 0U) ? ISAC_NVM_PAGE_A_ADDR : ISAC_NVM_PAGE_B_ADDR;
}

static bool slot_blank(const uint8_t rec[ISAC_NVM_RECORD_SIZE])
{
    uint8_t i;
    for (i = 0U; i < ISAC_NVM_RECORD_SIZE; ++i) {
        if (rec[i] != 0xFFU) {
            return false;
        }
    }
    return true;
}

static bool rec_valid(const uint8_t rec[ISAC_NVM_RECORD_SIZE], uint32_t *seq_out)
{
    if (get_u32(&rec[0]) != ISAC_NVM_REC_MAGIC) {
        return false;
    }
    if (ISAC_NVM_Crc32(&rec[12], ISAC_NVM_RECORD_SIZE - 12U) != get_u32(&rec[8])) {
        return false;
    }
    *seq_out = get_u32(&rec[4]);
    return true;
}

/* Newest valid record across both pages. Sequence compare is wrap-safe. */
static rec_pos_t find_newest(uint8_t rec_out[ISAC_NVM_RECORD_SIZE], bool ecc_page[2])
{
    rec_pos_t best = { false, 0UL, 0UL, 0UL };
    uint32_t  pg, s;
    uint8_t   rec[ISAC_NVM_RECORD_SIZE];

    for (pg = 0U; pg < 2U; ++pg) {
        if (ecc_page != NULL) {
            (void)ISAC_HAL_Flash_ConsumeEccFault();
        }
        for (s = 0U; s < ISAC_NVM_RECORDS_PER_PAGE; ++s) {
            uint32_t seq;
            ISAC_HAL_Flash_Read(page_base(pg) + (s * ISAC_NVM_RECORD_SIZE), rec, ISAC_NVM_RECORD_SIZE);
            if (rec_valid(rec, &seq)) {
                if (!best.valid || ((int32_t)(seq - best.seq) > 0)) {
                    best.valid     = true;
                    best.page_addr = page_base(pg);
                    best.slot      = s;
                    best.seq       = seq;
                    if (rec_out != NULL) {
                        memcpy(rec_out, rec, ISAC_NVM_RECORD_SIZE);
                    }
                }
            }
        }
        if (ecc_page != NULL) {
            ecc_page[pg] = ISAC_HAL_Flash_ConsumeEccFault();
        }
    }
    return best;
}

bool ISAC_NVM_LoadSession(isac_nvm_session_t *out)
{
    uint8_t   rec[ISAC_NVM_RECORD_SIZE];
    rec_pos_t pos;
    uint8_t   k;

    if (out == NULL) {
        return false;
    }
    pos = find_newest(rec, NULL);
    if (!pos.valid) {
        return false;
    }
    memset(out, 0, sizeof(*out));
    out->dev_nonce     = (uint16_t)(rec[12] | ((uint16_t)rec[13] << 8));
    out->joined        = rec[14];
    out->pending_ack   = rec[15];
    out->dev_addr      = get_u32(&rec[16]);
    out->fcnt_up       = get_u32(&rec[20]);
    out->fcnt_down     = get_u32(&rec[24]);
    out->rx1_delay_ms  = (uint16_t)(rec[28] | ((uint16_t)rec[29] << 8));
    out->rx1_dr_offset = rec[30];
    out->rx2_sf        = rec[31];
    memcpy(out->nwk_skey, &rec[32], 16U);
    memcpy(out->app_skey, &rec[48], 16U);
    out->num_channels  = rec[64];
    for (k = 0U; k < 5U; ++k) {
        out->channel_hz[k] = get_u32(&rec[68U + (k * 4U)]);
    }
    out->sticky_mac_ans_len = (rec[88] <= ISAC_NVM_MAX_STICKY_MAC_ANS) ? rec[88] : 0U;
    if (out->sticky_mac_ans_len > 0U) {
        memcpy(out->sticky_mac_ans, &rec[89], out->sticky_mac_ans_len);
    }
    return true;
}

static bool program_record(uint32_t addr, const uint8_t rec[ISAC_NVM_RECORD_SIZE])
{
    uint8_t i;
    /* Write payload + CRC32 double-words (offsets 8..88) FIRST, and commit
     * header double-word 0 (ISAC_NVM_REC_MAGIC + seq) LAST so any mid-record power-cut
     * leaves bytes 0..7 erased (0xFF) until the full CRC-verified body is committed. */
    for (i = 8U; i < ISAC_NVM_RECORD_SIZE; i += 8U) {
        if (!ISAC_HAL_Flash_ProgramDoubleWord(addr + i, get_u32(&rec[i]), get_u32(&rec[i + 4U]))) {
            return false;
        }
    }
    return ISAC_HAL_Flash_ProgramDoubleWord(addr, get_u32(&rec[0]), get_u32(&rec[4]));
}

static bool page_is_blank(uint32_t page_addr)
{
    uint8_t  rec[ISAC_NVM_RECORD_SIZE];
    uint32_t s;
    for (s = 0U; s < ISAC_NVM_RECORDS_PER_PAGE; ++s) {
        ISAC_HAL_Flash_Read(page_addr + (s * ISAC_NVM_RECORD_SIZE), rec, ISAC_NVM_RECORD_SIZE);
        if (!slot_blank(rec)) {
            return false;
        }
    }
    return true;
}

bool ISAC_NVM_SaveSession(const isac_nvm_session_t *in)
{
    uint8_t   rec[ISAC_NVM_RECORD_SIZE];
    uint8_t   cur[ISAC_NVM_RECORD_SIZE];
    rec_pos_t pos;
    uint32_t  seq, target_page, target_slot;
    uint32_t  s;
    bool      ecc_page[2] = { false, false };
    uint32_t  heal_page_addr = 0UL;

    if (in == NULL) {
        return false;
    }
    pos = find_newest(NULL, ecc_page);
    seq = pos.valid ? (pos.seq + 1UL) : 1UL;

    memset(rec, 0xFF, sizeof(rec));
    memset(&rec[12], 0, ISAC_NVM_RECORD_SIZE - 12U);
    put_u32(&rec[0], ISAC_NVM_REC_MAGIC);
    put_u32(&rec[4], seq);
    rec[12] = (uint8_t)(in->dev_nonce);
    rec[13] = (uint8_t)(in->dev_nonce >> 8);
    rec[14] = in->joined;
    rec[15] = in->pending_ack;
    put_u32(&rec[16], in->dev_addr);
    put_u32(&rec[20], in->fcnt_up);
    put_u32(&rec[24], in->fcnt_down);
    rec[28] = (uint8_t)(in->rx1_delay_ms);
    rec[29] = (uint8_t)(in->rx1_delay_ms >> 8);
    rec[30] = in->rx1_dr_offset;
    rec[31] = in->rx2_sf;
    memcpy(&rec[32], in->nwk_skey, 16U);
    memcpy(&rec[48], in->app_skey, 16U);
    rec[64] = in->num_channels;
    for (s = 0U; s < 5U; ++s) {
        put_u32(&rec[68U + (s * 4U)], in->channel_hz[s]);
    }
    rec[88] = (in->sticky_mac_ans_len <= ISAC_NVM_MAX_STICKY_MAC_ANS)
            ? in->sticky_mac_ans_len
            : ISAC_NVM_MAX_STICKY_MAC_ANS;
    if (rec[88] > 0U) {
        memcpy(&rec[89], in->sticky_mac_ans, rec[88]);
    }
    put_u32(&rec[8], ISAC_NVM_Crc32(&rec[12], ISAC_NVM_RECORD_SIZE - 12U));

    if (!pos.valid) {
        /* Fresh/corrupt store: start clean in page A (and heal page B if ECC-corrupted) */
        target_page = ISAC_NVM_PAGE_A_ADDR;
        if ((!page_is_blank(target_page) || ISAC_HAL_Flash_ConsumeEccFault() || ecc_page[0]) &&
            !ISAC_HAL_Flash_ErasePage(target_page)) {
            return false;
        }
        if (ecc_page[1]) {
            (void)ISAC_HAL_Flash_ErasePage(ISAC_NVM_PAGE_B_ADDR);
        }
        target_slot = 0UL;
    } else {
        /* Track per-page ECC faults so an inactive-page ECC scar heals ONLY the
         * inactive page without erasing or discarding free slots on a clean active page. */
        const uint32_t active_idx = (pos.page_addr == ISAC_NVM_PAGE_A_ADDR) ? 0U : 1U;
        const uint32_t other_idx  = 1U - active_idx;
        const uint32_t other_page = page_base(other_idx);
        bool           active_ecc = ecc_page[active_idx];

        target_page = pos.page_addr;
        target_slot = ISAC_NVM_RECORDS_PER_PAGE;
        if (!active_ecc) {
            for (s = pos.slot + 1UL; s < ISAC_NVM_RECORDS_PER_PAGE; ++s) {
                ISAC_HAL_Flash_Read(target_page + (s * ISAC_NVM_RECORD_SIZE), cur, ISAC_NVM_RECORD_SIZE);
                if (ISAC_HAL_Flash_ConsumeEccFault()) {
                    active_ecc = true;
                    break;
                }
                if (slot_blank(cur)) {
                    target_slot = s;
                    break;
                }
            }
        }
        if (active_ecc || (target_slot >= ISAC_NVM_RECORDS_PER_PAGE)) {
            /* Active page full or ECC-corrupted: erase OTHER page first (old record stays intact until commit) */
            target_page = other_page;
            if (!ISAC_HAL_Flash_ErasePage(target_page)) {
                return false;
            }
            target_slot    = 0UL;
            heal_page_addr = active_ecc ? pos.page_addr : 0UL;
        } else if (ecc_page[other_idx]) {
            /* Active page is clean with free slots; post-commit heal ONLY the faulted inactive page */
            heal_page_addr = other_page;
        }
    }
    if (!program_record(target_page + (target_slot * ISAC_NVM_RECORD_SIZE), rec)) {
        return false;
    }
    if (heal_page_addr != 0UL) {
        /* Safe post-commit heal: new record is committed on target_page before erasing ECC-faulted page */
        (void)ISAC_HAL_Flash_ErasePage(heal_page_addr);
    }
    (void)ISAC_HAL_Flash_ConsumeEccFault();
    return true;
}
