/**
 * @file isac_sensing.c
 * @brief RAK3172LP-SiP 15 uH SMPS Activation, 3-Tone ISAC Sweep, Feature Extractor & FPort 10 Engine
 */
#include "isac_sensing.h"
#include "isac_board_pins.h"
#include "isac_hal.h"

#include <stddef.h>

static bool     g_subghz_dcdc_configured = false;
static bool     g_cal_dry_valid          = false;
static bool     g_cal_ref_valid          = false;
static uint16_t g_cal_dry_mv[ISAC_NUM_TONES] = { 0U, 0U, 0U };
static int16_t  g_cal_ref_cdb            = 0;

static const uint32_t k_sweep_freqs_hz[ISAC_NUM_TONES] = {
    ISAC_TONE1_FREQ_HZ,  /* 863.1 MHz */
    ISAC_TONE2_FREQ_HZ,  /* 866.5 MHz */
    ISAC_TONE3_FREQ_HZ   /* 869.5 MHz */
};

/* Nominal Rev E.5 +4.0 dBm Enclosed Dry-Air detector voltages [0.1 mV] from 3D-FDTD + Distributed Bridge + ADI LT5538 Z_in */
static const int32_t k_nom_dry_u100[ISAC_NUM_TONES] = { 8180, 7588, 8837 };

/* 11-entry Q12 lookup table for 10^(k / 10) across k = 0..10 dB (4096 = 1.0000) */
static const uint16_t k_pow10_db_q12[11] = {
    4096U, 5157U, 6492U, 8173U, 10289U, 12953U, 16306U, 20529U, 25844U, 32536U, 40960U
};

static uint32_t pow10_db_q12(int32_t db_x100)
{
    int32_t dec = 0;
    int32_t rem = db_x100;
    uint32_t idx, frac, base;

    if (rem <= -1500) {
        return 130UL;
    }
    if (rem >= 3600) {
        return 16306176UL;
    }
    while (rem < 0) {
        rem += 1000;
        --dec;
    }
    while (rem >= 1000) {
        rem -= 1000;
        ++dec;
    }
    idx  = (uint32_t)(rem / 100);
    frac = (uint32_t)(rem - ((int32_t)idx * 100));
    base = (uint32_t)k_pow10_db_q12[idx] +
           (((uint32_t)(k_pow10_db_q12[idx + 1U] - k_pow10_db_q12[idx]) * frac + 50UL) / 100UL);
    while (dec < 0) {
        base = (base + 5UL) / 10UL;
        ++dec;
    }
    while (dec > 0) {
        base *= 10UL;
        --dec;
    }
    return base;
}

static int32_t log10_q12_to_db_x100(uint32_t val_q12)
{
    int32_t dec = 0;
    uint32_t v = val_q12;
    uint32_t idx;

    if (v <= 130UL) {
        return -1500;
    }
    while (v < 4096UL) {
        v *= 10UL;
        --dec;
    }
    while (v >= 40960UL) {
        v = (v + 5UL) / 10UL;
        ++dec;
    }
    for (idx = 0U; idx < 10U; ++idx) {
        if (v <= (uint32_t)k_pow10_db_q12[idx + 1U]) {
            const uint32_t num = (v - (uint32_t)k_pow10_db_q12[idx]) * 100UL;
            const uint32_t den = (uint32_t)(k_pow10_db_q12[idx + 1U] - k_pow10_db_q12[idx]);
            const uint32_t frac = (num + (den >> 1U)) / den;
            return (dec * 1000) + ((int32_t)idx * 100) + (int32_t)frac;
        }
    }
    return (dec + 1) * 1000;
}

void ISAC_Sensing_SetCalibration2Pt(const uint16_t cal_dry_mv[ISAC_NUM_TONES],
                                    bool dry_valid,
                                    int16_t cal_ref_cdb,
                                    bool ref_valid)
{
    uint32_t i;

    if (!dry_valid || (cal_dry_mv == NULL)) {
        g_cal_dry_valid = false;
    } else {
        bool ok = true;
        for (i = 0U; i < ISAC_NUM_TONES; ++i) {
            if ((cal_dry_mv[i] < 100U) || (cal_dry_mv[i] > 2400U)) {
                ok = false;
                break;
            }
        }
        if (ok) {
            for (i = 0U; i < ISAC_NUM_TONES; ++i) {
                g_cal_dry_mv[i] = cal_dry_mv[i];
            }
            g_cal_dry_valid = true;
        } else {
            g_cal_dry_valid = false;
        }
    }

    if (ref_valid && (cal_ref_cdb >= -1200) && (cal_ref_cdb <= 1200)) {
        g_cal_ref_cdb   = cal_ref_cdb;
        g_cal_ref_valid = true;
    } else {
        g_cal_ref_cdb   = 0;
        g_cal_ref_valid = false;
    }
}

void ISAC_Sensing_SetCalibration(const uint16_t cal_dry_mv[ISAC_NUM_TONES], bool valid)
{
    ISAC_Sensing_SetCalibration2Pt(cal_dry_mv, valid, 0, false);
}

static int32_t round_div_s32(int32_t num, int32_t den)
{
    if (num >= 0) {
        return (num + (den / 2)) / den;
    }
    return (num - (den / 2)) / den;
}

/**
 * @brief Convert RF frequency in Hz to SX1262 32-bit PLL step word:
 *        rfFreq = round((freq_hz * 2^25) / 32,000,000)
 *
 * Uses exact 32-bit hardware UDIV decomposition (32,000,000 = 512 * 62,500)
 * so bare-metal Cortex-M4 `-nostdlib` builds never emit 64-bit `__aeabi_uldivmod`.
 */
uint32_t ISAC_FreqHz_To_PllStep(uint32_t freq_hz)
{
    const uint32_t q = freq_hz / 62500UL;
    const uint32_t r = freq_hz % 62500UL;
    return (q << 16) + (((r << 16) + 31250UL) / 62500UL);
}

static bool subghz_set_rf_frequency(uint32_t freq_hz)
{
    const uint32_t pll = ISAC_FreqHz_To_PllStep(freq_hz);
    uint8_t buf[4];
    buf[0] = (uint8_t)((pll >> 24) & 0xFFU);
    buf[1] = (uint8_t)((pll >> 16) & 0xFFU);
    buf[2] = (uint8_t)((pll >> 8)  & 0xFFU);
    buf[3] = (uint8_t)(pll         & 0xFFU);
    return ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_SET_RF_FREQUENCY, buf, 4U);
}

/**
 * @brief Initialize board GPIOs, enable external 15 uH SMPS buck (`PWR_CR5_SMPSEN` +
 *        `SUBGHZ_SetRegulatorMode(0x01)`), enable the internal 32 MHz TCXO on PB0/DIO3
 *        (`SetDIO3AsTCXOCtrl 0x97` + `Calibrate 0x89`), and configure RAK3172LP-SiP +14 dBm RFO_LP PA.
 */
