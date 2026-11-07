/**
 * @file test_isac_nvm.c
 * @brief Host tests for session persistence (audit B3), provisioning gate and MAC commands (B4).
 *        Flash is emulated in RAM with real-flash semantics (program only onto erased
 *        double-words; erase = 0xFF) plus power-fail injection.
 */
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#include "isac_nvm.h"
#include "isac_lorawan_eu868.h"
#include "isac_hal.h"

#define FL_BASE  0x0803E000UL
#define FL_SIZE  0x2000UL
static uint8_t  g_flash[FL_SIZE];
static int      g_fail_after = -1;   /* program n more dwords, then "lose power" */
static uint32_t g_ecc_fault_addr = 0UL; /* simulated double-bit ECC fault dword address (0 = none) */
static bool     g_ecc_latched = false;
static unsigned g_erases = 0;
static int g_fails = 0, g_pass = 0;

#define CHECK(c, ...) do { if (c) { g_pass++; } else { g_fails++; printf("  FAIL %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

bool ISAC_HAL_Flash_ErasePage(uint32_t a)
{
    if ((a < FL_BASE) || ((a + 2048UL) > (FL_BASE + FL_SIZE)) || (a % 2048UL)) return false;
    memset(&g_flash[a - FL_BASE], 0xFF, 2048U);
    /* Real STM32WLE5JC page erase restores all 72-bit ECC words in the 2 KB page to erased state */
    if ((g_ecc_fault_addr >= a) && (g_ecc_fault_addr < (a + 2048UL))) {
        g_ecc_fault_addr = 0UL;
    }
    g_erases++;
    return true;
}
bool ISAC_HAL_Flash_ProgramDoubleWord(uint32_t a, uint32_t lo, uint32_t hi)
{
    uint8_t *p; uint32_t i;
    if ((a < FL_BASE) || ((a + 8UL) > (FL_BASE + FL_SIZE)) || (a % 8UL)) return false;
    if (g_fail_after == 0) return false;
    if (g_fail_after > 0) g_fail_after--;
    p = &g_flash[a - FL_BASE];
    for (i = 0; i < 8; ++i) if (p[i] != 0xFF) { printf("  (program onto non-erased flash @%08lX)\n", (unsigned long)a); return false; }
    memcpy(p, &lo, 4); memcpy(p + 4, &hi, 4); return true;
}
void ISAC_HAL_Flash_Read(uint32_t a, void *d, uint32_t n)
{
    uint8_t *dst = (uint8_t *)d;
    uint32_t i;
    for (i = 0U; i < n; ++i) {
        const uint32_t cur = a + i;
        if ((g_ecc_fault_addr != 0UL) && (cur >= g_ecc_fault_addr) && (cur < (g_ecc_fault_addr + 8UL))) {
            dst[i] = 0x00U; /* Matches NMI_Handler poison byte on FLASH_ECCR.ECCD */
            g_ecc_latched = true;
        } else {
            dst[i] = g_flash[cur - FL_BASE];
        }
    }
}
bool ISAC_HAL_Flash_ConsumeEccFault(void)
{
    const bool f = g_ecc_latched;
    g_ecc_latched = false;
    return f;
}


