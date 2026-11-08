/**
 * @file main_target.c
 * @brief Autonomous Low-Power Target Firmware Entry for RAK3172LP-SiP (STM32WLE5JC)
 *
 * Lifecycle per 15-minute (900 s) LSE/RTC Wakeup Cycle (Rev E.5 analytical ~4.4 uA typ avg @ SF7BW125;
 * bench Joulescope/PPK2 verification tracked in `docs/OPEN_ITEMS.md` O-04):
 *   1. Boot: Engage SUBGHZ_SMPSC0R.CLKDE + external 15 uH SMPS buck (`PWR_CR5_SMPSEN` +
 *      `SetRegulatorMode(USE_DCDC)`), enable PB0/DIO3 32 MHz TCXO (`SetDIO3AsTCXOCtrl`),
 *      calibrate all radio blocks, configure +14 dBm `RFO_LP` PA, run boot self-test,
 *      and arm the 32.768 kHz LSE `RTC_WKUP` timer (EXTI Line 20).
 *   2. Wake from STOP2 (analytical ~1.74 uA typ board sleep), execute gated +4.0 dBm 3-tone sweep
 *      (`PA8` `DET_EN` high ONLY during 3.0 ms wakeup + 3 x 600 us CW sweep, then immediately gated LOW).
 *   3. Extract VDDA-droop-immune (`ADC_IN13` VREFINT) & PA-drift-canceled RF features
 *      (`tilt_db_x100`, `notch_db_x100`, `level_dbm_x100`, `eps_est_x100`, `state`).
 *   4. Pack 10-byte Big-Endian `FPort 10` payload, enforce ETSI EN 300 220-1 <= 1%
 *      sub-band duty-cycle budget, execute full LoRaWAN 1.0.3 Class A transaction
 *      (OTAA Join or encrypted `FPort 10` Unconfirmed Data Up + `RX1` + `RX2`), and re-enter STOP2.
 */
#include "isac_board_pins.h"
#include "isac_hal.h"
#include "isac_lorawan_eu868.h"
#include "isac_sensing.h"

/*
 * NO credential is compiled into the image. Keys, EUIs and the OTAA/ABP
 * selection live in a dedicated, per-unit provisioning page (ISAC_NVM_PROVISION_ADDR) written
 * once by tools/provision_unit.py. An erased/corrupt page => the unit stays asleep and never
 * joins or transmits.
 */
#include "isac_nvm.h"

/*
 * worst-case CW dwell per hour must fit inside the STRICTEST EU 863-870 MHz
 * sub-band duty limit (0.1 %, i.e. 3600 ms/h) so that no tone frequency needs separate accounting.
 * Spectral/modulation legality of the CW tones is a lab item (docs/OPEN_ITEMS.md O-05).
 */
_Static_assert(((3600UL / ISAC_DEFAULT_REPORT_PERIOD_S) * ISAC_SWEEP_CW_AIRTIME_MS) <= 3600UL,
               "CW sweep dwell exceeds 0.1% hourly duty cycle");
_Static_assert(ISAC_DEFAULT_REPORT_PERIOD_S >= 60UL, "report period below 60 s is not supported");

/** Brown-out, LT5538 linear-headroom & 1S Li-ion/LiPo over-discharge guards (Rev E.5):
 *  - VDDA < 2700 mV: regulated 3V3 collapsing below LT5538 2.7 V VCC minimum -> inhibit all TX.
 *  - VDDA < 3000 mV or VBAT < 3050 mV: skip CW reflectometry, report FAULT + LowBat if >= 2.7 V / 3.0 V.
 *  - VBAT < 3000 mV: 1S Li-ion/LiPo 0% discharge cutoff (protects bare cells from < 3.0 V). */
#define ISAC_MIN_TX_VDDA_MV     2700U
#define ISAC_MIN_SENSE_VDDA_MV  3000U
#define ISAC_FULL_VDDA_MV       3300U
#define ISAC_MIN_TX_VBAT_MV     3000U
#define ISAC_MIN_SENSE_VBAT_MV  3050U
#define ISAC_FULL_VBAT_MV       4200U

typedef enum {
    ISAC_PROV_OK = 0,
    ISAC_PROV_MISSING = 1
} isac_prov_state_t;

typedef struct {
    uint16_t vrefint_cal;
    uint16_t boot_vdda_mv;
    uint8_t  smpsc0r_readback;
    bool     uid_nonzero;
    bool     vrefint_cal_valid;
    bool     vdda_in_range;
    bool     subghz_spi_ok;
    bool     smps_ready;
    bool     passed;
} isac_boot_selftest_t;