bool ISAC_Init_Radio_And_SMPS(void)
{
    uint8_t stdby_rc = ISAC_SUBGHZ_STDBY_RC;
    uint8_t reg_dcdc = ISAC_SUBGHZ_REGMODE_USE_DCDC;
    uint8_t reg_ldo  = ISAC_SUBGHZ_REGMODE_USE_LDO;
    /* BLK-04 fix: Power RAK3172LP-SiP internal 32 MHz TCXO via PB0/DIO3 at RAKwireless-mandated 3.0 V (0x06,
     * 5.0 ms = 320 ticks), fed cleanly by TPS7A0233DBVR 3.3 V rail with 300 mV headroom (8.3x LDO margin)! */
    uint8_t tcxo_cfg[4] = {
        ISAC_SUBGHZ_TCXO_CTRL_3_0V,
        (uint8_t)((ISAC_SUBGHZ_TCXO_TIMEOUT_5MS_TICKS >> 16U) & 0xFFU),
        (uint8_t)((ISAC_SUBGHZ_TCXO_TIMEOUT_5MS_TICKS >>  8U) & 0xFFU),
        (uint8_t)( ISAC_SUBGHZ_TCXO_TIMEOUT_5MS_TICKS         & 0xFFU)
    };
    uint8_t cal_all  = ISAC_SUBGHZ_CALIBRATE_ALL_BLOCKS;
    /* RM0453 Table 35: Optimal +14 dBm RFO_LP PA config (paDutyCycle=0x04, hpMax=0x00, deviceSel=0x01, paLut=0x01) */
    uint8_t pa_cfg[4] = { 0x04U, 0x00U, ISAC_SUBGHZ_PA_DEVSEL_RFO_LP, 0x01U };
    uint8_t tx_prm[2] = { 14U, ISAC_SUBGHZ_RAMP_40_US };
    /* RM0453 Table 37: 863-870 MHz EU868 image rejection calibration */
    uint8_t cal_img[2] = { 0xD7U, 0xDBU };
    uint8_t rx_boost   = ISAC_SUBGHZ_RX_GAIN_BOOSTED;
    uint8_t warm_sleep = ISAC_SUBGHZ_SLEEP_WARM_START;
    uint8_t smpsc0r    = 0U;
    uint8_t smpsc0r_rb = 0U;
    bool    clkde_ok   = false;
    bool    smps_hw_ok = false;
    bool    radio_ok;

    g_subghz_dcdc_configured = false;

    ISAC_HAL_GPIO_InitBoardPins();
    ISAC_HAL_GPIO_SetDetEnable(false);
    ISAC_HAL_GPIO_SetBatMonEnable(false);
    ISAC_HAL_RFSwitch_SetMode(ISAC_RFSW_OFF);

    /* 1. BLK-03 fix: Wake internal Sub-GHz transceiver, set SUBGHZ_SMPSC0R.CLKDE (0x0916 bit 6),
     *    and READ BACK 0x0916 to verify CLKDE == 1 BEFORE asserting PWR_CR5_SMPSEN per
     *    ST DS13105 Rev 12 §3.9.1 Danger ("risk of destructive damage to the device"). */
    radio_ok = ISAC_HAL_SubGhz_WakeupAndReset() &&
               ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_SET_STANDBY, &stdby_rc, 1U) &&
               ISAC_HAL_SubGhz_ReadReg(ISAC_SUBGHZ_REG_SMPSC0R, &smpsc0r, 1U);
    if (radio_ok) {
        const uint8_t smpsc0r_wr = (uint8_t)(smpsc0r | ISAC_SUBGHZ_SMPSC0R_CLKDE);
        radio_ok = ISAC_HAL_SubGhz_WriteReg(ISAC_SUBGHZ_REG_SMPSC0R, &smpsc0r_wr, 1U) &&
                   ISAC_HAL_SubGhz_ReadReg(ISAC_SUBGHZ_REG_SMPSC0R, &smpsc0r_rb, 1U);
        clkde_ok = radio_ok && ((smpsc0r_rb & ISAC_SUBGHZ_SMPSC0R_CLKDE) != 0U);
    }

    /* 2. Enable STM32WLE5JC MCU SMPS step-down converter ONLY if CLKDE readback succeeded;
     *    otherwise (or if SMPSRDY failed), fall back cleanly to SetRegulatorMode(USE_LDO = 0x00)! */
    if (radio_ok) {
        if (clkde_ok) {
            smps_hw_ok = ISAC_HAL_System_EnableSMPS();
        }
        if (clkde_ok && smps_hw_ok) {
            radio_ok = ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_SET_REGULATOR_MODE, &reg_dcdc, 1U);
            if (radio_ok) {
                g_subghz_dcdc_configured = true;
            }
        } else {
            radio_ok = ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_SET_REGULATOR_MODE, &reg_ldo, 1U);
        }
    }

    /* 3. Enable PB0/DIO3 32 MHz TCXO rail (0x97, 3.0 V = 0x06) and calibrate RC/PLL/ADC/IMG blocks (0x89, 0x98) */
    radio_ok = radio_ok &&
               ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_SET_TCXO_MODE, tcxo_cfg, 4U) &&
               ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_CALIBRATE, &cal_all, 1U) &&
               ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_CALIBRATE_IMAGE, cal_img, 2U);

    /* 4. Select RAK3172LP-SiP RFO_LP path (+14 dBm, 40 us PA ramp), +3 dB Boosted RX Gain (0x08AC = 0x96),
     *    and Semtech SX1262 §15.2 PA Antenna-Mismatch Clamp workaround (0x08D8 |= 0x1E) for wet/iced VSWR ~ 6:1 */
    radio_ok = radio_ok &&
               ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_SET_PA_CONFIG, pa_cfg, 4U) &&
               ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_SET_TX_PARAMS, tx_prm, 2U) &&
               ISAC_HAL_SubGhz_WriteReg(ISAC_SUBGHZ_REG_RX_GAIN, &rx_boost, 1U);
    if (radio_ok) {
        uint8_t tx_clamp    = 0U;
        uint8_t tx_clamp_rb = 0U;
        radio_ok = ISAC_HAL_SubGhz_ReadReg(ISAC_SUBGHZ_REG_TX_CLAMP_CFG, &tx_clamp, 1U);
        if (radio_ok) {
            const uint8_t tx_clamp_wr = (uint8_t)(tx_clamp | ISAC_SUBGHZ_TX_CLAMP_FIX_MASK);
            radio_ok = ISAC_HAL_SubGhz_WriteReg(ISAC_SUBGHZ_REG_TX_CLAMP_CFG, &tx_clamp_wr, 1U) &&
                       ISAC_HAL_SubGhz_ReadReg(ISAC_SUBGHZ_REG_TX_CLAMP_CFG, &tx_clamp_rb, 1U) &&
                       ((tx_clamp_rb & ISAC_SUBGHZ_TX_CLAMP_FIX_MASK) == ISAC_SUBGHZ_TX_CLAMP_FIX_MASK);
        }
    }

    /* 5. Park radio in warm-start sleep (~500 nA) preserving regulator + TCXO + PA + RXGAIN registers */
    radio_ok = radio_ok &&
               ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_SET_SLEEP, &warm_sleep, 1U);

    return clkde_ok && smps_hw_ok && radio_ok;
}