/* Radio/timing HAL is not exercised here (MAC/NVM logic only): inert stubs. */
uint32_t ISAC_FreqHz_To_PllStep(uint32_t f);
void ISAC_HAL_RFSwitch_SetMode(isac_rf_switch_mode_t m) { (void)m; }
bool ISAC_HAL_SubGhz_WakeupAndReset(void) { return true; }
bool ISAC_HAL_SubGhz_WriteCmd(uint8_t o, const uint8_t *p, uint8_t l) { (void)o; (void)p; (void)l; return true; }
bool ISAC_HAL_SubGhz_ReadCmd(uint8_t o, uint8_t *r, uint8_t l) { (void)o; memset(r, 0, l); return true; }
bool ISAC_HAL_SubGhz_WriteReg(uint16_t a, const uint8_t *d, uint8_t l) { (void)a; (void)d; (void)l; return true; }
bool ISAC_HAL_SubGhz_ReadReg(uint16_t a, uint8_t *d, uint8_t l) { (void)a; memset(d, 0, l); return true; }
bool ISAC_HAL_SubGhz_WriteBuffer(uint8_t o, const uint8_t *d, uint8_t l) { (void)o; (void)d; (void)l; return true; }
bool ISAC_HAL_SubGhz_ReadBuffer(uint8_t o, uint8_t *d, uint8_t l) { (void)o; memset(d, 0, l); return true; }
uint32_t ISAC_HAL_GetTickMs(void) { return 0; }
void ISAC_HAL_DelayMs(uint32_t ms) { (void)ms; }
void ISAC_HAL_Watchdog_Kick(void) {}
uint32_t ISAC_FreqHz_To_PllStep(uint32_t f) { return f; }
uint32_t ISAC_DutyCycle_MinBackoffMs(uint32_t airtime_ms) { return airtime_ms * 100UL; }

static isac_nvm_session_t mk(uint16_t dn, uint32_t fu)
{
    isac_nvm_session_t s; memset(&s, 0, sizeof s);
    s.dev_nonce = dn; s.joined = 1; s.pending_ack = (uint8_t)(fu & 1U);
    s.rx1_delay_ms = 5000U; s.rx1_dr_offset = 1U; s.rx2_sf = 9U; s.num_channels = 8U;
    s.dev_addr = 0x26ABCDEFUL; s.fcnt_up = fu; s.fcnt_down = fu / 2;
    s.channel_hz[0] = 867100000UL; s.channel_hz[1] = 867300000UL;
    s.channel_hz[2] = 867500000UL; s.channel_hz[3] = 867700000UL; s.channel_hz[4] = 867900000UL;
    memset(s.nwk_skey, 0x11, 16); memset(s.app_skey, 0x22, 16); return s;
}

static void test_crc(void)
{
    CHECK(ISAC_NVM_Crc32("123456789", 9) == 0xCBF43926UL, "CRC-32 check value");
}

static void test_session_basic(void)
{
    isac_nvm_session_t s, l; uint32_t i;
    g_erases = 0;
    memset(g_flash, 0xFF, sizeof g_flash);
    CHECK(!ISAC_NVM_LoadSession(&l), "blank flash => no session");
    for (i = 1; i <= 500; ++i) {              /* spans many page flips */
        s = mk((uint16_t)i, i);
        CHECK(ISAC_NVM_SaveSession(&s), "save %u", (unsigned)i);
        CHECK(ISAC_NVM_LoadSession(&l) && l.fcnt_up == i && l.dev_nonce == (uint16_t)i
              && l.dev_addr == s.dev_addr && l.rx1_delay_ms == 5000U
              && l.rx1_dr_offset == 1U && l.rx2_sf == 9U && l.num_channels == 8U
              && l.channel_hz[4] == 867900000UL
              && !memcmp(l.nwk_skey, s.nwk_skey, 16)
              && !memcmp(l.app_skey, s.app_skey, 16), "roundtrip %u", (unsigned)i);
    }
    CHECK(g_erases >= 20 && g_erases <= 28, "erase count sane for 500 x 96B records (%u)", g_erases);
}