static volatile uint32_t         g_reset_cause;       /* RCC_CSR flags at boot (SWD-inspectable) */
static volatile isac_prov_state_t g_prov_state;
static volatile bool             g_wdt_running;
static volatile uint32_t         g_nvm_save_fail;
static volatile uint32_t         g_tx_inhibit_lowbatt;
static volatile uint32_t         g_sweep_inhibit_duty;
static volatile bool             g_rdp_active;
static volatile isac_boot_selftest_t g_selftest_report;

/* Persistent telemetry, LoRaWAN MAC context & payload shadow in SRAM1 for SWD inspection */
static isac_raw_sweep_t    g_last_sweep;
static isac_telemetry_t    g_last_telemetry;
static isac_duty_tracker_t g_duty_tracker;
static isac_lorawan_ctx_t  g_lorawan_ctx;
static uint8_t             g_fport10_frame[ISAC_FPORT10_PAYLOAD_LEN];

static void nvm_persist_cb(const isac_lorawan_ctx_t *ctx)
{
    isac_nvm_session_t n;

    ISAC_LoRaWAN_SaveToNvmSession(ctx, &n);
    if (!ISAC_NVM_SaveSession(&n)) {
        ++g_nvm_save_fail;
    }
}

static bool provision_lorawan_session(void)
{
    isac_provision_t   prov;
    isac_nvm_session_t sess;
    uint8_t            dev_eui[8];
    uint8_t            i;
    bool               custom_eui = false;

    if (!ISAC_NVM_ReadProvision(&prov)) {
        g_prov_state = ISAC_PROV_MISSING;
        return false;
    }
    g_prov_state = ISAC_PROV_OK;

    for (i = 0U; i < 8U; ++i) {
        if (prov.dev_eui[i] != 0U) {
            custom_eui = true;
        }
        dev_eui[i] = prov.dev_eui[i];
    }
    if (!custom_eui) {
        ISAC_HAL_ReadUniqueId64(dev_eui);
    }

    if (prov.use_otaa != 0U) {
        ISAC_LoRaWAN_InitOTAA(&g_lorawan_ctx, dev_eui, prov.join_eui, prov.app_key);
    } else {
        ISAC_LoRaWAN_InitABP(&g_lorawan_ctx, prov.abp_dev_addr, prov.abp_nwk_skey, prov.abp_app_skey);
    }

    /* Apply per-unit 2-point factory calibration (Point-1 dry-air tare + Point-2 Al2O3/load ref) */
    ISAC_Sensing_SetCalibration2Pt(prov.cal_dry_mv,
                                   (prov.cal_flags & ISAC_PROV_FLAG_CAL_DRY_VALID) != 0U,
                                   prov.cal_ref_cdb,
                                   (prov.cal_flags & ISAC_PROV_FLAG_CAL_REF_VALID) != 0U);

    /* Resume full session (DevNonce, keys, counters, CFList, RX1 delay/DR/RX2) across resets */
    if (ISAC_NVM_LoadSession(&sess)) {
        ISAC_LoRaWAN_RestoreFromNvmSession(&g_lorawan_ctx, &sess);
    }
    g_lorawan_ctx.persist_cb = nvm_persist_cb;

    /* Wipe key material from the stack copy */
    for (i = 0U; i < 16U; ++i) {
        prov.app_key[i] = 0U;
        prov.abp_nwk_skey[i] = 0U;
        prov.abp_app_skey[i] = 0U;
    }
    return true;
}

static uint8_t battery_level_from_rails(uint16_t vbat_mv, uint16_t vdda_mv)
{
    if (vbat_mv != 0U) {
        if (vbat_mv >= ISAC_FULL_VBAT_MV) {
            return 254U;
        }
        if (vbat_mv <= ISAC_MIN_TX_VBAT_MV) {
            return 1U;
        }
        return (uint8_t)(1U + (((uint32_t)(vbat_mv - ISAC_MIN_TX_VBAT_MV) * 253UL)
                              / (uint32_t)(ISAC_FULL_VBAT_MV - ISAC_MIN_TX_VBAT_MV)));
    }
    if (vdda_mv == 0U) {
        return 255U; /* unknown */
    }
    if (vdda_mv >= ISAC_FULL_VDDA_MV) {
        return 254U;
    }
    if (vdda_mv <= ISAC_MIN_TX_VDDA_MV) {
        return 1U;
    }
    return (uint8_t)(1U + (((uint32_t)(vdda_mv - ISAC_MIN_TX_VDDA_MV) * 253UL)
                          / (uint32_t)(ISAC_FULL_VDDA_MV - ISAC_MIN_TX_VDDA_MV)));
}