bool ISAC_Is_SMPS_Active(void)
{
    /* Read live hardware status (PWR->CR5 SMPSEN + PWR->SR2 SMPSRDY) & radio USE_DCDC config */
    return g_subghz_dcdc_configured && ISAC_HAL_System_IsSMPSEnabled();
}

static uint32_t vrefint_raw16_to_vdda_100uv(uint16_t vrefint_cal, uint32_t vrefint_raw16)
{
    if (vrefint_raw16 == 0UL) {
        return 33000UL;
    }
    /* Exact 32-bit bandgap formula: 16 * 3000.0 mV * 10 (0.1 mV/mV) = 480,000 */
    return (480000UL * (uint32_t)vrefint_cal + (vrefint_raw16 >> 1U)) / vrefint_raw16;
}

/**
 * @brief Convert a 16x hardware-oversampled ADC count (0..65520) into ratiometric 0.1 mV
 *        units given live `vdda_100uv` (`33000` = `3300.0 mV`).
 */
static uint32_t adc_raw16_to_100uv(uint32_t ch_raw16, uint32_t vdda_100uv)
{
    if (ch_raw16 > 65520UL) {
        ch_raw16 = 65520UL;
    }
    return (ch_raw16 * vdda_100uv + 32760UL) / 65520UL;
}

/**
 * @brief Passively measure `VBAT` (`PB4/ADC_IN3` via `PA9`/`Q2` `BAT_MON_EN`) and `VDDA` (`VREFINT`)
 *        WITHOUT asserting `PA8` (`DET_EN` -> `0 mA` `LT5538` draw!) or waking the Sub-GHz transceiver (`HIGH-04`).
 */
bool ISAC_Acquire_Supply_Rails(uint16_t *out_vbat_mv, uint16_t *out_vdda_mv)
{
    uint16_t vref_cal;
    uint32_t vref_raw16, bat_raw16, vdda_100uv, vbat_half_100uv;

    if ((out_vbat_mv == NULL) || (out_vdda_mv == NULL)) {
        return false;
    }

    ISAC_HAL_GPIO_SetBatMonEnable(true);
    ISAC_HAL_DelayUs(ISAC_RAIL_SENSE_SETTLE_US);

    ISAC_HAL_ADC_EnableAndCalibrate();
    vref_cal   = ISAC_HAL_ReadVrefintCal();
    vref_raw16 = ISAC_HAL_ADC_ReadOversampled16x(ISAC_ADC_CH_VREFINT);
    bat_raw16  = ISAC_HAL_ADC_ReadOversampled16x(ISAC_ADC_CH_BAT_SENSE);

    ISAC_HAL_GPIO_SetBatMonEnable(false);
    ISAC_HAL_ADC_Disable();

    if (vref_raw16 == 0UL) {
        *out_vdda_mv = 0U;
        *out_vbat_mv = 0U;
        return false;
    }

    vdda_100uv      = vrefint_raw16_to_vdda_100uv(vref_cal, vref_raw16);
    vbat_half_100uv = adc_raw16_to_100uv(bat_raw16, vdda_100uv);
    *out_vdda_mv    = (uint16_t)((vdda_100uv + 5UL) / 10UL);
    *out_vbat_mv    = (uint16_t)((2UL * vbat_half_100uv + 5UL) / 10UL);
    return true;
}

/**
 * @brief Execute deterministic 3-tone ISAC acquisition after STOP2 wakeup:
 *   a) Assert PA8 (`DET_EN = 1`, Q1 `VBAT -> 3V3_DET`) + PA9 (`BAT_MON_EN = 1`, Q2 divider), wait 3.0 ms (`BLK-06`).
 *   b) Calibrate 12-bit SAR ADC, sample 16x oversampled VREFINT + ADC_IN3 (`PB4`) -> `vbat_mv`, release PA9 (`Q2`).
 *   b2) Listen-Before-Sense (`LBS`): with CW TX OFF, sample `DET_ADC` to verify ambient antenna RF ingress
 *       <= 320 mV (~-72 dBm); back off 20 ms (`PA8 = 0`) up to 2 retries on burst interference (`0 ms` airtime).
 *   c) Configure RFO_LP to +4 dBm (`ISAC_SENSING_TX_DBM`, `MED-03`), step across 863.1, 866.5, 869.5 MHz,
 *      wait 550 us (>99.5% LPF settle), sample live CW-loaded `VREFINT` + `DET_ADC` per tone (`F-08`), and
 *      soft-ramp PA envelope down to -9 dBm (`40 us` ramp + `50 us` settle) before `SET_STANDBY(XOSC)`.
 *   c2) Post-sweep `LBS`: isolate RF switch, wait 650 us (`6.5 * tau_LPF`, 99.85% `C_LPF` decay), and verify
 *       ambient floor <= 320 mV to flag any mid-sweep RF packet collision (`lbs_jammed = true`).
 *   d) Restore +14 dBm (`ISAC_LORAWAN_TX_DBM`), de-assert PA8 (`DET_EN = 0`) & sleep radio + ADC.
 */