static void test_power_fail(void)
{
    isac_nvm_session_t s, l; int cut;
    /* cut power at every possible point across all 12 double-words of a 96B record */
    for (cut = 0; cut < 13; ++cut) {
        uint32_t i;
        memset(g_flash, 0xFF, sizeof g_flash);
        for (i = 1; i <= ISAC_NVM_RECORDS_PER_PAGE; ++i) { s = mk((uint16_t)i, i); ISAC_NVM_SaveSession(&s); }
        s = mk(9999, 9999);
        g_fail_after = cut;
        (void)ISAC_NVM_SaveSession(&s);
        g_fail_after = -1;
        if (cut < 12) {
            /* BLK-FW-02 commit-last invariant: header MAGIC+seq dword @ Page B offset 0 MUST remain 0xFF until cut == 12! */
            uint32_t b;
            bool hdr_erased = true;
            for (b = 0U; b < 8U; ++b) {
                if (g_flash[(ISAC_NVM_PAGE_B_ADDR - FL_BASE) + b] != 0xFFU) {
                    hdr_erased = false;
                }
            }
            CHECK(hdr_erased, "cut=%d commit-last header MAGIC+seq remained erased (0xFF)", cut);
        }
        CHECK(ISAC_NVM_LoadSession(&l), "cut=%d a valid record survives", cut);
        CHECK(l.fcnt_up == ISAC_NVM_RECORDS_PER_PAGE || l.fcnt_up == 9999U,
              "cut=%d value is old-or-new, never garbage (got %u)", cut, (unsigned)l.fcnt_up);
        /* and the store keeps working afterwards */
        s = mk(10000, 10000);
        CHECK(ISAC_NVM_SaveSession(&s) && ISAC_NVM_LoadSession(&l) && l.fcnt_up == 10000U,
              "cut=%d recovers", cut);
    }
}

static void test_provision(void)
{
    isac_provision_t p, r;
    memset(g_flash, 0xFF, sizeof g_flash);
    CHECK(!ISAC_NVM_ReadProvision(&r), "erased page => NOT provisioned");
    memset(&p, 0, sizeof p);
    p.magic = ISAC_PROV_MAGIC; p.version = ISAC_PROV_VERSION; p.use_otaa = 1;
    p.cal_flags = ISAC_PROV_FLAG_CAL_DRY_VALID | ISAC_PROV_FLAG_CAL_REF_VALID;
    p.cal_dry_mv[0] = 818U; p.cal_dry_mv[1] = 759U; p.cal_dry_mv[2] = 884U;
    p.cal_ref_cdb = -135;
    memset(p.app_key, 0xA5, 16);
    p.crc32 = ISAC_NVM_Crc32(&p, sizeof p - 4);
    memcpy(&g_flash[ISAC_NVM_PROVISION_ADDR - FL_BASE], &p, sizeof p);
    CHECK(ISAC_NVM_ReadProvision(&r) && r.app_key[0] == 0xA5
          && (r.cal_flags & ISAC_PROV_FLAG_CAL_DRY_VALID) != 0U
          && (r.cal_flags & ISAC_PROV_FLAG_CAL_REF_VALID) != 0U
          && r.cal_dry_mv[1] == 759U && r.cal_ref_cdb == -135,
          "valid v2 block with 2-point factory cal accepted");
    g_flash[ISAC_NVM_PROVISION_ADDR - FL_BASE + 20] ^= 1;
    CHECK(!ISAC_NVM_ReadProvision(&r), "corrupt block rejected");
}

static void test_provision_python_fixture(void)
{
    /* LOW-03 fix: resolve fixture path relative to __FILE__ so the binary works from any CWD */
    char path_rel[512];
    const char *src = __FILE__;
    const char *slash = strrchr(src, '/');
    FILE *f = NULL;
    isac_provision_t r;

    if (slash != NULL) {
        size_t dlen = (size_t)(slash - src);
        if (dlen + 36U < sizeof(path_rel)) {
            memcpy(path_rel, src, dlen);
            strcpy(path_rel + dlen, "/data/provision_page_fixture.bin");
            f = fopen(path_rel, "rb");
        }
    }
    if (f == NULL) {
        f = fopen("test/data/provision_page_fixture.bin", "rb");
    }
    if (f == NULL) {
        f = fopen("firmware/test/data/provision_page_fixture.bin", "rb");
    }
    memset(g_flash, 0xFF, sizeof g_flash);
    CHECK(f != NULL, "fixture present (CWD-independent via __FILE__)");
    if (f) {
        CHECK(fread(&g_flash[ISAC_NVM_PROVISION_ADDR - FL_BASE], 1, 2048, f) == 2048U, "fixture size");
        fclose(f);
        CHECK(ISAC_NVM_ReadProvision(&r) && r.use_otaa == 1U && r.join_eui[0] == 0x70U,
              "python-generated page accepted by firmware parser");
    }
}