/**
 * @brief Non-radiating on-target boot self-test (SWD-inspectable via `g_selftest_report`):
 *        checks OTP `VREFINT_CAL`, 64-bit `UID`, live `VDDA` via SAR ADC `VREFINT`,
 *        Sub-GHz SPI register readback (`SUBGHZ_SMPSC0R`), and live `PWR_SR2_SMPSRDY`.
 */
static void run_boot_selftest(bool radio_init_ok)
{
    uint8_t  uid[8];
    uint8_t  stdby_rc   = ISAC_SUBGHZ_STDBY_RC;
    uint8_t  warm_sleep = ISAC_SUBGHZ_SLEEP_WARM_START;
    uint8_t  smpsc0r    = 0U;
    uint16_t vref_cal   = ISAC_HAL_ReadVrefintCal();
    uint32_t vref_raw16;
    uint32_t vdda_mv    = 0UL;
    uint8_t  i;
    bool     uid_ok     = false;
    bool     spi_ok     = false;

    ISAC_HAL_ReadUniqueId64(uid);
    for (i = 0U; i < 8U; ++i) {
        if ((uid[i] != 0x00U) && (uid[i] != 0xFFU)) {
            uid_ok = true;
        }
    }

    ISAC_HAL_ADC_EnableAndCalibrate();
    vref_raw16 = ISAC_HAL_ADC_ReadOversampled16x(ISAC_ADC_CH_VREFINT);
    ISAC_HAL_ADC_Disable();
    if (vref_raw16 != 0UL) {
        vdda_mv = (48000UL * (uint32_t)vref_cal + (vref_raw16 >> 1U)) / vref_raw16;
    }

    if (radio_init_ok &&
        ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_SET_STANDBY, &stdby_rc, 1U) &&
        ISAC_HAL_SubGhz_ReadReg(ISAC_SUBGHZ_REG_SMPSC0R, &smpsc0r, 1U) &&
        ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_SET_SLEEP, &warm_sleep, 1U)) {
        spi_ok = ((smpsc0r & ISAC_SUBGHZ_SMPSC0R_CLKDE) != 0U);
    }

    g_selftest_report.vrefint_cal       = vref_cal;
    g_selftest_report.boot_vdda_mv      = (uint16_t)vdda_mv;
    g_selftest_report.smpsc0r_readback  = smpsc0r;
    g_selftest_report.uid_nonzero       = uid_ok;
    g_selftest_report.vrefint_cal_valid = (vref_cal >= 1400U) && (vref_cal <= 1900U);
    g_selftest_report.vdda_in_range     = (vdda_mv >= ISAC_MIN_TX_VDDA_MV) && (vdda_mv <= 3600UL);
    g_selftest_report.subghz_spi_ok     = spi_ok;
    g_selftest_report.smps_ready        = ISAC_Is_SMPS_Active();
    g_selftest_report.passed            = uid_ok &&
                                          g_selftest_report.vrefint_cal_valid &&
                                          g_selftest_report.vdda_in_range &&
                                          spi_ok &&
                                          g_selftest_report.smps_ready;
}