bool ISAC_Acquire_3Tone_Sweep(isac_raw_sweep_t *out_sweep)
{
    uint8_t stdby_xosc      = ISAC_SUBGHZ_STDBY_XOSC;
    uint8_t stdby_rc        = ISAC_SUBGHZ_STDBY_RC;
    uint8_t warm_sleep      = ISAC_SUBGHZ_SLEEP_WARM_START;
    uint8_t tx_prm_sense[2]  = { (uint8_t)ISAC_SENSING_TX_DBM, ISAC_SUBGHZ_RAMP_40_US };
    uint8_t tx_prm_quench[2] = { (uint8_t)((int8_t)ISAC_CW_QUENCH_DBM), ISAC_SUBGHZ_RAMP_40_US };
    uint8_t tx_prm_lora[2]   = { (uint8_t)ISAC_LORAWAN_TX_DBM, ISAC_SUBGHZ_RAMP_40_US };
    uint32_t vdda_100uv;
    uint32_t min_vdda_mv;
    uint32_t vbat_half_100uv;
    uint32_t lbs_raw16;
    uint32_t lbs_100uv;
    uint32_t lbs_try;
    uint32_t i;
    bool     radio_ok;

    if (out_sweep == NULL) {
        return false;
    }

    out_sweep->lbs_pre_mv  = 0U;
    out_sweep->lbs_post_mv = 0U;
    out_sweep->lbs_jammed  = false;

    /* (a) Assert PA8 (DET_EN = 1) + PA9 (BAT_MON_EN = 1) and wait 3.0 ms TPS22919DCKR + LT5538 settling */
    ISAC_HAL_RFSwitch_SetMode(ISAC_RFSW_OFF);
    ISAC_HAL_GPIO_SetDetEnable(true);
    ISAC_HAL_GPIO_SetBatMonEnable(true);
    ISAC_HAL_DelayUs(ISAC_WAKEUP_SETTLE_US);

    /* (b) Enable + linearity-calibrate 12-bit SAR ADC; sample VREFINT & BAT_SENSE (PB4 / ADC_IN3) */
    ISAC_HAL_ADC_EnableAndCalibrate();
    out_sweep->vrefint_cal   = ISAC_HAL_ReadVrefintCal();
    out_sweep->vrefint_raw16 = ISAC_HAL_ADC_ReadOversampled16x(ISAC_ADC_CH_VREFINT);
    out_sweep->bat_raw16     = ISAC_HAL_ADC_ReadOversampled16x(ISAC_ADC_CH_BAT_SENSE);
    ISAC_HAL_GPIO_SetBatMonEnable(false);

    vdda_100uv  = vrefint_raw16_to_vdda_100uv(out_sweep->vrefint_cal, out_sweep->vrefint_raw16);
    min_vdda_mv = (vdda_100uv + 5UL) / 10UL;

    /* R_B1 = 4.7k (0.1%), R_B2 = 4.7k (0.1%) -> VBAT = 2.000 * V(PB4) */
    vbat_half_100uv    = adc_raw16_to_100uv(out_sweep->bat_raw16, vdda_100uv);
    out_sweep->vbat_mv = (uint16_t)((2UL * vbat_half_100uv + 5UL) / 10UL);

    /* MED-02: Sample internal MCU die temperature sensor BEFORE CW PA emission (0 us RF airtime!) */
    out_sweep->die_temp_degc_x10 = ISAC_HAL_ADC_ReadDieTempDegCx10((uint16_t)min_vdda_mv);

    /* Read live SMPS ready status while MCU is active in Run mode */
    out_sweep->smps_dcdc_enabled = ISAC_Is_SMPS_Active();

    /* (b2) Listen-Before-Sense (LBS): Measure TX-off ambient antenna RF ingress via LT5538 (0 us RF airtime) */
    for (lbs_try = 0U; ; ++lbs_try) {
        lbs_raw16 = ISAC_HAL_ADC_ReadOversampled16x(ISAC_ADC_CH_DET_ADC);
        lbs_100uv = adc_raw16_to_100uv(lbs_raw16, vdda_100uv);
        out_sweep->lbs_pre_mv = (uint16_t)((lbs_100uv + 5UL) / 10UL);
        if (out_sweep->lbs_pre_mv <= ISAC_LBS_MAX_AMBIENT_MV) {
            break;
        }
        if (lbs_try >= ISAC_LBS_MAX_RETRIES) {
            out_sweep->lbs_jammed = true;
            out_sweep->vdda_mv    = (uint16_t)min_vdda_mv;
            for (i = 0U; i < ISAC_NUM_TONES; ++i) {
                out_sweep->vrefint_tone_raw16[i] = 0UL;
                out_sweep->vdda_tone_mv[i]       = 0U;
                out_sweep->det_raw16[i]          = 0UL;
                out_sweep->det_100uv[i]          = 0UL;
                out_sweep->det_mv[i]             = 0U;
                out_sweep->tone_cw_ms[i]         = 0U;
            }
            ISAC_HAL_GPIO_SetDetEnable(false);
            ISAC_HAL_ADC_Disable();
            return true;
        }
        /* Power-gate LT5538 + SAR ADC during 20 ms carrier-sense backoff to conserve battery */
        ISAC_HAL_GPIO_SetDetEnable(false);
        ISAC_HAL_ADC_Disable();
        ISAC_HAL_DelayMs(ISAC_LBS_BACKOFF_MS);
        ISAC_HAL_GPIO_SetDetEnable(true);
        ISAC_HAL_DelayUs(ISAC_WAKEUP_SETTLE_US);
        ISAC_HAL_ADC_EnableAndCalibrate();
        out_sweep->vrefint_raw16 = ISAC_HAL_ADC_ReadOversampled16x(ISAC_ADC_CH_VREFINT);
        vdda_100uv               = vrefint_raw16_to_vdda_100uv(out_sweep->vrefint_cal,
                                                               out_sweep->vrefint_raw16);
        if (((vdda_100uv + 5UL) / 10UL) < min_vdda_mv) {
            min_vdda_mv = (vdda_100uv + 5UL) / 10UL;
        }
    }

    /* (c) Step SX1262 RFO_LP (+4 dBm CW, `MED-03`) across f1=863.1, f2=866.5, f3=869.5 MHz */
    radio_ok = ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_SET_STANDBY, &stdby_xosc, 1U) &&
               ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_SET_TX_PARAMS, tx_prm_sense, 2U);
    if (radio_ok) {
        ISAC_HAL_RFSwitch_SetMode(ISAC_RFSW_TX_LP); /* PA0 = 0, PA1 = 1 -> Pin 37 RF_OUT */
    }

    for (i = 0U; i < ISAC_NUM_TONES; ++i) {
        uint32_t tone_vdda_100uv;
        uint32_t tone_vdda_mv;
        uint32_t t_cw_start_ms;
        uint32_t t_cw_elapsed_ms;

        out_sweep->tone_cw_ms[i] = 0U;
        if (!radio_ok) {
            out_sweep->vrefint_tone_raw16[i] = 0UL;
            out_sweep->vdda_tone_mv[i]       = 0U;
            out_sweep->det_raw16[i]          = 0UL;
            out_sweep->det_100uv[i]          = 0UL;
            out_sweep->det_mv[i]             = 0U;
            continue;
        }
        if (i > 0U) {
            /* Restore +4 dBm sensing PA target after prior tone's -9 dBm soft-quench */
            radio_ok = ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_SET_TX_PARAMS, tx_prm_sense, 2U);
        }
        radio_ok      = radio_ok && subghz_set_rf_frequency(k_sweep_freqs_hz[i]);
        t_cw_start_ms = ISAC_HAL_GetTickMs();
        radio_ok      = radio_ok &&
                        ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_SET_TX_CONTINUOUS_WAVE, NULL, 0U);
        if (!radio_ok) {
            out_sweep->vrefint_tone_raw16[i] = 0UL;
            out_sweep->vdda_tone_mv[i]       = 0U;
            out_sweep->det_raw16[i]          = 0UL;
            out_sweep->det_100uv[i]          = 0UL;
            out_sweep->det_mv[i]             = 0U;
            continue;
        }

        /* Wait 550 us = 5.5 * tau_LPF (99.59% > 99.5% video LPF settling; total CW = 1.22 ms/tone) */
        ISAC_HAL_DelayUs(ISAC_LPF_SETTLE_US);

        /* F-08 fix: Sample VREFINT while CW PA load is active right before DET_ADC */
        out_sweep->vrefint_tone_raw16[i] = ISAC_HAL_ADC_ReadOversampled16x(ISAC_ADC_CH_VREFINT);
        tone_vdda_100uv = vrefint_raw16_to_vdda_100uv(out_sweep->vrefint_cal,
                                                      out_sweep->vrefint_tone_raw16[i]);
        tone_vdda_mv = (tone_vdda_100uv + 5UL) / 10UL;
        out_sweep->vdda_tone_mv[i] = (uint16_t)tone_vdda_mv;
        if (tone_vdda_mv < min_vdda_mv) {
            min_vdda_mv = tone_vdda_mv;
        }

        out_sweep->det_raw16[i] = ISAC_HAL_ADC_ReadOversampled16x(ISAC_ADC_CH_DET_ADC);
        out_sweep->det_100uv[i] = adc_raw16_to_100uv(out_sweep->det_raw16[i], tone_vdda_100uv);
        out_sweep->det_mv[i]    = (uint16_t)((out_sweep->det_100uv[i] + 5UL) / 10UL);

        /* Soft-ramp CW carrier down to -9 dBm (40 us PA ramp + 50 us settle) before XOSC standby
         * to suppress hard-keyed ETSI EN 300 220-1 transient spectral splatter */
        radio_ok = ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_SET_TX_PARAMS, tx_prm_quench, 2U);
        if (radio_ok) {
            ISAC_HAL_DelayUs(ISAC_CW_QUENCH_SETTLE_US);
        }
        radio_ok = ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_SET_STANDBY, &stdby_xosc, 1U) && radio_ok;
        t_cw_elapsed_ms = ISAC_HAL_GetTickMs() - t_cw_start_ms;
        out_sweep->tone_cw_ms[i] = (uint16_t)((t_cw_elapsed_ms >= ISAC_TONE1_CW_AIRTIME_MS)
                                               ? t_cw_elapsed_ms
                                               : ISAC_TONE1_CW_AIRTIME_MS);
    }

    out_sweep->vdda_mv = (uint16_t)min_vdda_mv;

    /* (c2) Post-sweep LBS: Isolate RF switch, let C_LPF=100nF decay 650 us (6.5*tau = 99.85%),
     *      and sample TX-off ambient floor to detect any mid-sweep external RF burst collision */
    ISAC_HAL_RFSwitch_SetMode(ISAC_RFSW_OFF);
    if (radio_ok) {
        ISAC_HAL_DelayUs(ISAC_LBS_DISCHARGE_US);
        lbs_raw16 = ISAC_HAL_ADC_ReadOversampled16x(ISAC_ADC_CH_DET_ADC);
        lbs_100uv = adc_raw16_to_100uv(lbs_raw16, vdda_100uv);
        out_sweep->lbs_post_mv = (uint16_t)((lbs_100uv + 5UL) / 10UL);
        if (out_sweep->lbs_post_mv > ISAC_LBS_MAX_AMBIENT_MV) {
            out_sweep->lbs_jammed = true;
        }
    } else {
        /* Force deterministic FAULT classification if SUBGHZSPI / RFBUSYS timed out mid-sweep */
        for (i = 0U; i < ISAC_NUM_TONES; ++i) {
            out_sweep->det_raw16[i] = 0UL;
            out_sweep->det_100uv[i] = 0UL;
            out_sweep->det_mv[i]    = 0U;
        }
    }

    /* (d) Restore +14 dBm LoRaWAN TX power, de-assert PA8/PA9, isolate RF switch & sleep ADC + radio */
    ISAC_HAL_GPIO_SetDetEnable(false);
    ISAC_HAL_GPIO_SetBatMonEnable(false);
    ISAC_HAL_ADC_Disable();
    radio_ok = ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_SET_TX_PARAMS, tx_prm_lora, 2U) && radio_ok;
    radio_ok = ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_SET_STANDBY, &stdby_rc, 1U) && radio_ok;
    radio_ok = ISAC_HAL_SubGhz_WriteCmd(ISAC_SUBGHZ_CMD_SET_SLEEP, &warm_sleep, 1U) && radio_ok;

    return radio_ok;
}