static unsigned g_cb;
static void cb(const isac_lorawan_ctx_t *c) { (void)c; g_cb++; }

static void test_mac_and_persist_hooks(void)
{
    isac_lorawan_ctx_t c; uint8_t eui[8] = {0}, key[16] = {0}, phy[64], app[10] = {0}; uint8_t n;
    uint8_t cmds[] = { 0x06, 0x03, 0x00,0x00,0x00,0x00, 0x08, 0x03, 0x0A, 1,2,3,4, 0x77 };
    ISAC_LoRaWAN_InitOTAA(&c, eui, eui, key);
    c.persist_cb = cb;
    CHECK(ISAC_LoRaWAN_BuildJoinRequest(&c, phy) == 23U && g_cb == 1U && c.dev_nonce == 1U, "DevNonce persisted before TX");
    ISAC_LoRaWAN_BuildJoinRequest(&c, phy);
    CHECK(c.dev_nonce == 2U && g_cb == 2U, "DevNonce monotonic");

    ISAC_LoRaWAN_RestoreSession(&c, 7, true, 0x26000001UL, 41, 3, key, key);
    CHECK(c.joined && c.fcnt_up == 41U && c.dev_nonce == 7U, "restore");
    c.battery_level = 200;
    ISAC_LoRaWAN_ProcessMacCommands(&c, cmds, sizeof cmds);
    /* DevStatusAns(3) + LinkADRAns(2) + RXTimingAns(1) + DlChannelAns(2) = 8, unknown CID stops parse */
    CHECK(c.mac_ans_len == 8U && c.mac_ans[0] == 0x06 && c.mac_ans[1] == 200 && c.mac_ans[3] == 0x03
          && c.mac_ans[4] == 0x00 && c.mac_ans[5] == 0x08 && c.mac_ans[6] == 0x0A && c.mac_ans[7] == 0x00,
          "answers: len=%u", c.mac_ans_len);
    CHECK(c.rx1_delay_ms == 3000U, "RX1 delay applied");

    g_cb = 0;
    n = ISAC_LoRaWAN_BuildUnconfirmedUplink(&c, 10U, app, 10U, phy);
    CHECK(n == (uint8_t)(23U + 8U), "uplink carries FOpts (len %u)", n);
    CHECK((phy[5] & 0x0FU) == 8U && (phy[5] & 0x80U) == 0U, "FOptsLen=8, ADR bit clear");
    CHECK(g_cb == 1U && c.fcnt_up == 42U && c.mac_ans_len == 0U, "counter persisted after increment, answers flushed");

    /* HIGH-04: Verify full LoRaWAN session (CFList + RxDelay + rx1_dr_offset + rx2_sf + pending_ack + fcnt_down)
     * survives simulated MCU reset via ISAC_LoRaWAN_SaveToNvmSession / ISAC_LoRaWAN_RestoreFromNvmSession */
    {
        isac_lorawan_ctx_t c_reboot;
        isac_nvm_session_t snap, loaded;
        memset(g_flash, 0xFF, sizeof g_flash);
        c.rx1_delay_ms   = 5000U;
        c.rx1_dr_offset  = 2U;
        c.rx2_sf         = 9U;
        c.pending_ack    = true;
        c.fcnt_down      = 19UL;
        c.num_channels   = 8U;
        c.channel_hz[3]  = 867100000UL;
        c.channel_hz[4]  = 867300000UL;
        c.channel_hz[5]  = 867500000UL;
        c.channel_hz[6]  = 867700000UL;
        c.channel_hz[7]  = 867900000UL;

        ISAC_LoRaWAN_SaveToNvmSession(&c, &snap);
        CHECK(ISAC_NVM_SaveSession(&snap), "HIGH-04 snapshot save");
        ISAC_LoRaWAN_InitOTAA(&c_reboot, eui, eui, key);
        CHECK(ISAC_NVM_LoadSession(&loaded), "HIGH-04 snapshot load");
        ISAC_LoRaWAN_RestoreFromNvmSession(&c_reboot, &loaded);
        CHECK(c_reboot.joined &&
              c_reboot.rx1_delay_ms == 5000U &&
              c_reboot.rx1_dr_offset == 2U &&
              c_reboot.rx2_sf == 9U &&
              c_reboot.pending_ack &&
              c_reboot.fcnt_down == 19UL &&
              c_reboot.num_channels == 8U &&
              c_reboot.channel_hz[3] == 867100000UL &&
              c_reboot.channel_hz[7] == 867900000UL &&
              c_reboot.sticky_mac_ans_len == 3U &&
              c_reboot.sticky_mac_ans[0] == 0x08U &&
              c_reboot.sticky_mac_ans[1] == 0x0AU,
              "HIGH-04/HIGH-05 full MAC + sticky session restored identically after MCU reset");

        /* HIGH-05: Second uplink (still awaiting network DL ack) MUST repeat sticky 0x08 + 0x0A,0x00 (3 B),
         * while dropping one-shot DevStatusAns (0x06) and LinkADRAns (0x03)! */
        n = ISAC_LoRaWAN_BuildUnconfirmedUplink(&c_reboot, 10U, app, 10U, phy);
        CHECK(n == (uint8_t)(23U + 3U) && (phy[5] & 0x0FU) == 3U &&
              phy[8] == 0x08U && phy[9] == 0x0AU && phy[10] == 0x00U,
              "HIGH-05 sticky RXTimingSetupAns + DlChannelAns repeated on uplink until valid DL (len=%u)", n);

        /* HIGH-05: Truncated MAC command buffer MUST NOT read out-of-bounds or enqueue bogus answers */
        {
            uint8_t trunc_adr[3] = { 0x03U, 0x11U, 0x22U }; /* LinkADRReq needs 5 bytes */
            uint8_t trunc_rxt[1] = { 0x08U };               /* RXTimingSetupReq needs 2 bytes */
            c_reboot.mac_ans_len = 0U;
            ISAC_LoRaWAN_ProcessMacCommands(&c_reboot, trunc_adr, sizeof trunc_adr);
            ISAC_LoRaWAN_ProcessMacCommands(&c_reboot, trunc_rxt, sizeof trunc_rxt);
            CHECK(c_reboot.mac_ans_len == 0U && c_reboot.rx1_delay_ms == 5000U,
                  "HIGH-05 truncated MAC commands safely rejected without state mutation");
        }

        /* HIGH-05: Malformed downlink with FOptsLen > 0 AND FPort == 0 MUST be rejected BEFORE fcnt_down update */
        {
            uint8_t bad_dl[16] = { 0 };
            uint32_t mic;
            bad_dl[0] = ISAC_LORAWAN_MHDR_CONF_DATA_DOWN;
            bad_dl[1] = 0x01U; bad_dl[2] = 0x00U; bad_dl[3] = 0x00U; bad_dl[4] = 0x26U; /* 0x26000001 */
            bad_dl[5] = 0x02U; /* FOptsLen = 2 */
            bad_dl[6] = 20U;   bad_dl[7] = 0U; /* FCntDown = 20 */
            bad_dl[8] = 0x08U; bad_dl[9] = 0x01U; /* FOpts */
            bad_dl[10] = 0x00U; /* FPort == 0 (illegal when FOptsLen > 0!) */
            bad_dl[11] = 0xAAU;
            mic = ISAC_LoRaWAN_ComputeDataMIC(c_reboot.nwk_skey, 0x26000001UL, 1U, 20UL, bad_dl, 12U);
            bad_dl[12] = (uint8_t)(mic);       bad_dl[13] = (uint8_t)(mic >> 8);
            bad_dl[14] = (uint8_t)(mic >> 16); bad_dl[15] = (uint8_t)(mic >> 24);
            c_reboot.pending_ack = false;
            CHECK(!ISAC_LoRaWAN_ProcessDataDownlink(&c_reboot, bad_dl, 16U) &&
                  c_reboot.fcnt_down == 19UL && !c_reboot.pending_ack &&
                  c_reboot.sticky_mac_ans_len == 3U,
                  "HIGH-05 FOptsLen>0 && FPort==0 rejected before fcnt_down/pending_ack update");
        }

        /* HIGH-05: Downlink exceeding MAX_FCNT_GAP (16384) MUST be rejected */
        {
            uint8_t gap_dl[12] = { 0 };
            uint32_t gap_fcnt = 19UL + ISAC_LORAWAN_MAX_FCNT_GAP;
            uint32_t mic;
            gap_dl[0] = ISAC_LORAWAN_MHDR_UNCONF_DATA_DOWN;
            gap_dl[1] = 0x01U; gap_dl[2] = 0x00U; gap_dl[3] = 0x00U; gap_dl[4] = 0x26U;
            gap_dl[5] = 0x00U;
            gap_dl[6] = (uint8_t)(gap_fcnt & 0xFFU);
            gap_dl[7] = (uint8_t)((gap_fcnt >> 8U) & 0xFFU);
            mic = ISAC_LoRaWAN_ComputeDataMIC(c_reboot.nwk_skey, 0x26000001UL, 1U, gap_fcnt, gap_dl, 8U);
            gap_dl[8] = (uint8_t)(mic);       gap_dl[9]  = (uint8_t)(mic >> 8);
            gap_dl[10]= (uint8_t)(mic >> 16); gap_dl[11] = (uint8_t)(mic >> 24);
            CHECK(!ISAC_LoRaWAN_ProcessDataDownlink(&c_reboot, gap_dl, 12U) &&
                  c_reboot.fcnt_down == 19UL,
                  "HIGH-05 downlink with gap >= 16384 rejected");
        }

        /* HIGH-05: Valid authenticated downlink clears sticky MAC answers so next uplink has FOptsLen == 0 */
        {
            uint8_t ok_dl[12] = { 0 };
            uint32_t mic;
            ok_dl[0] = ISAC_LORAWAN_MHDR_UNCONF_DATA_DOWN;
            ok_dl[1] = 0x01U; ok_dl[2] = 0x00U; ok_dl[3] = 0x00U; ok_dl[4] = 0x26U;
            ok_dl[5] = 0x00U;
            ok_dl[6] = 20U; ok_dl[7] = 0U;
            mic = ISAC_LoRaWAN_ComputeDataMIC(c_reboot.nwk_skey, 0x26000001UL, 1U, 20UL, ok_dl, 8U);
            ok_dl[8] = (uint8_t)(mic);       ok_dl[9]  = (uint8_t)(mic >> 8);
            ok_dl[10]= (uint8_t)(mic >> 16); ok_dl[11] = (uint8_t)(mic >> 24);
            CHECK(ISAC_LoRaWAN_ProcessDataDownlink(&c_reboot, ok_dl, 12U) &&
                  c_reboot.fcnt_down == 21UL && c_reboot.sticky_mac_ans_len == 0U,
                  "HIGH-05 valid downlink clears sticky MAC answers");
            n = ISAC_LoRaWAN_BuildUnconfirmedUplink(&c_reboot, 10U, app, 10U, phy);
            CHECK(n == 23U && (phy[5] & 0x0FU) == 0U, "post-DL uplink has clean FOptsLen=0");
        }
    }
}