int main(void)
{
    bool radio_ready;
    bool provisioned;

    g_reset_cause = ISAC_HAL_ResetCause_ReadAndClear();
    g_rdp_active  = ISAC_HAL_ReadoutProtectionActive();
    g_wdt_running = ISAC_HAL_Watchdog_Start();

    ISAC_HAL_RTC_InitWakeup(ISAC_DEFAULT_REPORT_PERIOD_S);
    provisioned = provision_lorawan_session();
    if (!provisioned) {
        /* Initialize all board GPIOs to Analog / 0 nA STOP2 state (PA0=PA1=PA8=PA9=0)
         * and park the internal SX1262 transceiver in sleep BEFORE entering STOP2 so unprovisioned
         * inventory boards never leak Schmitt-trigger or STDBY_RC (~600 uA) shelf current */
        uint8_t cold_sleep = 0x00U;
        ISAC_HAL_GPIO_InitBoardPins();
        ISAC_HAL_GPIO_SetDetEnable(false);
        ISAC_HAL_GPIO_SetBatMonEnable(false);
        ISAC_HAL_RFSwitch_SetMode(ISAC_RFSW_OFF);
        if (ISAC_HAL_SubGhz_WakeupAndReset()) {
            (void)ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_SET_SLEEP, &cold_sleep, 1U);
        }
        for (;;) {
            ISAC_HAL_Watchdog_Kick();
            ISAC_HAL_EnterStop2();
        }
    }
    radio_ready = ISAC_Init_Radio_And_SMPS();
    run_boot_selftest(radio_ready);
    ISAC_DutyCycle_Init(&g_duty_tracker, ISAC_HAL_GetTickMs());

    for (;;) {
        uint32_t       now_ms      = ISAC_HAL_GetTickMs();
        uint32_t       cw_1pct_ms  = ISAC_SWEEP_CW_AIRTIME_MS - ISAC_TONE1_CW_AIRTIME_MS;
        uint32_t       join_toa_ms;
        uint32_t       ul_toa_ms;
        uint32_t       planned_ms;
        uint16_t       rail_vbat_mv = 0U;
        uint16_t       rail_vdda_mv = 0U;
        bool           sweep_ok     = false;

        ISAC_HAL_Watchdog_Kick();
        /* Advance duty-cycle 1-hour window & latch expired TX/Join backoffs on every
         * 900 s wakeup BEFORE any low-battery inhibit branch so multi-month brownouts never wrap 2^31/2^32 ms */
        ISAC_DutyCycle_Tick(&g_duty_tracker, now_ms);
        ISAC_LoRaWAN_TickBackoff(&g_lorawan_ctx, now_ms);

        /* Non-radiating pre-sweep VBAT/VDDA rail check BEFORE any CW PA emission */
        if (!ISAC_Acquire_Supply_Rails(&rail_vbat_mv, &rail_vdda_mv) ||
            (rail_vdda_mv < ISAC_MIN_TX_VDDA_MV) ||
            (rail_vbat_mv < ISAC_MIN_TX_VBAT_MV)) {
            ++g_tx_inhibit_lowbatt;
            ISAC_HAL_EnterStop2();
            continue;
        }

        if (!radio_ready) {
            radio_ready = ISAC_Init_Radio_And_SMPS();
        }

        /* Gate +4.0 dBm CW reflectometry if rails sagged below 3.00 V VDDA / 3.05 V VBAT */
        if ((rail_vdda_mv < ISAC_MIN_SENSE_VDDA_MV) || (rail_vbat_mv < ISAC_MIN_SENSE_VBAT_MV)) {
            cw_1pct_ms = 0UL;
            g_last_telemetry.tilt_db_x100   = 0;
            g_last_telemetry.notch_db_x100  = 0;
            g_last_telemetry.level_dbm_x100 = 0;
            g_last_telemetry.eps_est_x100   = 0U;
            g_last_telemetry.vbat_mv        = rail_vbat_mv;
            g_last_telemetry.vdda_mv        = rail_vdda_mv;
            g_last_telemetry.state          = ISAC_SURFACE_FAULT;
            g_last_telemetry.smps_dcdc_ok   = ISAC_Is_SMPS_Active();
            g_lorawan_ctx.battery_level     = battery_level_from_rails(rail_vbat_mv, rail_vdda_mv);
        } else {
            /* Pre-sweep ETSI <= 0.1% (863.1 MHz) & <= 1.0% duty-cycle gate BEFORE CW */
            if (!ISAC_DutyCycle_CanTransmitSubband0p1(&g_duty_tracker, ISAC_TONE1_CW_AIRTIME_MS, now_ms) ||
                !ISAC_DutyCycle_CanTransmit(&g_duty_tracker, cw_1pct_ms, now_ms)) {
                ++g_sweep_inhibit_duty;
                ISAC_HAL_EnterStop2();
                continue;
            }

            /* 1. Execute gated +4.0 dBm 3-tone ISAC sweep (with TX-off LBS blanking & soft CW quench) */
            sweep_ok = ISAC_Acquire_3Tone_Sweep(&g_last_sweep);
            now_ms   = ISAC_HAL_GetTickMs();
            if (!sweep_ok) {
                radio_ready = false;
                cw_1pct_ms  = 0UL;
            } else {
                ISAC_DutyCycle_RecordSubband0p1AirTime(&g_duty_tracker,
                                                       (uint32_t)g_last_sweep.tone_cw_ms[0],
                                                       now_ms);
                cw_1pct_ms = (uint32_t)g_last_sweep.tone_cw_ms[1]
                           + (uint32_t)g_last_sweep.tone_cw_ms[2];
            }

            /* 2. Extract drift-canceled Tilt, Notch, Level, eps_r' & die-temp-gated Medium Class */
            ISAC_Extract_Features_And_Classify_WithTemp(&g_last_sweep,
                                                        g_last_sweep.die_temp_degc_x10,
                                                        &g_last_telemetry);

            ISAC_HAL_Watchdog_Kick();
            g_lorawan_ctx.battery_level = battery_level_from_rails(g_last_sweep.vbat_mv,
                                                                   g_last_sweep.vdda_mv);

            /* 2b. Loaded CW rail droop guard: abort LoRaWAN TX / flash write if rail sagged under CW */
            if (((g_last_sweep.vdda_mv != 0U) && (g_last_sweep.vdda_mv < ISAC_MIN_TX_VDDA_MV)) ||
                ((g_last_sweep.vbat_mv != 0U) && (g_last_sweep.vbat_mv < ISAC_MIN_TX_VBAT_MV))) {
                if (sweep_ok) {
                    ISAC_DutyCycle_RecordAirTime(&g_duty_tracker, cw_1pct_ms, now_ms);
                }
                ++g_tx_inhibit_lowbatt;
                ISAC_HAL_EnterStop2();
                continue;
            }
        }

        /* Adaptive SF12 (DR0, +12.5 dB gain) fallback whenever radome is wet/iced/detuned */
        join_toa_ms = g_lorawan_ctx.joined
            ? 0UL
            : ISAC_LoRaWAN_CalcTimeOnAirMs(g_lorawan_ctx.tx_sf, ISAC_LORAWAN_JOIN_REQ_PHY_LEN);
        g_lorawan_ctx.tx_sf = ISAC_Select_Uplink_SF(g_last_telemetry.state,
                                                    &g_duty_tracker,
                                                    now_ms,
                                                    cw_1pct_ms + join_toa_ms);
        if (!g_lorawan_ctx.joined) {
            join_toa_ms = ISAC_LoRaWAN_CalcTimeOnAirMs(g_lorawan_ctx.tx_sf,
                                                       ISAC_LORAWAN_JOIN_REQ_PHY_LEN);
        }
        ul_toa_ms  = ISAC_LoRaWAN_CalcTimeOnAirMs(g_lorawan_ctx.tx_sf,
                                                  ISAC_LORAWAN_FPORT10_PHY_LEN);
        planned_ms = cw_1pct_ms + join_toa_ms + ul_toa_ms;

        /* 3. Account for CW sweep + LoRaWAN Class A airtime under ETSI <= 1% duty-cycle cap */
        if (ISAC_DutyCycle_CanTransmit(&g_duty_tracker, planned_ms, now_ms)) {
            uint32_t actual_ul_ms = 0UL;
            isac_lorawan_status_t st;

            ISAC_Pack_LoRaWAN_FPort10(&g_last_telemetry, &g_duty_tracker, g_fport10_frame);
            st = ISAC_LoRaWAN_SendClassA(&g_lorawan_ctx,
                                         ISAC_LORAWAN_FPORT,
                                         g_fport10_frame,
                                         ISAC_FPORT10_PAYLOAD_LEN,
                                         &actual_ul_ms);
            if (st == ISAC_LORAWAN_TX_OK) {
                ISAC_DutyCycle_RecordAirTime(
                    &g_duty_tracker,
                    cw_1pct_ms + join_toa_ms + actual_ul_ms,
                    ISAC_HAL_GetTickMs()
                );
            } else if (st == ISAC_LORAWAN_ERR_RADIO_BUSY) {
                radio_ready = false;
                ISAC_DutyCycle_RecordAirTime(
                    &g_duty_tracker,
                    sweep_ok ? cw_1pct_ms : 0UL,
                    ISAC_HAL_GetTickMs()
                );
            } else {
                /* Even if OTAA JoinAccept timed out, account for CW sweep + JoinRequest TX */
                ISAC_DutyCycle_RecordAirTime(
                    &g_duty_tracker,
                    cw_1pct_ms + join_toa_ms,
                    ISAC_HAL_GetTickMs()
                );
            }
        } else {
            /* Record CW f2+f3 airtime even when LoRaWAN uplink is deferred by 1% duty-cycle cap */
            if (sweep_ok) {
                ISAC_DutyCycle_RecordAirTime(&g_duty_tracker, cw_1pct_ms, now_ms);
            }
            ISAC_Pack_LoRaWAN_FPort10(&g_last_telemetry, &g_duty_tracker, g_fport10_frame);
        }

        ISAC_HAL_Watchdog_Kick();
        /* 4. Re-enter STOP2 deep sleep (~1.74 uA typ) until next LSE RTC_WKUP interrupt */
        ISAC_HAL_EnterStop2();
    }
}