/**
 * @brief Piecewise-linear superstrate permittivity lookup along the Rev E.5 Full-Wave 3D-FDTD
 *        + Distributed Bridge + Elliptic Harmonic Pi-Network + ADI LT5538 Z_in curve (`t_ASA = 0.80 mm`).
 */
static uint16_t estimate_loaded_eps_x100(int32_t tilt_x100)
{
    /* HIGH-FW-05 fix: Strictly monotonic 868 MHz Debye real permittivity knots (tilt_db_x100 -> eps_r' * 100)
     * from Full-Wave 3D-FDTD `design_values.json` (Dry Air -344 -> 100, PTFE/Oil -123 -> 210,
     * Glaze Ice -1 -> 320, IPA @ 868 MHz +145 -> 629, Alumina Al2O3 +156 -> 980; Water Film = 7990 via state): */
    static const int16_t  k_tilt[5] = { -344, -123,   -1,  145,  156 };
    static const uint16_t k_eps[5]  = { 100U, 210U, 320U, 629U, 980U };
    uint32_t k;

    if (tilt_x100 <= (int32_t)k_tilt[0]) {
        return k_eps[0];
    }
    for (k = 0U; k < 4U; ++k) {
        const int32_t t0 = (int32_t)k_tilt[k];
        const int32_t t1 = (int32_t)k_tilt[k + 1U];
        if (tilt_x100 <= t1) {
            const int32_t de = (int32_t)k_eps[k + 1U] - (int32_t)k_eps[k];
            const int32_t dt = t1 - t0;
            return (uint16_t)((int32_t)k_eps[k] + round_div_s32((tilt_x100 - t0) * de, dt));
        }
    }
    return k_eps[4];
}

/**
 * @brief Apply bidirectional per-unit factory dry-air leakage power tare (`BLK-02`),
 *        2-point factory Al2O3/load gain+intercept calibration (`HIGH-02`),
 *        LT5538 intercept temperature drift compensation & physical freezing-point gate (`MED-02`),
 *        and compute Tilt, Notch, Level, Permittivity & Medium Class.
 */