static void test_ecc_self_healing_and_rx_param_setup(void)
{
    /* 1. BLK-FW-02: Simulated STM32WLE5JC 72-bit Flash double-bit ECC fault (FLASH_ECCR.ECCD)
     *    on an active NVM page slot MUST NOT brick LoadSession() and MUST self-heal on SaveSession() */
    {
        isac_nvm_session_t s, l;
        memset(g_flash, 0xFF, sizeof g_flash);
        g_ecc_fault_addr = 0UL;
        g_ecc_latched = false;

        s = mk(101U, 101UL);
        CHECK(ISAC_NVM_SaveSession(&s), "ECC setup slot 0");
        s = mk(102U, 102UL);
        CHECK(ISAC_NVM_SaveSession(&s), "ECC setup slot 1");

        /* Inject double-bit ECC fault inside slot 2's payload region on Page A (simulate brownout mid-write) */
        g_fail_after = 3;
        s = mk(103U, 103UL);
        (void)ISAC_NVM_SaveSession(&s);
        g_fail_after = -1;
        g_ecc_fault_addr = ISAC_NVM_PAGE_A_ADDR + (2UL * ISAC_NVM_RECORD_SIZE) + 16UL;

        /* Even if ECC fault sits directly inside slot 1's payload, LoadSession falls back to slot 0 without NMI crash! */
        g_ecc_fault_addr = ISAC_NVM_PAGE_A_ADDR + (1UL * ISAC_NVM_RECORD_SIZE) + 16UL;
        CHECK(ISAC_NVM_LoadSession(&l) && l.fcnt_up == 101UL,
              "BLK-FW-02 LoadSession survives ECC fault on slot 1 and recovers slot 0 (fcnt=%lu)",
              (unsigned long)l.fcnt_up);

        /* Next SaveSession() detects ECC fault on Page A, migrates cleanly to Page B, and erases/heals Page A! */
        s = mk(104U, 104UL);
        CHECK(ISAC_NVM_SaveSession(&s), "BLK-FW-02 SaveSession migrates & heals ECC-corrupted Page A");
        CHECK(g_ecc_fault_addr == 0UL, "BLK-FW-02 Page A erase healed simulated 72-bit ECC fault");
        CHECK(ISAC_NVM_LoadSession(&l) && l.fcnt_up == 104UL && !ISAC_HAL_Flash_ConsumeEccFault(),
              "BLK-FW-02 Post-heal LoadSession clean on Page B with zero residual ECC faults");
    }

    /* 1b. HIGH-FW-04: Inactive-page ECC scar MUST NOT erase or discard free slots on clean active page */
    {
        isac_nvm_session_t s, l;
        uint32_t magic_slot2 = 0UL;
        memset(g_flash, 0xFF, sizeof g_flash);
        g_ecc_fault_addr = 0UL;
        g_ecc_latched = false;

        s = mk(201U, 201UL);
        CHECK(ISAC_NVM_SaveSession(&s), "HIGH-FW-04 setup Page A slot 0");
        s = mk(202U, 202UL);
        CHECK(ISAC_NVM_SaveSession(&s), "HIGH-FW-04 setup Page A slot 1");

        /* Inject brownout ECC scar on INACTIVE Page B while active Page A still has 19 blank slots */
        g_ecc_fault_addr = ISAC_NVM_PAGE_B_ADDR + 32UL;
        g_erases = 0U;
        s = mk(203U, 203UL);
        CHECK(ISAC_NVM_SaveSession(&s), "HIGH-FW-04 SaveSession with inactive Page B ECC scar");
        memcpy(&magic_slot2, &g_flash[(ISAC_NVM_PAGE_A_ADDR - FL_BASE) + (2UL * ISAC_NVM_RECORD_SIZE)], 4U);
        CHECK(g_erases == 1U && g_ecc_fault_addr == 0UL && magic_slot2 == ISAC_NVM_REC_MAGIC,
              "HIGH-FW-04 appended to clean Page A slot 2 and healed ONLY inactive Page B (erases=%u)",
              g_erases);
        CHECK(ISAC_NVM_LoadSession(&l) && l.fcnt_up == 203UL && !ISAC_HAL_Flash_ConsumeEccFault(),
              "HIGH-FW-04 Post-heal LoadSession reads slot 2 on Page A with zero ECC faults");
    }

    /* 2. HIGH-FW-03: LoRaWAN 1.0.3 §5.4 RXParamSetupReq (0x05) full parameter validation + sticky Ans */
    {
        isac_lorawan_ctx_t c;
        uint8_t key[16] = { 0x11U };
        /* Valid: DLSettings = 0x23 (RX1DROffset=2, RX2DataRate=DR3 -> SF9), Freq = 869.525 MHz (8695250 = 0x84ADD2 LE) */
        const uint8_t req_ok[5]      = { 0x05U, 0x23U, 0xD2U, 0xADU, 0x84U };
        /* Invalid channel frequency: 868.100 MHz (8681000 = 0x847628 LE) -> status 0x06 */
        const uint8_t req_bad_ch[5]  = { 0x05U, 0x13U, 0x28U, 0x76U, 0x84U };
        /* Invalid RX2DataRate = DR6 (6 > 5) @ 869.525 MHz -> status 0x05 */
        const uint8_t req_bad_dr[5]  = { 0x05U, 0x16U, 0xD2U, 0xADU, 0x84U };
        /* Invalid RX1DROffset = 6 (> 5) @ DR3, 869.525 MHz -> status 0x03 */
        const uint8_t req_bad_off[5] = { 0x05U, 0x63U, 0xD2U, 0xADU, 0x84U };

        ISAC_LoRaWAN_InitABP(&c, 0x26018685UL, key, key);
        ISAC_LoRaWAN_ProcessMacCommands(&c, req_ok, sizeof req_ok);
        CHECK(c.rx1_dr_offset == 2U && c.rx2_sf == 9U &&
              c.mac_ans_len == 2U && c.mac_ans[0] == 0x05U && c.mac_ans[1] == 0x07U &&
              c.sticky_mac_ans_len == 2U && c.sticky_mac_ans[0] == 0x05U && c.sticky_mac_ans[1] == 0x07U,
              "HIGH-FW-03 valid RXParamSetupReq (DR3/SF9 @ 869.525 MHz, off=2) applied with sticky 0x07 ACK");

        c.mac_ans_len = 0U;
        c.sticky_mac_ans_len = 0U;
        ISAC_LoRaWAN_ProcessMacCommands(&c, req_bad_ch, sizeof req_bad_ch);
        CHECK(c.rx1_dr_offset == 2U && c.rx2_sf == 9U &&
              c.mac_ans_len == 2U && c.mac_ans[0] == 0x05U && c.mac_ans[1] == 0x06U,
              "HIGH-FW-03 non-869.525 MHz RXParamSetupReq NACKed (0x06) without mutating RX params");

        c.mac_ans_len = 0U;
        c.sticky_mac_ans_len = 0U;
        ISAC_LoRaWAN_ProcessMacCommands(&c, req_bad_dr, sizeof req_bad_dr);
        CHECK(c.rx1_dr_offset == 2U && c.rx2_sf == 9U &&
              c.mac_ans_len == 2U && c.mac_ans[0] == 0x05U && c.mac_ans[1] == 0x05U,
              "HIGH-FW-03 unsupported RX2DataRate DR6 NACKed (0x05) without mutating RX params");

        c.mac_ans_len = 0U;
        c.sticky_mac_ans_len = 0U;
        ISAC_LoRaWAN_ProcessMacCommands(&c, req_bad_off, sizeof req_bad_off);
        CHECK(c.rx1_dr_offset == 2U && c.rx2_sf == 9U &&
              c.mac_ans_len == 2U && c.mac_ans[0] == 0x05U && c.mac_ans[1] == 0x03U,
              "HIGH-FW-03 invalid RX1DROffset=6 NACKed (0x03) without mutating RX params");
    }
}

int main(void)
{
    printf("ISAC NVM / MAC host tests\n");
    test_crc(); test_session_basic(); test_power_fail(); test_provision(); test_provision_python_fixture();
    test_mac_and_persist_hooks(); test_ecc_self_healing_and_rx_param_setup();
    printf("NVM SUMMARY: %d assertions passed, %d failed\n", g_pass, g_fails);
    return g_fails ? 1 : 0;
}