void ISAC_Extract_Features_And_Classify_WithTemp(const isac_raw_sweep_t *sweep,
                                                 int16_t temp_degc_x10,
                                                 isac_telemetry_t *out_tel)
{
    int32_t  v_u100[ISAC_NUM_TONES];
    int32_t  p1_x100, p2_x100, p3_x100;
    int32_t  tilt_x100, notch_x100, temp_intercept_cdb = 0;
    uint32_t max_ddry_mv = 0U;
    bool     apply_dry_tare = false;
    uint32_t i;

    if ((sweep == NULL) || (out_tel == NULL)) {
        return;
    }

    if (g_cal_dry_valid) {
        for (i = 0U; i < ISAC_NUM_TONES; ++i) {
            const uint32_t d_mv = (sweep->det_mv[i] >= g_cal_dry_mv[i])
                                ? (uint32_t)(sweep->det_mv[i] - g_cal_dry_mv[i])
                                : (uint32_t)(g_cal_dry_mv[i] - sweep->det_mv[i]);
            if (d_mv > max_ddry_mv) {
                max_ddry_mv = d_mv;
            }
        }
        /* Apply scalar dry-air leakage tare strictly near the unit's own dry-air floor (<= 25 mV);
         * at high reflection (|Gamma| ~ 0.7, +250..+450 mV above dry air), bridge directivity E_D
         * combines vectorially rather than incoherently in power (`HIGH-02`). */
        apply_dry_tare = (max_ddry_mv <= 25U);
    }

    for (i = 0U; i < ISAC_NUM_TONES; ++i) {
        v_u100[i] = (int32_t)sweep->det_100uv[i];
        if (apply_dry_tare) {
            const int32_t cal_u100 = (int32_t)g_cal_dry_mv[i] * 10;
            int32_t       cal_db   = round_div_s32((cal_u100 - k_nom_dry_u100[i]) * 10, 19);
            int32_t       dp_tare_q12, meas_db, p_meas_q12, p_corr_q12, corr_db;

            /* Clamp tare excursion to [-8.00 dB .. +26.00 dB] around nominal dry air (`BLK-02`) */
            if (cal_db < -800) {
                cal_db = -800;
            } else if (cal_db > 2600) {
                cal_db = 2600;
            }
            dp_tare_q12 = (int32_t)pow10_db_q12(cal_db) - 4096;
            if (dp_tare_q12 != 0) {
                meas_db    = round_div_s32((v_u100[i] - k_nom_dry_u100[i]) * 10, 19);
                p_meas_q12 = (int32_t)pow10_db_q12(meas_db);
                p_corr_q12 = p_meas_q12 - dp_tare_q12;
                if (p_corr_q12 < 1029) {
                    p_corr_q12 = 1029; /* -6.00 dB floor below nominal dry air */
                }
                corr_db   = log10_q12_to_db_x100((uint32_t)p_corr_q12);
                v_u100[i] = k_nom_dry_u100[i] + round_div_s32(corr_db * 19, 10);
            }
        }
    }

    /* 1. Drift-canceled log-slope Tilt = (V(f1) - V(f3)) / (19.0 mV/dB) [0.01 dB] */
    tilt_x100 = round_div_s32((v_u100[0] - v_u100[2]) * 10, 19);

    /* 2. Drift-canceled in-band resonance Notch = ((V(f1) + V(f3))/2 - V(f2)) / (19.0 mV/dB) */
    notch_x100 = round_div_s32((v_u100[0] + v_u100[2] - (2 * v_u100[1])) * 5, 19);

    /* 3. Per-tone & mean reflected power Level [0.01 dBm] with combined SX1262 RFO_LP + ADI LT5538
     *    chain thermal slope trim (0.015 dB/C; ADI LT5538 Rev A native log drift is < +/-0.5 dB over -40..+85 C) */
    if (temp_degc_x10 != (int16_t)ISAC_TEMP_UNAVAILABLE) {
        temp_intercept_cdb = -round_div_s32(((int32_t)temp_degc_x10 - 250) * 15, 100);
    }
    p1_x100 = round_div_s32(v_u100[0] * 10, 19) + (int32_t)ISAC_LT5538_INTERCEPT_DBM_X100 + temp_intercept_cdb;
    p2_x100 = round_div_s32(v_u100[1] * 10, 19) + (int32_t)ISAC_LT5538_INTERCEPT_DBM_X100 + temp_intercept_cdb;
    p3_x100 = round_div_s32(v_u100[2] * 10, 19) + (int32_t)ISAC_LT5538_INTERCEPT_DBM_X100 + temp_intercept_cdb;

    out_tel->tilt_db_x100   = (int16_t)tilt_x100;
    out_tel->notch_db_x100  = (int16_t)notch_x100;
    out_tel->level_dbm_x100 = (int16_t)round_div_s32(p1_x100 + p2_x100 + p3_x100, 3);
    out_tel->vbat_mv        = sweep->vbat_mv;
    out_tel->vdda_mv        = sweep->vdda_mv;
    out_tel->smps_dcdc_ok   = sweep->smps_dcdc_enabled;

    /* 4. Diagnostic sanity check (rail droop, open bridge, or LBS RF jammer) & dual-regime classifier (`HIGH-02`) */
    if (sweep->lbs_jammed || (sweep->vdda_mv < 2400U) || (sweep->det_mv[0] < 80U)) {
        out_tel->state        = ISAC_SURFACE_FAULT;
        out_tel->eps_est_x100 = 0U;
        return;
    }

    if (g_cal_ref_valid) {
        /* Production 2-point calibrated 2D (Level_cal, Tilt, DryDelta) classifier:
         * Cancels LT5538 +/-2 dB intercept + SX1262 PA tolerance via Point-2 Al2O3 ceramic reference,
         * achieving 1.38 dB median / 0.65 dB P01 (>= 0.50 dB) Water-vs-IPA separation & 99.45% 4-hazard yield! */
        const int32_t level_cal_x100 = (int32_t)out_tel->level_dbm_x100 - (int32_t)g_cal_ref_cdb;
        const bool    is_dry = g_cal_dry_valid ? (max_ddry_mv <= 15U) : (notch_x100 >= 220);

        if (is_dry) {
            out_tel->state        = ISAC_SURFACE_DRY_AIR;
            out_tel->eps_est_x100 = 100U;
        } else if (level_cal_x100 < -3115) {
            out_tel->state        = ISAC_SURFACE_OIL;
            out_tel->eps_est_x100 = estimate_loaded_eps_x100(tilt_x100);
        } else if (tilt_x100 <= 84) {
            if ((temp_degc_x10 != (int16_t)ISAC_TEMP_UNAVAILABLE) &&
                (temp_degc_x10 > (int16_t)ISAC_ICE_MAX_TEMP_DEGC_X10)) {
                out_tel->state        = ISAC_SURFACE_LIQUID_WATER;
                out_tel->eps_est_x100 = 7990U;
            } else {
                out_tel->state        = ISAC_SURFACE_GLAZE_ICE;
                out_tel->eps_est_x100 = estimate_loaded_eps_x100(tilt_x100);
            }
        } else if ((level_cal_x100 >= -2694) && (tilt_x100 <= 150)) {
            /* Water film (-26.35 dBm, +0.59 dB margin above -26.94 dBm) vs lossy IPA (-27.75 dBm, +0.81 dB margin) */
            out_tel->state        = ISAC_SURFACE_LIQUID_WATER;
            out_tel->eps_est_x100 = 7990U;
        } else {
            out_tel->state        = ISAC_SURFACE_IPA;
            out_tel->eps_est_x100 = estimate_loaded_eps_x100(tilt_x100);
        }
    } else {
        /* Uncalibrated bench fallback: 100% intercept-invariant differential (Notch, Tilt) classifier */
        if (notch_x100 >= 220) {
            out_tel->state        = ISAC_SURFACE_DRY_AIR;
            out_tel->eps_est_x100 = 100U;
        } else if (tilt_x100 <= -62) {
            out_tel->state        = ISAC_SURFACE_OIL;
            out_tel->eps_est_x100 = estimate_loaded_eps_x100(tilt_x100);
        } else if (tilt_x100 <= 61) {
            if ((temp_degc_x10 != (int16_t)ISAC_TEMP_UNAVAILABLE) &&
                (temp_degc_x10 > (int16_t)ISAC_ICE_MAX_TEMP_DEGC_X10)) {
                out_tel->state        = ISAC_SURFACE_LIQUID_WATER;
                out_tel->eps_est_x100 = 7990U;
            } else {
                out_tel->state        = ISAC_SURFACE_GLAZE_ICE;
                out_tel->eps_est_x100 = estimate_loaded_eps_x100(tilt_x100);
            }
        } else if (tilt_x100 <= 134) {
            out_tel->state        = ISAC_SURFACE_LIQUID_WATER;
            out_tel->eps_est_x100 = 7990U;
        } else {
            out_tel->state        = ISAC_SURFACE_IPA;
            out_tel->eps_est_x100 = estimate_loaded_eps_x100(tilt_x100);
        }
    }
}

void ISAC_Extract_Features_And_Classify(const isac_raw_sweep_t *sweep,
                                        isac_telemetry_t *out_tel)
{
    ISAC_Extract_Features_And_Classify_WithTemp(sweep, (int16_t)ISAC_TEMP_UNAVAILABLE, out_tel);
}

uint8_t ISAC_Select_Uplink_SF(isac_surface_state_t state,
                              isac_duty_tracker_t *dc,
                              uint32_t now_ms,
                              uint32_t extra_1pct_ms)
{
    /* Rev E.5 adaptive SF link-budget parity (`docs/rf_link_budget.md`):
     *   - DRY_AIR / OIL  -> SF7BW125 (DR5, 62 ms ToA, +15.0 dB margin)
     *   - GLAZE_ICE      -> SF9BW125 (DR3, 206 ms ToA, +15.1 dB margin, saves 86% TX energy vs SF12)
     *   - WATER/IPA/FAULT-> SF12BW125 (DR0, 1,483 ms ToA, +15.0 dB wet-radome margin; SF10/SF7 duty fallback) */
    if ((state == ISAC_SURFACE_DRY_AIR) || (state == ISAC_SURFACE_OIL)) {
        return 7U;
    }
    if (state == ISAC_SURFACE_GLAZE_ICE) {
        if ((dc == NULL) || ISAC_DutyCycle_CanTransmit(dc, extra_1pct_ms + 206UL, now_ms)) {
            return 9U;
        }
        return 7U;
    }
    if ((dc == NULL) || ISAC_DutyCycle_CanTransmit(dc, extra_1pct_ms + 1483UL, now_ms)) {
        return 12U;
    }
    if (ISAC_DutyCycle_CanTransmit(dc, extra_1pct_ms + 371UL, now_ms)) {
        return 10U;
    }
    return 7U;
}

/**
 * @brief Serialize telemetry into the 10-byte big-endian LoRaWAN FPort 10 wire contract:
 *   Byte 0    : [7]=RevE1(1), [6]=DutyThrottled, [5]=LowBat, [4]=SMPS_DCDC, [3:0]=SurfaceState
 *   Bytes 1..2: int16_t  tilt_db_x100   (Big-Endian, 0.01 dB)
 *   Bytes 3..4: int16_t  level_dbm_x100 (Big-Endian, 0.01 dBm)
 *   Bytes 5..6: uint16_t eps_est_x100   (Big-Endian, eps_r' * 100)
 *   Bytes 7..8: uint16_t vbat_mv        (Big-Endian, mV)
 *   Byte 9    : int8_t   notch_db_x10   (Signed 0.1 dB clamped [-128..+127])
 */
void ISAC_Pack_LoRaWAN_FPort10(const isac_telemetry_t *tel,
                               const isac_duty_tracker_t *dc,
                               uint8_t payload[ISAC_FPORT10_PAYLOAD_LEN])
{
    uint8_t flags;
    uint16_t u_tilt, u_lvl;
    int32_t notch_x10;

    if ((tel == NULL) || (payload == NULL)) {
        return;
    }

    flags = ISAC_FLAG_REV_E1_FRAME | ((uint8_t)tel->state & ISAC_FLAG_STATE_MASK);
    if (tel->smps_dcdc_ok) {
        flags |= ISAC_FLAG_SMPS_DCDC_ACTIVE;
    }
    if (tel->vbat_mv < ISAC_VBAT_LOW_WARN_MV) {
        flags |= ISAC_FLAG_LOW_BATTERY;
    }
    if ((dc != NULL) && dc->throttled) {
        flags |= ISAC_FLAG_DUTY_THROTTLED;
    }

    u_tilt = (uint16_t)tel->tilt_db_x100;
    u_lvl  = (uint16_t)tel->level_dbm_x100;

    notch_x10 = round_div_s32((int32_t)tel->notch_db_x100, 10);
    if (notch_x10 > 127) {
        notch_x10 = 127;
    } else if (notch_x10 < -128) {
        notch_x10 = -128;
    }

    payload[0] = flags;
    payload[1] = (uint8_t)((u_tilt >> 8) & 0xFFU);
    payload[2] = (uint8_t)(u_tilt        & 0xFFU);
    payload[3] = (uint8_t)((u_lvl >> 8)  & 0xFFU);
    payload[4] = (uint8_t)(u_lvl         & 0xFFU);
    payload[5] = (uint8_t)((tel->eps_est_x100 >> 8) & 0xFFU);
    payload[6] = (uint8_t)(tel->eps_est_x100        & 0xFFU);
    payload[7] = (uint8_t)((tel->vbat_mv >> 8) & 0xFFU);
    payload[8] = (uint8_t)(tel->vbat_mv        & 0xFFU);
    payload[9] = (uint8_t)((int8_t)notch_x10);
}

void ISAC_Unpack_LoRaWAN_FPort10(const uint8_t payload[ISAC_FPORT10_PAYLOAD_LEN],
                                 isac_telemetry_t *out_tel,
                                 uint8_t *out_flags)
{
    uint16_t u_tilt, u_lvl;

    if ((payload == NULL) || (out_tel == NULL)) {
        return;
    }
    if (out_flags != NULL) {
        *out_flags = payload[0];
    }

    u_tilt = (uint16_t)(((uint16_t)payload[1] << 8) | (uint16_t)payload[2]);
    u_lvl  = (uint16_t)(((uint16_t)payload[3] << 8) | (uint16_t)payload[4]);

    out_tel->state          = (isac_surface_state_t)(payload[0] & ISAC_FLAG_STATE_MASK);
    out_tel->smps_dcdc_ok   = ((payload[0] & ISAC_FLAG_SMPS_DCDC_ACTIVE) != 0U);
    out_tel->tilt_db_x100   = (int16_t)u_tilt;
    out_tel->level_dbm_x100 = (int16_t)u_lvl;
    out_tel->eps_est_x100   = (uint16_t)(((uint16_t)payload[5] << 8) | (uint16_t)payload[6]);
    out_tel->vbat_mv        = (uint16_t)(((uint16_t)payload[7] << 8) | (uint16_t)payload[8]);
    out_tel->vdda_mv        = 0U;
    out_tel->notch_db_x100  = (int16_t)((int16_t)((int8_t)payload[9]) * 10);
}

/* =========================================================================
 * ETSI EN 300 220-1 / ERC/REC 70-03 Sub-GHz Duty-Cycle Trackers (`BLK-05`, `HIGH-07`)
 *   - 1.0% (36,000 ms/hr, 100x backoff) for 865-868.6 MHz (Tone 2 & EU868 uplinks)
 *   - 0.1% ( 3,600 ms/hr, 1000x backoff) for 863-865 MHz h1.3 (Tone 1 = 863.1 MHz)
 * ========================================================================= */
void ISAC_DutyCycle_Init(isac_duty_tracker_t *dc, uint32_t now_ms)
{
    if (dc == NULL) {
        return;
    }
    dc->window_start_ms     = now_ms;
    dc->used_airtime_ms     = 0UL;
    dc->last_tx_end_ms      = now_ms;
    dc->min_next_tx_ms      = now_ms;
    dc->used_subband_0p1_ms = 0UL;
    dc->min_next_0p1_tx_ms  = now_ms;
    dc->throttled           = false;
}

static void duty_roll_window_if_expired(isac_duty_tracker_t *dc, uint32_t now_ms)
{
    /* BLK-FW-01 fix: Wrap-safe signed modular check + immediate deadline latching once expired
     * prevents both 49.71-day (2^32 ms) unsigned blackout and 24.85-day (2^31 ms) idle sign flip. */
    if ((int32_t)(now_ms - dc->min_next_tx_ms) >= 0) {
        dc->min_next_tx_ms = now_ms;
    }
    if ((int32_t)(now_ms - dc->min_next_0p1_tx_ms) >= 0) {
        dc->min_next_0p1_tx_ms = now_ms;
    }
    if ((now_ms - dc->window_start_ms) >= ISAC_ETSI_WINDOW_MS) {
        dc->window_start_ms     = now_ms;
        dc->used_airtime_ms     = 0UL;
        dc->used_subband_0p1_ms = 0UL;
    }
}

void ISAC_DutyCycle_Tick(isac_duty_tracker_t *dc, uint32_t now_ms)
{
    if (dc == NULL) {
        return;
    }
    duty_roll_window_if_expired(dc, now_ms);
}

uint32_t ISAC_DutyCycle_MinBackoffMs(uint32_t airtime_ms)
{
    /* <= 1% duty cycle requires T_off >= 99 * T_on -> T_period >= 100 * T_on */
    return airtime_ms * ISAC_ETSI_DUTY_DENOM_1PCT;
}

bool ISAC_DutyCycle_CanTransmit(isac_duty_tracker_t *dc, uint32_t planned_airtime_ms, uint32_t now_ms)
{
    if (dc == NULL) {
        return false;
    }
    duty_roll_window_if_expired(dc, now_ms);
    if ((int32_t)(now_ms - dc->min_next_tx_ms) < 0) {
        dc->throttled = true;
        return false;
    }
    if ((dc->used_airtime_ms + planned_airtime_ms) > ISAC_ETSI_MAX_AIRTIME_1PCT_MS) {
        dc->throttled = true;
        return false;
    }
    dc->throttled = false;
    return true;
}

bool ISAC_DutyCycle_CanTransmitSubband0p1(isac_duty_tracker_t *dc, uint32_t planned_0p1_ms, uint32_t now_ms)
{
    if (dc == NULL) {
        return false;
    }
    duty_roll_window_if_expired(dc, now_ms);
    if ((int32_t)(now_ms - dc->min_next_0p1_tx_ms) < 0) {
        dc->throttled = true;
        return false;
    }
    if ((dc->used_subband_0p1_ms + planned_0p1_ms) > ISAC_ETSI_MAX_AIRTIME_0P1PCT_MS) {
        dc->throttled = true;
        return false;
    }
    return true;
}

void ISAC_DutyCycle_RecordAirTime(isac_duty_tracker_t *dc, uint32_t airtime_ms, uint32_t now_ms)
{
    if (dc == NULL) {
        return;
    }
    duty_roll_window_if_expired(dc, now_ms);
    dc->used_airtime_ms += airtime_ms;
    dc->last_tx_end_ms   = now_ms + airtime_ms;
    dc->min_next_tx_ms   = now_ms + ISAC_DutyCycle_MinBackoffMs(airtime_ms);
}

void ISAC_DutyCycle_RecordSubband0p1AirTime(isac_duty_tracker_t *dc, uint32_t airtime_0p1_ms, uint32_t now_ms)
{
    if (dc == NULL) {
        return;
    }
    duty_roll_window_if_expired(dc, now_ms);
    dc->used_subband_0p1_ms += airtime_0p1_ms;
    dc->min_next_0p1_tx_ms   = now_ms + (airtime_0p1_ms * ISAC_ETSI_DUTY_DENOM_0P1PCT);
}
