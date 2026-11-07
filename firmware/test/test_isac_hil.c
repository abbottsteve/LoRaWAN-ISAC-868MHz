/**
 * @file test_isac_hil.c
 * @brief Deterministic Host Hardware-in-the-Loop (HIL) Unit-Test Suite for Rev E.1 Firmware
 *
 * Validates `isac_sensing.c`, `isac_lorawan_eu868.c`, and `isac_board_pins.h` against
 * `analysis/results/design_values.json`, NIST FIPS-197, RFC 4493, and LoRaWAN 1.0.3:
 *   1. Schematic Pin Parity (`PA0/PA1` RF switch, `PB0/DIO3` 32 MHz TCXO, `ADC_IN13` VREFINT,
 *      `CKMODE=PCLK/2`), 15 uH `USE_DCDC` SMPS Sequence & Gated `PA8` (`DET_EN`) Timing
 *   2. Exact `VREFINT` Supply-Droop Immunity (`VDDA = 3.00 V` vs `3.30 V` -> `0 mV` error)
 *   3. Exact PA / Temperature Common-Mode Drift Cancellation (`+/- 2.0 dB` -> `0.00 dB` Tilt error)
 *   4. `100%` Surface Medium Classification Accuracy (`Dry Air`, `Oil`, `Glaze Ice`, `IPA`,
 *      `Liquid Water`) + Byte-Exact 10-Byte `FPort 10` Serialization & ETSI `<= 1%` Duty Cycle
 *   5. NIST FIPS-197 AES-128, RFC 4493 CMAC, LoRaWAN 1.0.3 OTAA Join + Encrypted Class A
 *      `FPort 10` Uplink + `RX1 (+1.0 s)` / `RX2 (+2.0 s, 869.525 MHz)` State Machine.
 */
#include "isac_board_pins.h"
#include "isac_hal.h"
#include "isac_lorawan_eu868.h"
#include "isac_nvm.h"
#include "isac_sensing.h"

#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* =========================================================================
 * 1. Deterministic Host HIL Mock of STM32WLE5JC + SX1262 + LT5538 + SAR ADC
 * ========================================================================= */
#define MAX_CMD_LOG  512U

typedef struct {
    uint8_t opcode;
    uint8_t params[8];
    uint8_t len;
} hil_subghz_cmd_t;

typedef struct {
    /* Simulated physical analog environment */
    uint32_t vdda_true_100uv;             /* e.g. 33000 (3.3000 V) or 30000 (3.0000 V) */
    uint32_t vdda_tone_override_100uv[ISAC_NUM_TONES]; /* Optional per-tone CW droop override */
    uint32_t vbat_true_mv;                /* e.g. 3600 mV (1S LiPo nominal)            */
    uint16_t vrefint_cal;                 /* Factory OTP @ 3000 mV: 1650 (~1.2088 V)   */
    uint32_t tone_vout_100uv[ISAC_NUM_TONES]; /* LT5538 video LPF output @ f1, f2, f3  */
    uint32_t ambient_pre_100uv;           /* TX-off ambient LT5538 floor pre-sweep (0 -> 1400 = 140.0 mV) */
    uint32_t ambient_post_100uv;          /* TX-off ambient LT5538 floor post-sweep (0 -> 1400 = 140.0 mV)*/
    uint32_t jammer_pre_bursts_remaining; /* Transient pre-sweep jammer bursts before clearing to 140 mV  */
    uint32_t lbs_tx_off_samples;          /* Number of TX-off LBS ADC reads observed                      */
    uint32_t cw_soft_quench_count;        /* Number of -9 dBm >=50 us soft-ramp quenches before STDBY     */
    uint32_t delay_since_quench_us;       /* Settling time after -9 dBm soft-ramp before SET_STANDBY      */
    uint32_t delay_since_cw_off_us;       /* C_LPF discharge time after f3 CW quench                      */

    /* Observed hardware state & protocol trace */
    bool     gpio_inited;
    bool     det_en_high;
    bool     det_en_turned_on;
    bool     bat_mon_en_high;
    bool     adc_enabled;
    bool     smps_hw_cr5_enabled;
    bool     smps_sr2_ready;
    bool     inject_smps_fault;
    bool     inject_rfbusy_timeout;
    bool     rtc_inited;
    uint32_t rtc_period_s;
    bool     subghz_reset_called;
    bool     cw_active;
    uint32_t cw_trigger_count;
    int8_t   last_tx_power_dbm;
    int8_t   cw_tx_power_dbm[ISAC_NUM_TONES];
    isac_rf_switch_mode_t rf_sw_mode;

    uint32_t sim_tick_ms;
    uint32_t tx_done_at_ms;
    bool     tx_in_flight;
    bool     rx_in_flight;
    bool     rx_pkt_in_flight;
    bool     stop_rx_timer_on_preamble;
    uint32_t last_rx_search_timeout_ms;
    uint32_t staged_rx_toa_ms;
    uint32_t rx_done_at_ms;
    uint32_t rx_timeout_at_ms;
    uint16_t irq_status;
    uint8_t  tx_fifo[256];
    uint8_t  last_tx_len;
    uint32_t last_tx_freq_hz;
    uint8_t  rx_fifo[256];
    uint8_t  staged_rx_len;
    bool     stage_rx_on_rx2;
    uint32_t rx_window_count;
    uint32_t rx_window_freqs_hz[4];
    uint32_t rx_window_open_ms[4];
    bool     rfsw_rx_during_rx[4];
    uint8_t  sync_word[2];
    uint8_t  smpsc0r_reg;
    uint8_t  iq_polarity_reg;
    uint8_t  tx_mod_reg;
    uint8_t  rx_gain_reg;
    uint8_t  tx_clamp_reg;
    bool     saw_iq_std_on_ul;
    bool     saw_iq_inv_on_dl;
    bool     clkde_set_before_smpsen;
    bool     inject_clkde_readback_zero;
    bool     radio_sleeping;
    uint32_t wakeup_nss_pulses;
    bool     woke_before_post_sleep_spi;
    int16_t  mock_die_temp_degc_x10;

    uint32_t current_rf_freq_hz;
    uint32_t current_tone_idx;
    uint32_t delay_since_det_en_us;
    uint32_t delay_since_bat_mon_en_us;
    uint32_t delay_since_cw_on_us;

    /* Assertions captured at the exact instant of ADC conversion */
    bool     det_en_was_high_at_adc;
    bool     bat_mon_en_was_high_at_adc;
    bool     wakeup_settled_at_bat_adc;
    bool     lpf_settled_at_det_adc[ISAC_NUM_TONES];
    bool     rfsw_tx_lp_at_det_adc[ISAC_NUM_TONES];
    uint32_t captured_freq_hz[ISAC_NUM_TONES];

    hil_subghz_cmd_t cmd_log[MAX_CMD_LOG];
    uint32_t         cmd_count;
} hil_mock_state_t;

static hil_mock_state_t g_hil;

static void hil_reset_trace(void)
{
    g_hil.det_en_was_high_at_adc     = true;
    g_hil.det_en_turned_on           = false;
    g_hil.bat_mon_en_was_high_at_adc = false;
    g_hil.wakeup_settled_at_bat_adc  = false;
    for (uint32_t i = 0U; i < ISAC_NUM_TONES; ++i) {
        g_hil.lpf_settled_at_det_adc[i] = false;
        g_hil.rfsw_tx_lp_at_det_adc[i]  = false;
        g_hil.captured_freq_hz[i]       = 0UL;
        g_hil.cw_tx_power_dbm[i]        = 0;
    }
    g_hil.cmd_count            = 0U;
    g_hil.cw_trigger_count     = 0U;
    g_hil.lbs_tx_off_samples   = 0U;
    g_hil.cw_soft_quench_count = 0U;
    g_hil.rx_window_count      = 0U;
    g_hil.irq_status       = 0U;
    g_hil.tx_in_flight     = false;
    g_hil.rx_in_flight     = false;
    g_hil.rx_pkt_in_flight = false;
}

void ISAC_HAL_GPIO_InitBoardPins(void)
{
    g_hil.gpio_inited = true;
}

void ISAC_HAL_UART2_InitDiagnostic(void) {}
void ISAC_HAL_Watchdog_Kick(void) {}

void ISAC_HAL_GPIO_SetDetEnable(bool enable)
{
    g_hil.det_en_high = enable;
    if (enable) {
        g_hil.det_en_turned_on      = true;
        g_hil.delay_since_det_en_us = 0UL;
    }
}

void ISAC_HAL_GPIO_SetBatMonEnable(bool enable)
{
    g_hil.bat_mon_en_high = enable;
    if (enable) {
        g_hil.delay_since_bat_mon_en_us = 0UL;
    }
}

void ISAC_HAL_RFSwitch_SetMode(isac_rf_switch_mode_t mode)
{
    g_hil.rf_sw_mode = mode;
}

bool ISAC_HAL_System_EnableSMPS(void)
{
    g_hil.clkde_set_before_smpsen = ((g_hil.smpsc0r_reg & ISAC_SUBGHZ_SMPSC0R_CLKDE) != 0U);
    g_hil.smps_hw_cr5_enabled     = true;
    g_hil.smps_sr2_ready          = !g_hil.inject_smps_fault;
    return ISAC_HAL_System_IsSMPSEnabled();
}

bool ISAC_HAL_System_IsSMPSEnabled(void)
{
    return g_hil.smps_hw_cr5_enabled && g_hil.smps_sr2_ready;
}

void ISAC_HAL_RTC_InitWakeup(uint32_t period_s)
{
    g_hil.rtc_inited   = true;
    g_hil.rtc_period_s = period_s;
}

uint32_t ISAC_HAL_GetTickMs(void)
{
    return g_hil.sim_tick_ms;
}

void ISAC_HAL_DelayMs(uint32_t ms)
{
    g_hil.sim_tick_ms += ms;
    if (g_hil.tx_in_flight && (g_hil.sim_tick_ms >= g_hil.tx_done_at_ms)) {
        g_hil.tx_in_flight = false;
        g_hil.irq_status  |= ISAC_SUBGHZ_IRQ_TX_DONE;
    }
    if (g_hil.rx_pkt_in_flight) {
        /* If SetStopRxTimerOnPreamble(0x01) was NOT issued, SX1262 hardware RX timer still aborts mid-packet */
        if (!g_hil.stop_rx_timer_on_preamble && (g_hil.sim_tick_ms >= g_hil.rx_timeout_at_ms)) {
            g_hil.rx_pkt_in_flight = false;
            g_hil.irq_status      |= ISAC_SUBGHZ_IRQ_TIMEOUT;
        } else if (g_hil.sim_tick_ms >= g_hil.rx_done_at_ms) {
            g_hil.rx_pkt_in_flight = false;
            g_hil.irq_status      |= ISAC_SUBGHZ_IRQ_RX_DONE;
        }
    } else if (g_hil.rx_in_flight && (g_hil.sim_tick_ms >= g_hil.rx_timeout_at_ms)) {
        g_hil.rx_in_flight = false;
        g_hil.irq_status  |= ISAC_SUBGHZ_IRQ_TIMEOUT;
    }
}

bool ISAC_HAL_SubGhz_WakeupAndReset(void)
{
    if (g_hil.inject_rfbusy_timeout) {
        return false;
    }
    g_hil.subghz_reset_called = true;
    g_hil.radio_sleeping      = false;
    g_hil.iq_polarity_reg     = 0x0DU;
    g_hil.tx_clamp_reg        = 0x08U; /* SX1262 silicon POR value (bits [4:1] = 0b0100 before §15.2 fix) */
    return true;
}

bool ISAC_HAL_SubGhz_EnsureAwake(void)
{
    if (g_hil.inject_rfbusy_timeout) {
        return false;
    }
    if (g_hil.radio_sleeping) {
        g_hil.radio_sleeping = false;
        g_hil.wakeup_nss_pulses++;
        g_hil.woke_before_post_sleep_spi = true;
    }
    return true;
}

bool ISAC_HAL_SubGhz_WriteCmd(uint8_t opcode, const uint8_t *params, uint8_t len)
{
    if (!ISAC_HAL_SubGhz_EnsureAwake()) {
        return false;
    }
    if (g_hil.cmd_count < MAX_CMD_LOG) {
        hil_subghz_cmd_t *entry = &g_hil.cmd_log[g_hil.cmd_count++];
        entry->opcode = opcode;
        entry->len    = (len <= 8U) ? len : 8U;
        for (uint8_t i = 0U; i < entry->len; ++i) {
            entry->params[i] = (params != NULL) ? params[i] : 0U;
        }
    }

    if ((opcode == ISAC_SUBGHZ_CMD_SET_RF_FREQUENCY) && (params != NULL) && (len == 4U)) {
        const uint32_t pll = ((uint32_t)params[0] << 24) |
                             ((uint32_t)params[1] << 16) |
                             ((uint32_t)params[2] << 8)  |
                             (uint32_t)params[3];
        /* Invert rfFreq = round(freq_hz * 2^25 / 32e6) */
        const double f_hz = ((double)pll * 32000000.0) / 33554432.0;
        g_hil.current_rf_freq_hz = (uint32_t)llround(f_hz);
        if (labs((long)g_hil.current_rf_freq_hz - (long)ISAC_TONE1_FREQ_HZ) < 1000L) {
            g_hil.current_tone_idx = 0U;
        } else if (labs((long)g_hil.current_rf_freq_hz - (long)ISAC_TONE2_FREQ_HZ) < 1000L) {
            g_hil.current_tone_idx = 1U;
        } else {
            g_hil.current_tone_idx = 2U;
        }
    } else if ((opcode == ISAC_SUBGHZ_CMD_SET_TX_PARAMS) && (params != NULL) && (len >= 2U)) {
        g_hil.last_tx_power_dbm = (int8_t)params[0];
        if (g_hil.cw_active && (g_hil.last_tx_power_dbm == (int8_t)ISAC_CW_QUENCH_DBM)) {
            g_hil.delay_since_quench_us = 0UL;
        }
    } else if ((opcode == ISAC_SUBGHZ_CMD_SET_STOP_RX_TIMER_ON_PREAMBLE) && (params != NULL) && (len >= 1U)) {
        g_hil.stop_rx_timer_on_preamble = (params[0] != 0U);
    } else if ((opcode == ISAC_SUBGHZ_CMD_SET_PACKET_PARAMS) && (params != NULL) && (len == 6U)) {
        if (params[5] == 0x00U) { /* Uplink Standard IQ */
            g_hil.last_tx_len = params[3];
        }
    } else if (opcode == ISAC_SUBGHZ_CMD_CLEAR_IRQ_STATUS) {
        g_hil.irq_status = 0U;
    } else if (opcode == ISAC_SUBGHZ_CMD_SET_TX) {
        /* Simulate realistic 57 ms SF7BW125 Time-on-Air (> old broken 25 ms loop timeout) */
        g_hil.tx_in_flight    = true;
        g_hil.tx_done_at_ms   = g_hil.sim_tick_ms + 57UL;
        g_hil.last_tx_freq_hz = g_hil.current_rf_freq_hz;
    } else if (opcode == ISAC_SUBGHZ_CMD_SET_RX) {
        const uint32_t idx = g_hil.rx_window_count;
        uint32_t rx_ticks = 0UL;
        uint32_t rx_tmo_ms = 60UL;
        if ((params != NULL) && (len >= 3U)) {
            rx_ticks  = ((uint32_t)params[0] << 16U) | ((uint32_t)params[1] << 8U) | (uint32_t)params[2];
            rx_tmo_ms = (rx_ticks + 32UL) / 64UL;
        }
        g_hil.last_rx_search_timeout_ms = rx_tmo_ms;
        if (idx < 4U) {
            g_hil.rx_window_freqs_hz[idx] = g_hil.current_rf_freq_hz;
            g_hil.rx_window_open_ms[idx]  = g_hil.sim_tick_ms;
            g_hil.rfsw_rx_during_rx[idx]  = (g_hil.rf_sw_mode == ISAC_RFSW_RX);
        }
        g_hil.rx_window_count++;
        if ((g_hil.staged_rx_len > 0U) &&
            ((!g_hil.stage_rx_on_rx2 && (idx == 0U)) ||
             ( g_hil.stage_rx_on_rx2 && (idx == 1U)))) {
            g_hil.rx_timeout_at_ms = g_hil.sim_tick_ms + rx_tmo_ms;
            if (g_hil.staged_rx_toa_ms > 0UL) {
                g_hil.rx_in_flight     = false;
                g_hil.rx_pkt_in_flight = true;
                g_hil.rx_done_at_ms    = g_hil.sim_tick_ms + 15UL + g_hil.staged_rx_toa_ms;
            } else {
                g_hil.rx_in_flight     = false;
                g_hil.rx_pkt_in_flight = false;
                g_hil.irq_status      |= ISAC_SUBGHZ_IRQ_RX_DONE;
            }
        } else {
            g_hil.rx_pkt_in_flight = false;
            g_hil.rx_in_flight     = true;
            g_hil.rx_timeout_at_ms = g_hil.sim_tick_ms + 40UL;
        }
    } else if (opcode == ISAC_SUBGHZ_CMD_SET_TX_CONTINUOUS_WAVE) {
        g_hil.cw_active            = true;
        g_hil.cw_trigger_count++;
        g_hil.delay_since_cw_on_us = 0UL;
        if (g_hil.current_tone_idx < ISAC_NUM_TONES) {
            g_hil.cw_tx_power_dbm[g_hil.current_tone_idx] = g_hil.last_tx_power_dbm;
        }
    } else if ((opcode == ISAC_SUBGHZ_CMD_SET_STANDBY) ||
               (opcode == ISAC_SUBGHZ_CMD_SET_SLEEP)) {
        if (g_hil.cw_active) {
            if ((g_hil.last_tx_power_dbm == (int8_t)ISAC_CW_QUENCH_DBM) &&
                (g_hil.delay_since_quench_us >= ISAC_CW_QUENCH_SETTLE_US)) {
                g_hil.cw_soft_quench_count++;
            }
            g_hil.delay_since_cw_off_us = 0UL;
        }
        g_hil.cw_active = false;
        if (opcode == ISAC_SUBGHZ_CMD_SET_SLEEP) {
            g_hil.radio_sleeping = true;
        }
    }
    return true;
}

bool ISAC_HAL_SubGhz_ReadCmd(uint8_t opcode, uint8_t *rx_buf, uint8_t len)
{
    if (!ISAC_HAL_SubGhz_EnsureAwake()) {
        return false;
    }
    if ((rx_buf == NULL) || (len == 0U)) {
        return true;
    }
    memset(rx_buf, 0, len);
    if ((opcode == ISAC_SUBGHZ_CMD_GET_IRQ_STATUS) && (len >= 2U)) {
        rx_buf[0] = (uint8_t)((g_hil.irq_status >> 8U) & 0xFFU);
        rx_buf[1] = (uint8_t)( g_hil.irq_status        & 0xFFU);
    } else if ((opcode == ISAC_SUBGHZ_CMD_GET_RX_BUFFER_STATUS) && (len >= 2U)) {
        rx_buf[0] = g_hil.staged_rx_len;
        rx_buf[1] = 0x80U;
    }
    return true;
}

bool ISAC_HAL_SubGhz_WriteReg(uint16_t addr, const uint8_t *data, uint8_t len)
{
    if (!ISAC_HAL_SubGhz_EnsureAwake()) {
        return false;
    }
    if ((addr == ISAC_SUBGHZ_REG_LORA_SYNC_MSB) && (data != NULL) && (len >= 2U)) {
        g_hil.sync_word[0] = data[0];
        g_hil.sync_word[1] = data[1];
    } else if ((addr == ISAC_SUBGHZ_REG_SMPSC0R) && (data != NULL) && (len >= 1U)) {
        g_hil.smpsc0r_reg = data[0];
    } else if ((addr == ISAC_SUBGHZ_REG_IQ_POLARITY) && (data != NULL) && (len >= 1U)) {
        g_hil.iq_polarity_reg = data[0];
        if ((data[0] & (1U << 2)) != 0U) {
            g_hil.saw_iq_std_on_ul = true;
        } else {
            g_hil.saw_iq_inv_on_dl = true;
        }
    } else if ((addr == ISAC_SUBGHZ_REG_TX_MODULATION) && (data != NULL) && (len >= 1U)) {
        g_hil.tx_mod_reg = data[0];
    } else if ((addr == ISAC_SUBGHZ_REG_RX_GAIN) && (data != NULL) && (len >= 1U)) {
        g_hil.rx_gain_reg = data[0];
    } else if ((addr == ISAC_SUBGHZ_REG_TX_CLAMP_CFG) && (data != NULL) && (len >= 1U)) {
        g_hil.tx_clamp_reg = data[0];
    }
    return true;
}

bool ISAC_HAL_SubGhz_ReadReg(uint16_t addr, uint8_t *data, uint8_t len)
{
    if (!ISAC_HAL_SubGhz_EnsureAwake()) {
        return false;
    }
    if (data != NULL) {
        memset(data, 0, len);
        if ((addr == ISAC_SUBGHZ_REG_SMPSC0R) && (len >= 1U)) {
            data[0] = g_hil.inject_clkde_readback_zero
                        ? (uint8_t)(g_hil.smpsc0r_reg & ~ISAC_SUBGHZ_SMPSC0R_CLKDE)
                        : g_hil.smpsc0r_reg;
        } else if ((addr == ISAC_SUBGHZ_REG_IQ_POLARITY) && (len >= 1U)) {
            data[0] = g_hil.iq_polarity_reg;
        } else if ((addr == ISAC_SUBGHZ_REG_TX_MODULATION) && (len >= 1U)) {
            data[0] = g_hil.tx_mod_reg;
        } else if ((addr == ISAC_SUBGHZ_REG_RX_GAIN) && (len >= 1U)) {
            data[0] = g_hil.rx_gain_reg;
        } else if ((addr == ISAC_SUBGHZ_REG_TX_CLAMP_CFG) && (len >= 1U)) {
            data[0] = g_hil.tx_clamp_reg;
        }
    }
    return true;
}

bool ISAC_HAL_SubGhz_WriteBuffer(uint8_t offset, const uint8_t *data, uint8_t len)
{
    if (g_hil.inject_rfbusy_timeout) {
        return false;
    }
    if (data != NULL) {
        for (uint8_t i = 0U; i < len; ++i) {
            g_hil.tx_fifo[(uint8_t)(offset + i)] = data[i];
        }
    }
    return true;
}

bool ISAC_HAL_SubGhz_ReadBuffer(uint8_t offset, uint8_t *data, uint8_t len)
{
    if (g_hil.inject_rfbusy_timeout) {
        return false;
    }
    if (data != NULL) {
        for (uint8_t i = 0U; i < len; ++i) {
            data[i] = g_hil.rx_fifo[(uint8_t)(offset + i)];
        }
    }
    return true;
}

void ISAC_HAL_ADC_EnableAndCalibrate(void)
{
    g_hil.adc_enabled = true;
}

void ISAC_HAL_ADC_Disable(void)
{
    g_hil.adc_enabled = false;
}

uint16_t ISAC_HAL_ReadVrefintCal(void)
{
    return g_hil.vrefint_cal;
}

uint16_t ISAC_HAL_ReadTsCal1(void) { return 1037U; }
uint16_t ISAC_HAL_ReadTsCal2(void) { return 1370U; }

int16_t ISAC_HAL_ADC_ReadDieTempDegCx10(uint16_t vdda_mv)
{
    (void)vdda_mv;
    return g_hil.mock_die_temp_degc_x10;
}

void ISAC_HAL_ReadUniqueId64(uint8_t uid_be[8])
{
    static const uint8_t k_mock_uid[8] = { 0xACU, 0x1FU, 0x09U, 0xFFU, 0xFEU, 0x08U, 0x68U, 0x01U };
    if (uid_be != NULL) {
        memcpy(uid_be, k_mock_uid, 8U);
    }
}

void ISAC_HAL_DelayUs(uint32_t us)
{
    if (g_hil.det_en_high) {
        g_hil.delay_since_det_en_us += us;
    }
    if (g_hil.bat_mon_en_high) {
        g_hil.delay_since_bat_mon_en_us += us;
    }
    if (g_hil.cw_active) {
        g_hil.delay_since_cw_on_us     += us;
        g_hil.delay_since_quench_us    += us;
    } else {
        g_hil.delay_since_cw_off_us    += us;
    }
}

uint32_t ISAC_HAL_ADC_ReadOversampled16x(uint8_t channel)
{
    uint32_t active_vdda_100uv = g_hil.vdda_true_100uv;
    if (g_hil.cw_active &&
        (g_hil.current_tone_idx < ISAC_NUM_TONES) &&
        (g_hil.vdda_tone_override_100uv[g_hil.current_tone_idx] != 0UL)) {
        active_vdda_100uv = g_hil.vdda_tone_override_100uv[g_hil.current_tone_idx];
    }

    if (!g_hil.adc_enabled) {
        return 0UL;
    }

    if (channel == ISAC_ADC_CH_VREFINT) {
        /* 16x oversampled VREFINT count = round(16 * VREFINT_CAL * 3000.0 mV / VDDA_mv) */
        const uint64_t num = 16ULL * (uint64_t)g_hil.vrefint_cal * 30000ULL;
        return (uint32_t)((num + (active_vdda_100uv / 2UL)) / active_vdda_100uv);
    }

    if (channel == ISAC_ADC_CH_BAT_SENSE) {
        /* Gated R_B1 = 4.7k / R_B2 = 4.7k via PA9 (BAT_MON_EN / Q2) -> V(PB4) = 0.500 * VBAT (0 V if BAT_MON_EN == 0) */
        if (!g_hil.bat_mon_en_high) {
            return 0UL;
        }
        g_hil.bat_mon_en_was_high_at_adc = true;
        if (g_hil.det_en_high) {
            g_hil.wakeup_settled_at_bat_adc = (g_hil.delay_since_det_en_us >= ISAC_WAKEUP_SETTLE_US);
        } else {
            g_hil.wakeup_settled_at_bat_adc = (g_hil.delay_since_bat_mon_en_us >= ISAC_RAIL_SENSE_SETTLE_US);
        }
        const uint64_t v_pb4_100uv = ((uint64_t)g_hil.vbat_true_mv * 10ULL) / 2ULL;
        const uint64_t raw16 = (v_pb4_100uv * 65520ULL + (active_vdda_100uv / 2UL))
                               / active_vdda_100uv;
        return (raw16 > 65520ULL) ? 65520UL : (uint32_t)raw16;
    }

    if (channel == ISAC_ADC_CH_DET_ADC) {
        if (!g_hil.det_en_high) {
            g_hil.det_en_was_high_at_adc = false;
            return 0UL;
        }
        g_hil.det_en_was_high_at_adc = true;
        if (!g_hil.cw_active) {
            /* TX-off Listen-Before-Sense (LBS) ambient RF ingress measurement (pre- or post-sweep) */
            uint64_t v_amb_100uv = 1400ULL; /* Nominal 140.0 mV quiet LT5538 50-Ohm thermal floor */
            g_hil.lbs_tx_off_samples++;
            if (g_hil.cw_trigger_count == 0U) {
                if (g_hil.jammer_pre_bursts_remaining > 0U) {
                    v_amb_100uv = (g_hil.ambient_pre_100uv != 0UL) ? g_hil.ambient_pre_100uv : 4600ULL;
                    g_hil.jammer_pre_bursts_remaining--;
                } else if (g_hil.ambient_pre_100uv != 0UL) {
                    v_amb_100uv = g_hil.ambient_pre_100uv;
                }
            } else {
                if (g_hil.ambient_post_100uv != 0UL) {
                    v_amb_100uv = g_hil.ambient_post_100uv;
                }
            }
            const uint64_t raw16_amb = (v_amb_100uv * 65520ULL + (active_vdda_100uv / 2UL))
                                       / active_vdda_100uv;
            return (raw16_amb > 65520ULL) ? 65520UL : (uint32_t)raw16_amb;
        }
        const uint32_t idx = g_hil.current_tone_idx;
        if (idx < ISAC_NUM_TONES) {
            g_hil.lpf_settled_at_det_adc[idx] =
                g_hil.cw_active &&
                (g_hil.delay_since_cw_on_us >= ISAC_LPF_SETTLE_US) &&
                (g_hil.delay_since_cw_on_us <= (ISAC_MAX_CW_DWELL_PER_TONE_MS * 1000UL));
            g_hil.rfsw_tx_lp_at_det_adc[idx] = (g_hil.rf_sw_mode == ISAC_RFSW_TX_LP);
            g_hil.captured_freq_hz[idx]      = g_hil.current_rf_freq_hz;
        }
        const uint64_t v_det_100uv = g_hil.tone_vout_100uv[idx];
        const uint64_t raw16 = (v_det_100uv * 65520ULL + (active_vdda_100uv / 2UL))
                               / active_vdda_100uv;
        return (raw16 > 65520ULL) ? 65520UL : (uint32_t)raw16;
    }

    return 0UL;
}

void ISAC_HAL_EnterStop2(void)
{
    g_hil.sim_tick_ms += g_hil.rtc_period_s * 1000UL;
}

/* =========================================================================
 * 2. Minimal Dependency-Free JSON Curve Loader (`design_values.json`)
 * ========================================================================= */
typedef struct {
    char                 name[32];
    double               eps_real;
    double               vout_v[3];
    double               tilt_db;
    double               level_dbm;
    isac_surface_state_t expected_state;
} benchmark_curve_t;

static isac_surface_state_t map_medium_to_expected_state(const char *name)
{
    if (strstr(name, "dry air") != NULL) {
        return ISAC_SURFACE_DRY_AIR;
    }
    if ((strstr(name, "PTFE") != NULL) || (strstr(name, "Oil") != NULL) ||
        (strstr(name, "oil") != NULL)) {
        return ISAC_SURFACE_OIL;
    }
    if (strstr(name, "ice") != NULL) {
        return ISAC_SURFACE_GLAZE_ICE;
    }
    if ((strstr(name, "IPA") != NULL) || (strstr(name, "alumina") != NULL)) {
        return ISAC_SURFACE_IPA;
    }
    if (strstr(name, "water") != NULL) {
        return ISAC_SURFACE_LIQUID_WATER;
    }
    return ISAC_SURFACE_FAULT;
}

static bool extract_json_number(const char *obj_start, const char *obj_end,
                                const char *key, double *out_val)
{
    const char *p = strstr(obj_start, key);
    if ((p == NULL) || (p >= obj_end)) {
        return false;
    }
    p = strchr(p + strlen(key), ':');
    if ((p == NULL) || (p >= obj_end)) {
        return false;
    }
    *out_val = strtod(p + 1, NULL);
    return true;
}

static uint32_t load_design_values_curves(const char *json_path,
                                          benchmark_curve_t *curves,
                                          uint32_t max_curves)
{
    FILE *fp = fopen(json_path, "rb");
    if (fp == NULL) {
        return 0U;
    }
    if (fseek(fp, 0L, SEEK_END) != 0) {
        fclose(fp);
        return 0U;
    }
    const long fsize = ftell(fp);
    if (fsize <= 0L) {
        fclose(fp);
        return 0U;
    }
    rewind(fp);

    char *buf = (char *)malloc((size_t)fsize + 1U);
    if (buf == NULL) {
        fclose(fp);
        return 0U;
    }
    const size_t nread = fread(buf, 1U, (size_t)fsize, fp);
    fclose(fp);
    buf[nread] = '\0';

    const char *tbl = strstr(buf, "\"table\"");
    if (tbl == NULL) {
        free(buf);
        return 0U;
    }
    const char *arr_start = strchr(tbl, '[');
    if (arr_start == NULL) {
        free(buf);
        return 0U;
    }

    uint32_t count = 0U;
    const char *cur = arr_start + 1;
    while ((*cur != '\0') && (*cur != ']') && (count < max_curves)) {
        const char *obj_open = strchr(cur, '{');
        if (obj_open == NULL) {
            break;
        }
        const char *obj_close = strchr(obj_open, '}');
        if (obj_close == NULL) {
            break;
        }

        benchmark_curve_t *c = &curves[count];
        memset(c, 0, sizeof(*c));

        const char *mkey = strstr(obj_open, "\"medium\"");
        if ((mkey != NULL) && (mkey < obj_close)) {
            const char *colon = strchr(mkey, ':');
            const char *q1    = (colon != NULL) ? strchr(colon, '"') : NULL;
            const char *q2    = (q1 != NULL) ? strchr(q1 + 1, '"') : NULL;
            if ((q1 != NULL) && (q2 != NULL) && (q2 < obj_close)) {
                size_t len = (size_t)(q2 - (q1 + 1));
                if (len >= sizeof(c->name)) {
                    len = sizeof(c->name) - 1U;
                }
                memcpy(c->name, q1 + 1, len);
                c->name[len] = '\0';
            }
        }

        const char *vkey = strstr(obj_open, "\"vout_v\"");
        bool v_ok = false;
        if ((vkey != NULL) && (vkey < obj_close)) {
            const char *lb = strchr(vkey, '[');
            if ((lb != NULL) && (lb < obj_close)) {
                char *endp = NULL;
                c->vout_v[0] = strtod(lb + 1, &endp);
                const char *cm1 = (endp != NULL) ? strchr(endp, ',') : NULL;
                const char *cm2 = (cm1 != NULL) ? strchr(cm1 + 1, ',') : NULL;
                if ((cm1 != NULL) && (cm2 != NULL) && (cm2 < obj_close)) {
                    c->vout_v[1] = strtod(cm1 + 1, NULL);
                    c->vout_v[2] = strtod(cm2 + 1, NULL);
                    v_ok = true;
                }
            }
        }

        if (v_ok &&
            extract_json_number(obj_open, obj_close, "\"eps_real\"", &c->eps_real) &&
            extract_json_number(obj_open, obj_close, "\"tilt_dB\"", &c->tilt_db) &&
            extract_json_number(obj_open, obj_close, "\"level_dBm\"", &c->level_dbm)) {
            c->expected_state = map_medium_to_expected_state(c->name);
            ++count;
        }

        cur = obj_close + 1;
    }

    free(buf);
    return count;
}

/* =========================================================================
 * 3. Deterministic Assertion Helper & Test Suites
 * ========================================================================= */
static uint32_t g_tests_passed = 0U;
static uint32_t g_tests_failed = 0U;

#define HIL_ASSERT(cond, msg, ...)                                                    \
    do {                                                                              \
        if (cond) {                                                                   \
            ++g_tests_passed;                                                         \
        } else {                                                                      \
            ++g_tests_failed;                                                         \
            fprintf(stderr, "  [FAIL] Line %d: " msg "\n", __LINE__, ##__VA_ARGS__);  \
        }                                                                             \
    } while (0)

static const char *state_name(isac_surface_state_t s)
{
    switch (s) {
    case ISAC_SURFACE_DRY_AIR:      return "DRY_AIR";
    case ISAC_SURFACE_OIL:          return "OIL";
    case ISAC_SURFACE_GLAZE_ICE:    return "GLAZE_ICE";
    case ISAC_SURFACE_IPA:          return "IPA";
    case ISAC_SURFACE_LIQUID_WATER: return "LIQUID_WATER";
    case ISAC_SURFACE_FAULT:
    default:                        return "FAULT";
    }
}

static void test_pin_map_and_smps_sequence(void)
{
    printf("[1/5] Verifying Schematic Pin Map, PA0/PA1 RF Switch, PB0 TCXO, ADC_IN13 & 15 uH SMPS...\n");

    /* Exact schematic & STM32WLE5JC silicon parity checks */
    HIL_ASSERT(ISAC_SIP_PIN_DET_EN == 51U && ISAC_GPIOA_PIN_DET_EN == 8U,
               "PA8 (SiP Pin 51) DET_EN mapping mismatch");
    HIL_ASSERT(ISAC_SIP_PIN_BAT_MON_EN == 50U && ISAC_GPIOA_PIN_BAT_MON_EN == 9U,
               "PA9 (SiP Pin 50) BAT_MON_EN mapping mismatch");
    HIL_ASSERT(ISAC_SIP_PIN_DET_ADC == 8U && ISAC_GPIOA_PIN_DET_ADC == 15U && ISAC_ADC_CH_DET_ADC == 11U,
               "PA15 (SiP Pin 8, ADC_IN11) DET_ADC mapping mismatch");
    HIL_ASSERT(ISAC_SIP_PIN_BAT_SENSE == 15U && ISAC_GPIOB_PIN_BAT_SENSE == 4U && ISAC_ADC_CH_BAT_SENSE == 3U,
               "PB4 (SiP Pin 15, ADC_IN3) BAT_SENSE mapping mismatch");
    HIL_ASSERT(ISAC_ADC_CH_VREFINT == 13U,
               "STM32WLE5JC VREFINT channel must be ADC_IN13 (13U)");
    HIL_ASSERT(ISAC_ADC_CFGR2_CKMODE_PCLK2 == (1UL << 30),
               "STM32WLE5JC ADC CKMODE PCLK/2 bitmask mismatch");
    HIL_ASSERT(ISAC_SIP_PIN_UART2_TX == 29U && ISAC_SIP_PIN_UART2_RX == 30U,
               "PA2/PA3 (SiP Pins 29/30) USART2 mapping mismatch");
    HIL_ASSERT(ISAC_SIP_PIN_SWDIO == 1U && ISAC_SIP_PIN_SWCLK == 2U,
               "PA13/PA14 (SiP Pins 1/2) SWD mapping mismatch");
    HIL_ASSERT(ISAC_GPIOA_PIN_RFSW_VC1 == 0U && ISAC_GPIOA_PIN_RFSW_VC2 == 1U && ISAC_SIP_PIN_RF_OUT == 37U,
               "RAK3172LP-SiP internal SPDT RF switch (PA0 VC1 / PA1 VC2 -> Pin 37 RF_OUT) mismatch");

    memset(&g_hil, 0, sizeof(g_hil));
    hil_reset_trace();
    HIL_ASSERT(ISAC_Init_Radio_And_SMPS(), "ISAC_Init_Radio_And_SMPS() failed under nominal conditions");

    HIL_ASSERT(g_hil.gpio_inited, "Board GPIOs not initialized");
    HIL_ASSERT(g_hil.clkde_set_before_smpsen,
               "DS13105 §3.9.1 Danger: SUBGHZ_SMPSC0R.CLKDE (0x0916 |= 0x40) not set before PWR_CR5_SMPSEN!");
    HIL_ASSERT(g_hil.smps_hw_cr5_enabled, "PWR_CR5_SMPSEN not enabled for external 15 uH L_SMPS");
    HIL_ASSERT(g_hil.subghz_reset_called, "SUBGHZSPI wakeup/reset not executed");
    HIL_ASSERT(ISAC_Is_SMPS_Active(), "ISAC_Is_SMPS_Active() did not read live SMPS ready state");
    HIL_ASSERT(!g_hil.det_en_high && !g_hil.bat_mon_en_high && (g_hil.rf_sw_mode == ISAC_RFSW_OFF),
               "DET_EN, BAT_MON_EN, or RF switch left active after init");

    /* Verify exact SetRegulatorMode(USE_DCDC) + SetDIO3AsTCXOCtrl(0x97, 3.0V=0x06) + Calibrate(0x89) + RFO_LP (+14 dBm) */
    bool saw_use_dcdc = false;
    bool saw_tcxo_3v0 = false;
    bool saw_cal_all  = false;
    bool saw_cal_img  = false;
    bool saw_rfo_lp   = false;
    bool saw_tx_14dbm = false;
    bool saw_sleep    = false;
    bool saw_dio2_9d  = false;
    for (uint32_t i = 0U; i < g_hil.cmd_count; ++i) {
        const hil_subghz_cmd_t *c = &g_hil.cmd_log[i];
        if (c->opcode == 0x9DU) {
            saw_dio2_9d = true;
        }
        if ((c->opcode == ISAC_SUBGHZ_CMD_SET_REGULATOR_MODE) &&
            (c->len == 1U) && (c->params[0] == ISAC_SUBGHZ_REGMODE_USE_DCDC)) {
            saw_use_dcdc = true;
        }
        if ((c->opcode == ISAC_SUBGHZ_CMD_SET_TCXO_MODE) &&
            (c->len == 4U) && (c->params[0] == ISAC_SUBGHZ_TCXO_CTRL_3_0V) &&
            (c->params[2] == 0x01U) && (c->params[3] == 0x40U)) {
            saw_tcxo_3v0 = true;
        }
        if ((c->opcode == ISAC_SUBGHZ_CMD_CALIBRATE) &&
            (c->len == 1U) && (c->params[0] == ISAC_SUBGHZ_CALIBRATE_ALL_BLOCKS)) {
            saw_cal_all = true;
        }
        if ((c->opcode == ISAC_SUBGHZ_CMD_CALIBRATE_IMAGE) &&
            (c->len == 2U) && (c->params[0] == 0xD7U) && (c->params[1] == 0xDBU)) {
            saw_cal_img = true;
        }
        if ((c->opcode == ISAC_SUBGHZ_CMD_SET_PA_CONFIG) &&
            (c->len == 4U) && (c->params[2] == ISAC_SUBGHZ_PA_DEVSEL_RFO_LP)) {
            saw_rfo_lp = true;
        }
        if ((c->opcode == ISAC_SUBGHZ_CMD_SET_TX_PARAMS) &&
            (c->len == 2U) && (c->params[0] == 14U)) {
            saw_tx_14dbm = true;
        }
        if ((c->opcode == ISAC_SUBGHZ_CMD_SET_SLEEP) &&
            (c->len == 1U) && (c->params[0] == ISAC_SUBGHZ_SLEEP_WARM_START)) {
            saw_sleep = true;
        }
    }
    HIL_ASSERT(!saw_dio2_9d,  "Forbidden SetDio2AsRfSwitchCtrl(0x9D) issued on RAK3172LP-SiP!");
    HIL_ASSERT(saw_use_dcdc,  "Missing SUBGHZ_SetRegulatorMode(0x01 /* USE_DCDC */)");
    HIL_ASSERT(saw_tcxo_3v0,  "Missing SetDIO3AsTCXOCtrl(0x97, 3.0V=0x06, 320 ticks) for PB0 32 MHz TCXO");
    HIL_ASSERT(saw_cal_all,   "Missing SetCalibrate(0x89, 0x7F)");
    HIL_ASSERT(saw_cal_img,   "Missing CalibrateImage(0x98, 0xD7, 0xDB) for EU868");
    HIL_ASSERT(saw_rfo_lp,    "Missing SetPaConfig with deviceSel=0x01 (RFO_LP)");
    HIL_ASSERT(saw_tx_14dbm,  "Missing SetTxParams(+14 dBm)");
    HIL_ASSERT(g_hil.rx_gain_reg == ISAC_SUBGHZ_RX_GAIN_BOOSTED,
               "Missing SUBGHZ_RXGAIN (0x08AC = 0x96) +3 dB LNA boost");
    HIL_ASSERT((g_hil.tx_clamp_reg & ISAC_SUBGHZ_TX_CLAMP_FIX_MASK) == ISAC_SUBGHZ_TX_CLAMP_FIX_MASK,
               "BLK-RF-FW-02: Missing SX1262 §15.2 TxClampConfig (0x08D8 |= 0x1E) antenna-mismatch PA fix (got 0x%02X)!",
               g_hil.tx_clamp_reg);
    HIL_ASSERT(saw_sleep,     "Radio not parked in warm-start sleep after init");

    /* Run one 3-tone sweep and verify exact PA8 gating, 1000 us wakeup, 3 x 600 us LPF dwell */
    g_hil.vdda_true_100uv    = 33000UL;
    g_hil.vbat_true_mv       = 3600UL;
    g_hil.vrefint_cal        = 1650U;
    g_hil.tone_vout_100uv[0] = 10870UL;
    g_hil.tone_vout_100uv[1] = 8720UL;
    g_hil.tone_vout_100uv[2] = 11510UL;
    hil_reset_trace();

    isac_raw_sweep_t sw;
    HIL_ASSERT(ISAC_Acquire_3Tone_Sweep(&sw), "ISAC_Acquire_3Tone_Sweep() failed nominally");

    HIL_ASSERT(g_hil.det_en_was_high_at_adc, "PA8 (DET_EN) was not HIGH during DET_ADC sampling");
    HIL_ASSERT(g_hil.bat_mon_en_was_high_at_adc, "PA9 (BAT_MON_EN) was not HIGH during BAT_SENSE sampling");
    HIL_ASSERT(g_hil.wakeup_settled_at_bat_adc, "3.0 ms wakeup window not observed before ADC read");
    for (uint32_t t = 0U; t < ISAC_NUM_TONES; ++t) {
        HIL_ASSERT(g_hil.lpf_settled_at_det_adc[t],
                   "Tone %u did not observe 600 us..3000 us video LPF settling window", t);
        HIL_ASSERT(g_hil.rfsw_tx_lp_at_det_adc[t],
                   "Tone %u did not route RFO_LP via PA0=0, PA1=1", t);
    }
    HIL_ASSERT(labs((long)g_hil.captured_freq_hz[0] - 863100000L) <= 5L, "f1 != 863.1 MHz");
    HIL_ASSERT(labs((long)g_hil.captured_freq_hz[1] - 866500000L) <= 5L, "f2 != 866.5 MHz");
    HIL_ASSERT(labs((long)g_hil.captured_freq_hz[2] - 869500000L) <= 5L, "f3 != 869.5 MHz");

    HIL_ASSERT(!g_hil.det_en_high && !g_hil.bat_mon_en_high,
               "PA8 (DET_EN) or PA9 (BAT_MON_EN) not immediately de-asserted after sweep!");
    HIL_ASSERT(!g_hil.adc_enabled, "SAR ADC not disabled after sweep!");
    HIL_ASSERT(!g_hil.cw_active && (g_hil.rf_sw_mode == ISAC_RFSW_OFF),
               "CW carrier or RF switch left active after sweep!");

    /* Verify live SMPSRDY fault clears FPort 10 bit 4 (never hard-coded true) */
    g_hil.inject_smps_fault = true;
    HIL_ASSERT(!ISAC_Init_Radio_And_SMPS(), "ISAC_Init_Radio_And_SMPS() must return false when SMPSRDY fails");
    HIL_ASSERT(!ISAC_Is_SMPS_Active(), "ISAC_Is_SMPS_Active() must be false when PWR_SR2_SMPSRDY=0");
    isac_raw_sweep_t sw_nosmps = { 0 };
    isac_telemetry_t tel_nosmps = { 0 };
    uint8_t wire_nosmps[ISAC_FPORT10_PAYLOAD_LEN] = { 0 };
    HIL_ASSERT(ISAC_Acquire_3Tone_Sweep(&sw_nosmps), "Sweep radio path should still run on LDO fallback");
    ISAC_Extract_Features_And_Classify(&sw_nosmps, &tel_nosmps);
    ISAC_Pack_LoRaWAN_FPort10(&tel_nosmps, NULL, wire_nosmps);
    HIL_ASSERT(!sw_nosmps.smps_dcdc_enabled && ((wire_nosmps[0] & ISAC_FLAG_SMPS_DCDC_ACTIVE) == 0U),
               "FPort 10 bit 4 must report 0 when live SMPSRDY is 0!");
    g_hil.inject_smps_fault = false;

    /* Verify RFBUSYS timeout propagates false through Init, Sweep & Class A TX */
    g_hil.inject_rfbusy_timeout = true;
    HIL_ASSERT(!ISAC_Init_Radio_And_SMPS(), "ISAC_Init_Radio_And_SMPS() must fail on RFBUSYS timeout");
    isac_raw_sweep_t sw_busy = { 0 };
    isac_telemetry_t tel_busy = { 0 };
    HIL_ASSERT(!ISAC_Acquire_3Tone_Sweep(&sw_busy), "ISAC_Acquire_3Tone_Sweep() must fail on RFBUSYS timeout");
    ISAC_Extract_Features_And_Classify(&sw_busy, &tel_busy);
    HIL_ASSERT(tel_busy.state == ISAC_SURFACE_FAULT, "RFBUSYS timeout must force ISAC_SURFACE_FAULT");
    static const uint8_t k_zero16[16] = { 0 };
    isac_lorawan_ctx_t busy_ctx;
    ISAC_LoRaWAN_InitABP(&busy_ctx, 0x26011868UL, k_zero16, k_zero16);
    HIL_ASSERT(ISAC_LoRaWAN_SendClassA(&busy_ctx, ISAC_LORAWAN_FPORT, wire_nosmps, 10U, NULL) ==
               ISAC_LORAWAN_ERR_RADIO_BUSY,
               "ISAC_LoRaWAN_SendClassA() must return ISAC_LORAWAN_ERR_RADIO_BUSY on RFBUSYS timeout");
    g_hil.inject_rfbusy_timeout = false;
    HIL_ASSERT(ISAC_Init_Radio_And_SMPS() && ISAC_Is_SMPS_Active(),
               "Recovery ISAC_Init_Radio_And_SMPS() failed");
}

static void test_vrefint_droop_and_drift_and_classification(const benchmark_curve_t *curves,
                                                            uint32_t num_curves)
{
    printf("[2/5] Verifying VREFINT Supply-Droop Immunity (3.30 V vs 3.00 V -> 0 mV Error)...\n");
    printf("[3/5] Verifying PA/Temp Intercept Drift Cancellation (+/-2.0 dB -> 0.00 dB Error)...\n");
    printf("[4/5] Verifying 100%% Benchmark Classification (%u Media x 2 VDDA x 3 Drift = %u Runs)...\n",
           num_curves, num_curves * 6U);

    uint32_t total_runs   = 0U;
    uint32_t correct_runs = 0U;

    for (uint32_t idx = 0U; idx < num_curves; ++idx) {
        const benchmark_curve_t *c = &curves[idx];
        isac_raw_sweep_t sw_3v3  = { 0 };
        isac_raw_sweep_t sw_3v0  = { 0 };
        isac_telemetry_t tel_nom = { 0 };
        isac_telemetry_t tel_p2  = { 0 };
        isac_telemetry_t tel_m2  = { 0 };

        g_hil.vbat_true_mv = 3600UL;
        g_hil.vrefint_cal  = 1650U;
        for (uint32_t t = 0U; t < ISAC_NUM_TONES; ++t) {
            g_hil.tone_vout_100uv[t] = (uint32_t)llround(c->vout_v[t] * 10000.0);
        }

        g_hil.vdda_true_100uv = 33000UL;
        ISAC_Acquire_3Tone_Sweep(&sw_3v3);

        g_hil.vdda_true_100uv = 30000UL;
        ISAC_Acquire_3Tone_Sweep(&sw_3v0);

        HIL_ASSERT(sw_3v3.vdda_mv == 3300U && sw_3v0.vdda_mv == 3000U,
                   "%s: VDDA recovery mismatch (%u vs %u mV)",
                   c->name, sw_3v3.vdda_mv, sw_3v0.vdda_mv);
        HIL_ASSERT(sw_3v3.vbat_mv == 3600U && sw_3v0.vbat_mv == 3600U,
                   "%s: VBAT droop error (%u vs %u mV, expected 3600 mV)",
                   c->name, sw_3v3.vbat_mv, sw_3v0.vbat_mv);

        for (uint32_t t = 0U; t < ISAC_NUM_TONES; ++t) {
            const int32_t err_mv = (int32_t)sw_3v0.det_mv[t] - (int32_t)sw_3v3.det_mv[t];
            HIL_ASSERT(err_mv == 0,
                       "%s tone %u: VDDA droop error = %d mV (expected 0 mV)",
                       c->name, t, (int)err_mv);
        }

        ISAC_Extract_Features_And_Classify(&sw_3v3, &tel_nom);
        const int32_t vout_tilt_x100 = (int32_t)llround(((c->vout_v[0] - c->vout_v[2]) / 0.019) * 100.0);
        const int32_t exp_tilt_x100  = (int32_t)llround(c->tilt_db * 100.0);
        const int32_t exp_level_x100 = (int32_t)llround(c->level_dbm * 100.0);
        HIL_ASSERT(abs((int)tel_nom.tilt_db_x100 - (int)vout_tilt_x100) <= 1,
                   "%s: fixed-point tilt_db_x100 = %d vs exact vout formula %d",
                   c->name, tel_nom.tilt_db_x100, (int)vout_tilt_x100);
        HIL_ASSERT(abs((int)tel_nom.tilt_db_x100 - (int)exp_tilt_x100) <= 5,
                   "%s: tilt_db_x100 = %d vs JSON %d", c->name, tel_nom.tilt_db_x100, (int)exp_tilt_x100);
        HIL_ASSERT(abs((int)tel_nom.level_dbm_x100 - (int)exp_level_x100) <= 5,
                   "%s: level_dbm_x100 = %d vs JSON %d", c->name, tel_nom.level_dbm_x100, (int)exp_level_x100);

        const int32_t  shifts_cdb[3]  = { 0, +200, -200 };
        const uint32_t vddas_100uv[2] = { 33000UL, 30000UL };

        for (uint32_t v_i = 0U; v_i < 2U; ++v_i) {
            for (uint32_t s_i = 0U; s_i < 3U; ++s_i) {
                isac_raw_sweep_t sw_cur;
                isac_telemetry_t tel_cur;
                const int32_t dv_100uv = (shifts_cdb[s_i] * 19) / 10;

                g_hil.vdda_true_100uv = vddas_100uv[v_i];
                for (uint32_t t = 0U; t < ISAC_NUM_TONES; ++t) {
                    const int32_t base_u100 = (int32_t)llround(c->vout_v[t] * 10000.0);
                    g_hil.tone_vout_100uv[t] = (uint32_t)(base_u100 + dv_100uv);
                }

                ISAC_Acquire_3Tone_Sweep(&sw_cur);
                ISAC_Extract_Features_And_Classify(&sw_cur, &tel_cur);

                if ((v_i == 0U) && (s_i == 1U)) {
                    tel_p2 = tel_cur;
                } else if ((v_i == 0U) && (s_i == 2U)) {
                    tel_m2 = tel_cur;
                }

                HIL_ASSERT(tel_cur.tilt_db_x100 == tel_nom.tilt_db_x100,
                           "%s (VDDA=%u, dP=%d cdb): Tilt drifted %d != %d (expected 0.00 dB error)",
                           c->name, sw_cur.vdda_mv, (int)shifts_cdb[s_i],
                           tel_cur.tilt_db_x100, tel_nom.tilt_db_x100);
                HIL_ASSERT(tel_cur.notch_db_x100 == tel_nom.notch_db_x100,
                           "%s (VDDA=%u, dP=%d cdb): Notch drifted %d != %d",
                           c->name, sw_cur.vdda_mv, (int)shifts_cdb[s_i],
                           tel_cur.notch_db_x100, tel_nom.notch_db_x100);

                ++total_runs;
                if (tel_cur.state == c->expected_state) {
                    ++correct_runs;
                }
                HIL_ASSERT(tel_cur.state == c->expected_state,
                           "%s (VDDA=%u mV, dP=%+d cdb): Classified %s != expected %s",
                           c->name, sw_cur.vdda_mv, (int)shifts_cdb[s_i],
                           state_name(tel_cur.state), state_name(c->expected_state));
            }
        }

        HIL_ASSERT(abs((tel_p2.level_dbm_x100 - tel_nom.level_dbm_x100) - 200) <= 1 &&
                   abs((tel_m2.level_dbm_x100 - tel_nom.level_dbm_x100) + 200) <= 1,
                   "%s: Level did not track +/-2.00 dB shift", c->name);

        printf("    %-16s | eps=%5.2f | V=[%4u,%4u,%4u] mV | Tilt=%+6.2f dB | Notch=%+6.2f dB -> %-12s [PASS]\n",
               c->name,
               c->eps_real,
               sw_3v3.det_mv[0], sw_3v3.det_mv[1], sw_3v3.det_mv[2],
               (double)tel_nom.tilt_db_x100 / 100.0,
               (double)tel_nom.notch_db_x100 / 100.0,
               state_name(tel_nom.state));
    }

    HIL_ASSERT(correct_runs == total_runs && total_runs > 0U,
               "Classification accuracy %u/%u != 100%%", correct_runs, total_runs);

    g_hil.vdda_true_100uv    = 33000UL;
    g_hil.tone_vout_100uv[0] = 200UL;
    g_hil.tone_vout_100uv[1] = 200UL;
    g_hil.tone_vout_100uv[2] = 200UL;
    isac_raw_sweep_t sw_flt;
    isac_telemetry_t tel_flt;
    HIL_ASSERT(ISAC_Acquire_3Tone_Sweep(&sw_flt), "Fault-test sweep failed");
    ISAC_Extract_Features_And_Classify(&sw_flt, &tel_flt);
    HIL_ASSERT(tel_flt.state == ISAC_SURFACE_FAULT, "Open-bridge fault did not trigger ISAC_SURFACE_FAULT");

    /* Inject 10% dynamic VDDA droop across tones (3.30 V -> 3.135 V -> 2.97 V)
     * during CW PA emission and verify < 0.5% det_mv error + min VDDA recorded in sw_step.vdda_mv */
    g_hil.vdda_true_100uv    = 33000UL;
    g_hil.vbat_true_mv       = 3600UL;
    g_hil.vrefint_cal        = 1650U;
    g_hil.tone_vout_100uv[0] = 11435UL; /* Rev E.5 +4 dBm Glaze ice f1 = 1143.5 mV */
    g_hil.tone_vout_100uv[1] = 11425UL; /* Rev E.5 +4 dBm Glaze ice f2 = 1142.5 mV */
    g_hil.tone_vout_100uv[2] = 11437UL; /* Rev E.5 +4 dBm Glaze ice f3 = 1143.7 mV */
    g_hil.vdda_tone_override_100uv[0] = 33000UL; /* 3.300 V */
    g_hil.vdda_tone_override_100uv[1] = 31350UL; /* 3.135 V (-5%) */
    g_hil.vdda_tone_override_100uv[2] = 29700UL; /* 2.970 V (-10%) */

    isac_raw_sweep_t sw_step = { 0 };
    isac_telemetry_t tel_step = { 0 };
    HIL_ASSERT(ISAC_Acquire_3Tone_Sweep(&sw_step), "Dynamic VDDA step sweep failed");
    ISAC_Extract_Features_And_Classify(&sw_step, &tel_step);

    g_hil.vdda_tone_override_100uv[0] = 0UL;
    g_hil.vdda_tone_override_100uv[1] = 0UL;
    g_hil.vdda_tone_override_100uv[2] = 0UL;

    HIL_ASSERT(sw_step.vdda_mv == 2970U,
               "sw_step.vdda_mv = %u mV != expected min 2970 mV", sw_step.vdda_mv);
    HIL_ASSERT(sw_step.vdda_tone_mv[0] == 3300U &&
               sw_step.vdda_tone_mv[1] == 3135U &&
               sw_step.vdda_tone_mv[2] == 2970U,
               "per-tone VDDA tracking mismatch (%u, %u, %u mV)",
               sw_step.vdda_tone_mv[0], sw_step.vdda_tone_mv[1], sw_step.vdda_tone_mv[2]);
    for (uint32_t t = 0U; t < ISAC_NUM_TONES; ++t) {
        const double true_mv = (double)g_hil.tone_vout_100uv[t] / 10.0;
        const double pct_err = (fabs((double)sw_step.det_mv[t] - true_mv) / true_mv) * 100.0;
        HIL_ASSERT(pct_err < 0.5,
                   "tone %u det_mv = %u vs %.1f mV (%.3f%% >= 0.5%%)",
                   t, sw_step.det_mv[t], true_mv, pct_err);
    }
    HIL_ASSERT(tel_step.state == ISAC_SURFACE_GLAZE_ICE &&
               abs((int)tel_step.tilt_db_x100 - (-1)) <= 2,
               "Glaze ice misclassified under 10%% intra-sweep VDDA droop (tilt=%d, state=%s)",
               tel_step.tilt_db_x100, state_name(tel_step.state));
}

static void test_fport10_serialization_and_etsi_duty_cycle(void)
{
    printf("    Verifying Byte-Exact 10-Byte Big-Endian FPort 10 Wire Contract & ETSI <= 1%% Duty Cap...\n");

    isac_duty_tracker_t dc;
    ISAC_DutyCycle_Init(&dc, 0UL);

    const isac_telemetry_t golden_tel = {
        .tilt_db_x100   = -510,
        .notch_db_x100  = -110,
        .level_dbm_x100 = -2065,
        .eps_est_x100   = 320U,
        .vbat_mv        = 3600U,
        .vdda_mv        = 3300U,
        .state          = ISAC_SURFACE_GLAZE_ICE,
        .smps_dcdc_ok   = true
    };
    const uint8_t expected_bytes[ISAC_FPORT10_PAYLOAD_LEN] = {
        0x92U, 0xFEU, 0x02U, 0xF7U, 0xEFU, 0x01U, 0x40U, 0x0EU, 0x10U, 0xF5U
    };

    uint8_t wire[ISAC_FPORT10_PAYLOAD_LEN];
    ISAC_Pack_LoRaWAN_FPort10(&golden_tel, &dc, wire);
    HIL_ASSERT(memcmp(wire, expected_bytes, ISAC_FPORT10_PAYLOAD_LEN) == 0,
               "FPort 10 byte-exact big-endian mismatch!");

    isac_telemetry_t unpacked;
    uint8_t flags = 0U;
    ISAC_Unpack_LoRaWAN_FPort10(wire, &unpacked, &flags);
    HIL_ASSERT(flags == 0x92U &&
               unpacked.state == ISAC_SURFACE_GLAZE_ICE &&
               unpacked.smps_dcdc_ok &&
               unpacked.tilt_db_x100 == -510 &&
               unpacked.level_dbm_x100 == -2065 &&
               unpacked.eps_est_x100 == 320U &&
               unpacked.vbat_mv == 3600U &&
               unpacked.notch_db_x100 == -110,
               "FPort 10 unpack round-trip mismatch!");

    HIL_ASSERT(ISAC_DutyCycle_CanTransmit(&dc, 65UL, 0UL), "Initial TX at t=0 rejected");
    ISAC_DutyCycle_RecordAirTime(&dc, 65UL, 0UL);
    HIL_ASSERT(!ISAC_DutyCycle_CanTransmit(&dc, 65UL, 6499UL) && dc.throttled,
               "Backoff violation at t=6499 ms not throttled");
    HIL_ASSERT(ISAC_DutyCycle_CanTransmit(&dc, 65UL, 6500UL) && !dc.throttled,
               "Valid TX at t=6500 ms (exact 1%% backoff) rejected");

    dc.used_airtime_ms = 35980UL;
    HIL_ASSERT(!ISAC_DutyCycle_CanTransmit(&dc, 25UL, 2000000UL) && dc.throttled,
               "1-hour 36,000 ms (1%%) airtime cap did not throttle");

    /* Fresh 3.60 V Li-SOCl2 cell minus B5819W D1 drop (e.g. 3250 mV & 3150 mV
     * at post-D1 VBAT node) MUST NOT false-trigger bit 5 (ISAC_FLAG_LOW_BATTERY) */
    isac_telemetry_t fresh_post_d1_tel = golden_tel;
    fresh_post_d1_tel.vbat_mv = 3250U; /* 3.60 V cell - 0.35 V B5819W forward drop */
    ISAC_Pack_LoRaWAN_FPort10(&fresh_post_d1_tel, &dc, wire);
    HIL_ASSERT((wire[0] & ISAC_FLAG_LOW_BATTERY) == 0U,
               "Fresh 3.60 V cell post-D1 (3250 mV) falsely set ISAC_FLAG_LOW_BATTERY!");
    fresh_post_d1_tel.vbat_mv = 3150U;
    ISAC_Pack_LoRaWAN_FPort10(&fresh_post_d1_tel, &dc, wire);
    HIL_ASSERT((wire[0] & ISAC_FLAG_LOW_BATTERY) == 0U,
               "Healthy plateau cell post-D1 (3150 mV) falsely set ISAC_FLAG_LOW_BATTERY!");

    /* Depleting EOL cell entering ER14335M knee (post-D1 VBAT = 2750 mV < 2800 mV) sets bit 5 */
    isac_telemetry_t lowbat_tel = golden_tel;
    lowbat_tel.vbat_mv = 2750U;
    ISAC_Pack_LoRaWAN_FPort10(&lowbat_tel, &dc, wire);
    HIL_ASSERT((wire[0] & (ISAC_FLAG_LOW_BATTERY | ISAC_FLAG_DUTY_THROTTLED)) ==
               (ISAC_FLAG_LOW_BATTERY | ISAC_FLAG_DUTY_THROTTLED),
               "Low-battery / duty-throttled flags not set in Byte 0 at 2750 mV");

    HIL_ASSERT(ISAC_DutyCycle_CanTransmit(&dc, 65UL, ISAC_ETSI_WINDOW_MS + 1UL),
               "1-hour rolling duty-cycle window did not reset");
}

static void test_lorawan_aes_cmac_otaa_and_class_a(void)
{
    printf("[5/5] Verifying NIST AES-128, RFC 4493 CMAC & LoRaWAN 1.0.3 Class A (OTAA + RX1/RX2)...\n");

    /* 1. NIST FIPS-197 Appendix B & RFC 4493 Section 4 Official Test Vectors */
    static const uint8_t k_nist_key[16] = {
        0x2BU,0x7EU,0x15U,0x16U,0x28U,0xAEU,0xD2U,0xA6U,
        0xABU,0xF7U,0x15U,0x88U,0x09U,0xCFU,0x4FU,0x3CU
    };
    static const uint8_t k_fips_pt[16] = {
        0x32U,0x43U,0xF6U,0xA8U,0x88U,0x5AU,0x30U,0x8DU,
        0x31U,0x31U,0x98U,0xA2U,0xE0U,0x37U,0x07U,0x34U
    };
    static const uint8_t k_fips_ct[16] = {
        0x39U,0x25U,0x84U,0x1DU,0x02U,0xDCU,0x09U,0xFBU,
        0xDCU,0x11U,0x85U,0x97U,0x19U,0x6AU,0x0BU,0x32U
    };
    static const uint8_t k_rfc_msg[40] = {
        0x6BU,0xC1U,0xBEU,0xE2U,0x2EU,0x40U,0x9FU,0x96U,
        0xE9U,0x3DU,0x7EU,0x11U,0x73U,0x93U,0x17U,0x2AU,
        0xAEU,0x2DU,0x8AU,0x57U,0x1EU,0x03U,0xACU,0x9CU,
        0x9EU,0xB7U,0x6FU,0xACU,0x45U,0xAFU,0x8EU,0x51U,
        0x30U,0xC8U,0x1CU,0x46U,0xA3U,0x5CU,0xE4U,0x11U
    };
    static const uint8_t k_cmac_ex1_0b[16] = {
        0xBBU,0x1DU,0x69U,0x29U,0xE9U,0x59U,0x37U,0x28U,
        0x7FU,0xA3U,0x7DU,0x12U,0x9BU,0x75U,0x67U,0x46U
    };
    static const uint8_t k_cmac_ex2_16b[16] = {
        0x07U,0x0AU,0x16U,0xB4U,0x6BU,0x4DU,0x41U,0x44U,
        0xF7U,0x9BU,0xDDU,0x9DU,0xD0U,0x4AU,0x28U,0x7CU
    };
    static const uint8_t k_cmac_ex3_40b[16] = {
        0xDFU,0xA6U,0x67U,0x47U,0xDEU,0x9AU,0xE6U,0x30U,
        0x30U,0xCAU,0x32U,0x61U,0x14U,0x97U,0xC8U,0x27U
    };

    uint8_t out_blk[16];
    ISAC_AES128_EncryptBlock(k_nist_key, k_fips_pt, out_blk);
    HIL_ASSERT(memcmp(out_blk, k_fips_ct, 16U) == 0, "NIST FIPS-197 AES-128 test vector failed!");

    ISAC_AES128_CMAC(k_nist_key, NULL, 0UL, out_blk);
    HIL_ASSERT(memcmp(out_blk, k_cmac_ex1_0b, 16U) == 0, "RFC 4493 CMAC Example 1 (0 bytes) failed!");

    ISAC_AES128_CMAC(k_nist_key, k_rfc_msg, 16UL, out_blk);
    HIL_ASSERT(memcmp(out_blk, k_cmac_ex2_16b, 16U) == 0, "RFC 4493 CMAC Example 2 (16 bytes) failed!");

    ISAC_AES128_CMAC(k_nist_key, k_rfc_msg, 40UL, out_blk);
    HIL_ASSERT(memcmp(out_blk, k_cmac_ex3_40b, 16U) == 0, "RFC 4493 CMAC Example 3 (40 bytes) failed!");

    /* 2. Verify SF7BW125 23-byte FPort 10 LoRa Time-on-Air == 62 ms (61.70 ms rounded up) */
    const uint32_t toa_sf7 = ISAC_LoRaWAN_CalcTimeOnAirMs(7U, ISAC_LORAWAN_FPORT10_PHY_LEN);
    HIL_ASSERT(toa_sf7 == 62UL, "SF7BW125 23-byte PHYPayload ToA = %lu ms != expected 62 ms",
               (unsigned long)toa_sf7);

    /* 3. Verify OTAA JoinRequest + Encrypted Class A Uplink + RX1 (+1000 ms) & RX2 (+2000 ms, 869.525 MHz) */
    isac_lorawan_ctx_t ctx;
    uint8_t dev_eui[8];
    static const uint8_t join_eui[8] = { 0x70U,0xB3U,0xD5U,0x7EU,0xD0U,0x06U,0x86U,0x80U };
    ISAC_HAL_ReadUniqueId64(dev_eui);
    ISAC_LoRaWAN_InitOTAA(&ctx, dev_eui, join_eui, k_nist_key);

    /* Synthesize a valid gateway JoinAccept (decrypted on-node via AES128_EncryptBlock -> stage AES128_Decrypt,
     * or construct plaintext `dec` and compute inverse; even simpler: test ABP + direct JoinAccept round-trip) */
    static const uint8_t k_app_skey[16] = {
        0x3CU,0x4FU,0xCFU,0x09U,0x88U,0x15U,0xF7U,0xABU,
        0xA6U,0xD2U,0xAEU,0x28U,0x16U,0x15U,0x7EU,0x2BU
    };
    uint8_t join_req[ISAC_LORAWAN_JOIN_REQ_PHY_LEN];
    const uint8_t jlen = ISAC_LoRaWAN_BuildJoinRequest(&ctx, join_req);
    HIL_ASSERT(jlen == 23U && join_req[0] == ISAC_LORAWAN_MHDR_JOIN_REQUEST,
               "OTAA JoinRequest MHDR / length mismatch");

    ISAC_LoRaWAN_InitABP(&ctx, 0x26011868UL, k_nist_key, k_app_skey);

    const uint8_t app_fport10[10] = { 0x92U,0xFEU,0x02U,0xF7U,0xEFU,0x01U,0x40U,0x0EU,0x10U,0xF5U };
    memset(&g_hil, 0, sizeof(g_hil));
    hil_reset_trace();
    g_hil.sim_tick_ms    = 1000UL;
    g_hil.staged_rx_len  = 0U; /* Force both RX1 and RX2 windows to open and time out cleanly */

    uint32_t ul_airtime_ms = 0UL;
    const isac_lorawan_status_t st = ISAC_LoRaWAN_SendClassA(
        &ctx,
        ISAC_LORAWAN_FPORT,
        app_fport10,
        ISAC_FPORT10_PAYLOAD_LEN,
        &ul_airtime_ms
    );

    HIL_ASSERT(st == ISAC_LORAWAN_TX_OK, "ISAC_LoRaWAN_SendClassA failed (%d)", (int)st);
    HIL_ASSERT(ul_airtime_ms == 62UL && g_hil.last_tx_len == 23U,
               "Transmitted LoRaWAN PHY length %u != 23 bytes", g_hil.last_tx_len);
    HIL_ASSERT(g_hil.sync_word[0] == 0x34U && g_hil.sync_word[1] == 0x44U,
               "LoRaWAN Public SyncWord 0x3444 not written to SX1262 0x0740");
    HIL_ASSERT(labs((long)g_hil.last_tx_freq_hz - (long)ISAC_EU868_CH0_HZ) <= 5L,
               "First uplink did not use 868.1 MHz");
    HIL_ASSERT(g_hil.rx_window_count == 2U, "Expected RX1 + RX2 windows, observed %lu",
               (unsigned long)g_hil.rx_window_count);
    HIL_ASSERT(g_hil.rfsw_rx_during_rx[0] && g_hil.rfsw_rx_during_rx[1],
               "RF switch not set to ISAC_RFSW_RX (PA0=1, PA1=0) during RX1/RX2");
    HIL_ASSERT(labs((long)g_hil.rx_window_freqs_hz[0] - (long)ISAC_EU868_CH0_HZ) <= 5L,
               "RX1 frequency != TX channel 868.1 MHz");
    HIL_ASSERT(labs((long)g_hil.rx_window_freqs_hz[1] - (long)ISAC_EU868_RX2_HZ) <= 5L,
               "RX2 frequency != 869.525 MHz");
    HIL_ASSERT((g_hil.rx_window_open_ms[0] >= (1000UL + 57UL + 1000UL - ISAC_LORAWAN_RX_EARLY_OPEN_MS)) &&
               (g_hil.rx_window_open_ms[0] <= (1000UL + 57UL + 1000UL)) &&
               (g_hil.rx_window_open_ms[1] >= (1000UL + 57UL + 2000UL - ISAC_LORAWAN_RX_EARLY_OPEN_MS)) &&
               (g_hil.rx_window_open_ms[1] <= (1000UL + 57UL + 2000UL)),
               "RX1/RX2 early-open RECEIVE_DELAY1 (+1s - 15ms) / RECEIVE_DELAY2 (+2s - 15ms) timing violated (%lu, %lu)",
               (unsigned long)g_hil.rx_window_open_ms[0], (unsigned long)g_hil.rx_window_open_ms[1]);
    HIL_ASSERT(g_hil.rf_sw_mode == ISAC_RFSW_OFF,
               "RF switch not returned to ISAC_RFSW_OFF before STOP2");

    /* Decrypt captured 23-byte PHY frame in `g_hil.tx_fifo` and verify exact MIC + FPort 10 recovery */
    const uint8_t *phy = g_hil.tx_fifo;
    HIL_ASSERT(phy[0] == ISAC_LORAWAN_MHDR_UNCONF_DATA_UP && phy[8] == ISAC_LORAWAN_FPORT,
               "PHY MHDR (0x40) or FPort (10) mismatch");
    const uint32_t calc_mic = ISAC_LoRaWAN_ComputeDataMIC(k_nist_key, 0x26011868UL, 0U, 0UL, phy, 19U);
    const uint32_t wire_mic = ((uint32_t)phy[19]) | ((uint32_t)phy[20] << 8U) |
                              ((uint32_t)phy[21] << 16U) | ((uint32_t)phy[22] << 24U);
    HIL_ASSERT(calc_mic == wire_mic, "LoRaWAN 32-bit CMAC MIC mismatch!");

    uint8_t dec_payload[10];
    ISAC_LoRaWAN_CryptPayload(k_app_skey, 0x26011868UL, 0U, 0UL, &phy[9], dec_payload, 10U);
    HIL_ASSERT(memcmp(dec_payload, app_fport10, 10U) == 0,
               "Encrypted FPort 10 payload failed AES-128 CTR round-trip decryption!");
    HIL_ASSERT(memcmp(&phy[9], app_fport10, 10U) != 0,
               "FPort 10 payload was sent unencrypted!");
}

static isac_nvm_session_t g_hil_saved_sess;
static uint32_t           g_hil_persist_calls = 0U;

static void hil_persist_session_cb(const isac_lorawan_ctx_t *ctx)
{
    ISAC_LoRaWAN_SaveToNvmSession(ctx, &g_hil_saved_sess);
    g_hil_persist_calls++;
}

static void test_reve3_rx2_sf12_brownout_etsi0p1_and_tare(void)
{
    printf("[6/6] Verifying Rev E.3 Closures: 1,810 ms SF12 RX2 JoinAccept/Downlink, Pre-Sweep Guards & Tare...\n");

    /* (A) 1,810 ms SF12BW125 33-byte JoinAccept (CFList + RxDelay=5s + DLSettings=0x13) on RX2 */
    static const uint8_t k_app_key[16] = {
        0x2BU,0x7EU,0x15U,0x16U,0x28U,0xAEU,0xD2U,0xA6U,
        0xABU,0xF7U,0x15U,0x88U,0x09U,0xCFU,0x4FU,0x3CU
    };
    static const uint8_t k_join_eui[8] = { 0x70U,0xB3U,0xD5U,0x7EU,0xD0U,0x06U,0x86U,0x80U };
    static const uint8_t k_join_accept_cf33[33] = {
        0x20U, 0x9AU, 0x7FU, 0x87U, 0xE3U, 0x68U, 0x13U, 0x37U,
        0xEBU, 0x79U, 0x7BU, 0x4BU, 0x94U, 0x18U, 0xEEU, 0x53U,
        0x34U, 0x75U, 0x0FU, 0x91U, 0x62U, 0xB0U, 0x74U, 0xF4U,
        0xD1U, 0xEBU, 0xF5U, 0xABU, 0xC5U, 0xF4U, 0x64U, 0x16U,
        0xB3U
    };

    uint8_t dev_eui[8];
    isac_lorawan_ctx_t otaa_ctx;
    ISAC_HAL_ReadUniqueId64(dev_eui);
    ISAC_LoRaWAN_InitOTAA(&otaa_ctx, dev_eui, k_join_eui, k_app_key);
    otaa_ctx.persist_cb = hil_persist_session_cb;

    memset(&g_hil_saved_sess, 0, sizeof(g_hil_saved_sess));
    g_hil_persist_calls = 0U;
    memset(&g_hil, 0, sizeof(g_hil));
    hil_reset_trace();
    g_hil.sim_tick_ms      = 500UL;
    memcpy(&g_hil.rx_fifo[0x80U], k_join_accept_cf33, 33U);
    g_hil.staged_rx_len    = 33U;
    g_hil.stage_rx_on_rx2  = true;
    g_hil.staged_rx_toa_ms = 1810UL; /* Full 1,810 ms SF12BW125 JoinAccept flight */

    const bool jok = ISAC_LoRaWAN_JoinOTAA(&otaa_ctx);
    HIL_ASSERT(jok && otaa_ctx.joined,
               "1,810 ms SF12BW125 RX2 JoinAccept failed!");
    HIL_ASSERT(g_hil.stop_rx_timer_on_preamble,
               "SetStopRxTimerOnPreamble(0x9F, 0x01) was not issued before SET_RX!");
    HIL_ASSERT(g_hil.last_rx_search_timeout_ms >= 325UL,
               "SF12 symbol-search timeout %lu ms < 325 ms (10 * T_sym)",
               (unsigned long)g_hil.last_rx_search_timeout_ms);
    HIL_ASSERT(otaa_ctx.dev_addr == 0x26018683UL &&
               otaa_ctx.rx1_delay_ms == 5000U &&
               otaa_ctx.rx1_dr_offset == 1U &&
               otaa_ctx.rx2_sf == 9U &&
               otaa_ctx.num_channels == 8U &&
               otaa_ctx.channel_hz[7] == 867900000UL,
               "JoinAccept CFList / RxDelay=5s / DLSettings not parsed!");

    /* Simulate MCU power-cycle reset and restore full session from `g_hil_saved_sess` */
    isac_lorawan_ctx_t reboot_ctx;
    ISAC_LoRaWAN_InitOTAA(&reboot_ctx, dev_eui, k_join_eui, k_app_key);
    reboot_ctx.persist_cb = hil_persist_session_cb;
    ISAC_LoRaWAN_RestoreFromNvmSession(&reboot_ctx, &g_hil_saved_sess);
    HIL_ASSERT(reboot_ctx.joined &&
               reboot_ctx.rx1_delay_ms == 5000U &&
               reboot_ctx.rx1_dr_offset == 1U &&
               reboot_ctx.rx2_sf == 9U &&
               reboot_ctx.num_channels == 8U &&
               reboot_ctx.channel_hz[3] == 867100000UL &&
               reboot_ctx.channel_hz[7] == 867900000UL,
               "CFList + RxDelay=5s lost across simulated MCU reset!");

    /* Also verify 1,810 ms Confirmed Data Downlink on RX2 persists `fcnt_down` & `pending_ack` */
    reboot_ctx.rx2_sf = 12U;
    uint8_t dl_phy[16] = { 0U };
    dl_phy[0] = ISAC_LORAWAN_MHDR_CONF_DATA_DOWN;
    dl_phy[1] = 0x83U; dl_phy[2] = 0x86U; dl_phy[3] = 0x01U; dl_phy[4] = 0x26U;
    dl_phy[5] = 0x00U; /* FCtrl */
    dl_phy[6] = 0x07U; dl_phy[7] = 0x00U; /* FCntDown = 7 */
    const uint32_t dl_mic = ISAC_LoRaWAN_ComputeDataMIC(reboot_ctx.nwk_skey, 0x26018683UL, 1U, 7UL, dl_phy, 8U);
    dl_phy[8]  = (uint8_t)(dl_mic & 0xFFU);
    dl_phy[9]  = (uint8_t)((dl_mic >> 8U) & 0xFFU);
    dl_phy[10] = (uint8_t)((dl_mic >> 16U) & 0xFFU);
    dl_phy[11] = (uint8_t)((dl_mic >> 24U) & 0xFFU);

    hil_reset_trace();
    memcpy(&g_hil.rx_fifo[0x80U], dl_phy, 12U);
    g_hil.staged_rx_len    = 12U;
    g_hil.stage_rx_on_rx2  = true;
    g_hil.staged_rx_toa_ms = 1810UL;
    const uint32_t persist_before_dl = g_hil_persist_calls;
    const uint8_t dummy_ul[10] = { 0x80U };
    HIL_ASSERT(ISAC_LoRaWAN_SendClassA(&reboot_ctx, ISAC_LORAWAN_FPORT, dummy_ul, 10U, NULL) == ISAC_LORAWAN_TX_OK,
               "SendClassA with 1,810 ms SF12 RX2 Confirmed Downlink failed!");
    HIL_ASSERT(g_hil_persist_calls >= (persist_before_dl + 2U) &&
               g_hil_saved_sess.fcnt_down == 8UL &&
               g_hil_saved_sess.pending_ack == 1U,
               "Confirmed downlink did not persist fcnt_down=8 & pending_ack=1 to NVM!");
    g_hil.staged_rx_len    = 0U;
    g_hil.staged_rx_toa_ms = 0UL;

    /* (B) Passive pre-sweep VBAT brownout guard + 0.1% 863.1 MHz duty guard (0 CW TX) */
    hil_reset_trace();
    g_hil.vdda_true_100uv = 33000UL;
    g_hil.vbat_true_mv    = 2890UL; /* Brownout < 3000 mV */
    g_hil.vrefint_cal     = 1650U;
    uint16_t pre_vbat = 0U, pre_vdda = 0U;
    HIL_ASSERT(ISAC_Acquire_Supply_Rails(&pre_vbat, &pre_vdda), "ISAC_Acquire_Supply_Rails failed");
    HIL_ASSERT(pre_vbat == 2890U && pre_vdda == 3300U,
               "ISAC_Acquire_Supply_Rails mismatch (%u, %u)", pre_vbat, pre_vdda);
    HIL_ASSERT(g_hil.cmd_count == 0U && g_hil.cw_trigger_count == 0U &&
               !g_hil.det_en_high && !g_hil.det_en_turned_on &&
               !g_hil.bat_mon_en_high && g_hil.bat_mon_en_was_high_at_adc,
               "Passive rail sense must gate Q2 via PA9 ONLY (PA8/LT5538 strictly OFF) & issue ZERO SPI/CW!");

    isac_duty_tracker_t dc01;
    ISAC_DutyCycle_Init(&dc01, 0UL);
    HIL_ASSERT(ISAC_DutyCycle_CanTransmitSubband0p1(&dc01, ISAC_TONE1_CW_AIRTIME_MS, 0UL),
               "Initial 0.1%% 863.1 MHz TX rejected");
    ISAC_DutyCycle_RecordSubband0p1AirTime(&dc01, ISAC_TONE1_CW_AIRTIME_MS, 0UL);
    HIL_ASSERT(!ISAC_DutyCycle_CanTransmitSubband0p1(&dc01, ISAC_TONE1_CW_AIRTIME_MS,
                                                     (ISAC_TONE1_CW_AIRTIME_MS * 1000UL) - 1UL) && dc01.throttled,
               "0.1%% 1000x backoff did not inhibit Tone 1!");
    HIL_ASSERT(ISAC_DutyCycle_CanTransmitSubband0p1(&dc01, ISAC_TONE1_CW_AIRTIME_MS,
                                                    ISAC_TONE1_CW_AIRTIME_MS * 1000UL),
               "0.1%% 1000x backoff did not release!");
    dc01.used_subband_0p1_ms = 3600UL;
    HIL_ASSERT(!ISAC_DutyCycle_CanTransmitSubband0p1(&dc01, 1UL, 5000UL) && dc01.throttled,
               "0.1%% 3,600 ms/hr 863.1 MHz cap did not inhibit sweep!");

    /* Verify +4 dBm CW sensing power vs +14 dBm restored LoRaWAN power */
    g_hil.vbat_true_mv       = 3700UL;
    g_hil.tone_vout_100uv[0] = 8180UL;
    g_hil.tone_vout_100uv[1] = 7588UL;
    g_hil.tone_vout_100uv[2] = 8837UL;
    hil_reset_trace();
    isac_raw_sweep_t sw_pwr = { 0 };
    HIL_ASSERT(ISAC_Acquire_3Tone_Sweep(&sw_pwr), "Sweep failed");
    HIL_ASSERT(g_hil.cw_tx_power_dbm[0] == ISAC_SENSING_TX_DBM &&
               g_hil.cw_tx_power_dbm[1] == ISAC_SENSING_TX_DBM &&
               g_hil.cw_tx_power_dbm[2] == ISAC_SENSING_TX_DBM &&
               g_hil.last_tx_power_dbm  == ISAC_LORAWAN_TX_DBM &&
               ISAC_SENSING_TX_DBM      == 4,
               "Expected +4 dBm CW sweep and +14 dBm restored LoRaWAN power (got %d / %d)",
               (int)g_hil.cw_tx_power_dbm[0], (int)g_hil.last_tx_power_dbm);

    /* (C) Per-unit factory dry-air leakage power tare (`ISAC_Sensing_SetCalibration`) */
    isac_raw_sweep_t sw_off_air = sw_pwr;
    sw_off_air.det_100uv[0] = 10450UL; sw_off_air.det_mv[0] = 1045U;
    sw_off_air.det_100uv[1] = 10620UL; sw_off_air.det_mv[1] = 1062U;
    sw_off_air.det_100uv[2] = 10380UL; sw_off_air.det_mv[2] = 1038U;
    isac_telemetry_t tel_uncal = { 0 }, tel_cal = { 0 };
    ISAC_Sensing_SetCalibration(NULL, false);
    ISAC_Extract_Features_And_Classify(&sw_off_air, &tel_uncal);
    HIL_ASSERT(tel_uncal.state != ISAC_SURFACE_DRY_AIR,
               "Expected uncalibrated +3sigma board to fail dry-air notch without tare");

    const uint16_t unit_tare_mv[3] = { 1045U, 1062U, 1038U };
    ISAC_Sensing_SetCalibration(unit_tare_mv, true);
    ISAC_Extract_Features_And_Classify(&sw_off_air, &tel_cal);
    HIL_ASSERT(tel_cal.state == ISAC_SURFACE_DRY_AIR && tel_cal.notch_db_x100 >= 450,
               "Factory dry-air tare failed to restore Dry Air notch (%d cB, state=%s)",
               tel_cal.notch_db_x100, state_name(tel_cal.state));
    ISAC_Sensing_SetCalibration(NULL, false);
}

static void test_reve4_remediation_suite(void)
{
    printf("[7/7] Verifying Rev E.4 Closures: CLKDE Readback/USE_LDO, NSS Wakeup, Bidirectional Tare, Die-Temp, Join 1%% & Wet SF12...\n");

    /* (1) CLKDE readback failure MUST NOT assert PWR_CR5_SMPSEN and MUST fall back to USE_LDO (0x00) */
    memset(&g_hil, 0, sizeof(g_hil));
    hil_reset_trace();
    g_hil.inject_clkde_readback_zero = true;
    HIL_ASSERT(!ISAC_Init_Radio_And_SMPS(),
               "ISAC_Init_Radio_And_SMPS() must return false when SMPSC0R.CLKDE readback == 0");
    HIL_ASSERT(!g_hil.smps_hw_cr5_enabled,
               "PWR_CR5_SMPSEN was asserted despite CLKDE readback == 0!");
    bool saw_use_ldo = false;
    bool saw_use_dcdc_bad = false;
    for (uint32_t i = 0U; i < g_hil.cmd_count; ++i) {
        const hil_subghz_cmd_t *c = &g_hil.cmd_log[i];
        if ((c->opcode == ISAC_SUBGHZ_CMD_SET_REGULATOR_MODE) && (c->len == 1U)) {
            if (c->params[0] == ISAC_SUBGHZ_REGMODE_USE_LDO)  { saw_use_ldo = true; }
            if (c->params[0] == ISAC_SUBGHZ_REGMODE_USE_DCDC) { saw_use_dcdc_bad = true; }
        }
    }
    HIL_ASSERT(saw_use_ldo && !saw_use_dcdc_bad && !ISAC_Is_SMPS_Active(),
               "Radio did not fall back cleanly to SetRegulatorMode(USE_LDO = 0x00)!");
    g_hil.inject_clkde_readback_zero = false;

    /* (2) Warm-sleep NSS wakeup pulse before post-STOP2 SUBGHZSPI commands */
    HIL_ASSERT(ISAC_Init_Radio_And_SMPS(), "Recovery init failed");
    HIL_ASSERT(g_hil.radio_sleeping, "Radio should be parked in SET_SLEEP after init");
    g_hil.wakeup_nss_pulses          = 0U;
    g_hil.woke_before_post_sleep_spi = false;
    g_hil.vdda_true_100uv            = 33000UL;
    g_hil.vbat_true_mv               = 3700UL;
    g_hil.vrefint_cal                = 1650U;
    g_hil.tone_vout_100uv[0]         = 8180UL;
    g_hil.tone_vout_100uv[1]         = 7588UL;
    g_hil.tone_vout_100uv[2]         = 8837UL;
    isac_raw_sweep_t sw_wake = { 0 };
    HIL_ASSERT(ISAC_Acquire_3Tone_Sweep(&sw_wake), "Post-sleep sweep failed");
    HIL_ASSERT(g_hil.wakeup_nss_pulses >= 1U && g_hil.woke_before_post_sleep_spi,
               "Missing NSS wakeup pulse before post-sleep SUBGHZSPI transaction!");
    HIL_ASSERT(sw_wake.tone_cw_ms[0] >= ISAC_TONE1_CW_AIRTIME_MS,
               "Per-tone measured CW airtime %u ms < %lu ms",
               sw_wake.tone_cw_ms[0], (unsigned long)ISAC_TONE1_CW_AIRTIME_MS);

    /* (3) Bidirectional factory dry-air tare for -3sigma negative excursion (f1 < nom) */
    isac_raw_sweep_t sw_neg_air = sw_wake;
    sw_neg_air.det_100uv[0] = 6700UL; sw_neg_air.det_mv[0] = 670U; /* Null shifted to f1 < 818.0 mV */
    sw_neg_air.det_100uv[1] = 8800UL; sw_neg_air.det_mv[1] = 880U;
    sw_neg_air.det_100uv[2] = 9100UL; sw_neg_air.det_mv[2] = 910U;
    isac_telemetry_t tel_neg_uncal = { 0 }, tel_neg_cal = { 0 };
    ISAC_Sensing_SetCalibration(NULL, false);
    ISAC_Extract_Features_And_Classify(&sw_neg_air, &tel_neg_uncal);
    HIL_ASSERT(tel_neg_uncal.state != ISAC_SURFACE_DRY_AIR,
               "Expected uncalibrated -3sigma board to fail dry-air notch");

    const uint16_t neg_tare_mv[3] = { 670U, 880U, 910U };
    ISAC_Sensing_SetCalibration(neg_tare_mv, true);
    ISAC_Extract_Features_And_Classify(&sw_neg_air, &tel_neg_cal);
    HIL_ASSERT(tel_neg_cal.state == ISAC_SURFACE_DRY_AIR && tel_neg_cal.notch_db_x100 >= 450,
               "Bidirectional negative dry-air tare failed (notch=%d cB, state=%s)!",
               tel_neg_cal.notch_db_x100, state_name(tel_neg_cal.state));
    ISAC_Sensing_SetCalibration(NULL, false);

    /* (4) Die-temperature warm-dew (+20 C) vs sub-zero glaze-ice (-5 C) disambiguation */
    isac_raw_sweep_t sw_ice = sw_wake;
    sw_ice.det_100uv[0] = 11435UL; sw_ice.det_mv[0] = 1144U;
    sw_ice.det_100uv[1] = 11425UL; sw_ice.det_mv[1] = 1143U;
    sw_ice.det_100uv[2] = 11437UL; sw_ice.det_mv[2] = 1144U;
    isac_telemetry_t tel_warm_dew = { 0 }, tel_subzero_ice = { 0 };
    ISAC_Extract_Features_And_Classify_WithTemp(&sw_ice, +200, &tel_warm_dew);    /* +20.0 C */
    ISAC_Extract_Features_And_Classify_WithTemp(&sw_ice, -50,  &tel_subzero_ice); /*  -5.0 C */
    HIL_ASSERT(tel_warm_dew.state == ISAC_SURFACE_LIQUID_WATER,
               "+20.0 C partial dew falsely classified as %s instead of LIQUID_WATER!",
               state_name(tel_warm_dew.state));
    HIL_ASSERT(tel_subzero_ice.state == ISAC_SURFACE_GLAZE_ICE,
               "-5.0 C glaze ice failed to classify as GLAZE_ICE (%s)!",
               state_name(tel_subzero_ice.state));
    HIL_ASSERT(tel_warm_dew.tilt_db_x100 == tel_subzero_ice.tilt_db_x100 &&
               tel_warm_dew.notch_db_x100 == tel_subzero_ice.notch_db_x100,
               "Temperature intercept compensation perturbed differential Tilt/Notch!");

    /* (5) SX1262 0x0736/0x0889 workarounds + Post-Join 1% Off-Time + §7 Join Back-Off */
    static const uint8_t k_app_key[16] = {
        0x2BU,0x7EU,0x15U,0x16U,0x28U,0xAEU,0xD2U,0xA6U,
        0xABU,0xF7U,0x15U,0x88U,0x09U,0xCFU,0x4FU,0x3CU
    };
    static const uint8_t k_join_eui[8] = { 0x70U,0xB3U,0xD5U,0x7EU,0xD0U,0x06U,0x86U,0x80U };
    static const uint8_t k_join_accept_cf33[33] = {
        0x20U, 0x9AU, 0x7FU, 0x87U, 0xE3U, 0x68U, 0x13U, 0x37U,
        0xEBU, 0x79U, 0x7BU, 0x4BU, 0x94U, 0x18U, 0xEEU, 0x53U,
        0x34U, 0x75U, 0x0FU, 0x91U, 0x62U, 0xB0U, 0x74U, 0xF4U,
        0xD1U, 0xEBU, 0xF5U, 0xABU, 0xC5U, 0xF4U, 0x64U, 0x16U,
        0xB3U
    };
    uint8_t dev_eui[8];
    ISAC_HAL_ReadUniqueId64(dev_eui);

    /* 5a: Failed Join must enforce >= 36 s LoRaWAN 1.0.3 §7 backoff and block immediate retry */
    isac_lorawan_ctx_t backoff_ctx;
    ISAC_LoRaWAN_InitOTAA(&backoff_ctx, dev_eui, k_join_eui, k_app_key);
    hil_reset_trace();
    g_hil.sim_tick_ms   = 1000UL;
    g_hil.staged_rx_len = 0U; /* Timeout both RX1 & RX2 */
    HIL_ASSERT(!ISAC_LoRaWAN_JoinOTAA(&backoff_ctx), "Unanswered JoinOTAA should return false");
    HIL_ASSERT(backoff_ctx.join_attempts == 1U && backoff_ctx.next_join_allowed_ms >= (1057UL + 36000UL),
               "Missing >= 36 s JoinRequest retransmission backoff (%lu ms)",
               (unsigned long)backoff_ctx.next_join_allowed_ms);
    hil_reset_trace();
    HIL_ASSERT(!ISAC_LoRaWAN_JoinOTAA(&backoff_ctx) && g_hil.cmd_count == 0U,
               "Immediate JoinOTAA retry before backoff expiry was NOT blocked!");

    /* 5b: Successful RX1 JoinAccept (+5.06 s) inside SendClassA() MUST wait until t_join_end + 6,200 ms (1% off-time) */
    isac_lorawan_ctx_t rx1_join_ctx;
    ISAC_LoRaWAN_InitOTAA(&rx1_join_ctx, dev_eui, k_join_eui, k_app_key);
    hil_reset_trace();
    g_hil.saw_iq_std_on_ul = false;
    g_hil.saw_iq_inv_on_dl = false;
    g_hil.tx_mod_reg       = 0U;
    g_hil.sim_tick_ms      = 2000UL;
    memcpy(&g_hil.rx_fifo[0x80U], k_join_accept_cf33, 33U);
    g_hil.staged_rx_len    = 33U;
    g_hil.stage_rx_on_rx2  = false;  /* Arrive on RX1 @ +5.0 s (< 6.2 s 1% off-time) */
    g_hil.staged_rx_toa_ms = 62UL;
    const uint8_t ul_frame[10] = { 0x90U, 0U, 171U, 0xEEU, 0x02U, 0U, 100U, 0x0EU, 0x74U, 103U };
    uint32_t ul_toa = 0UL;
    HIL_ASSERT(ISAC_LoRaWAN_SendClassA(&rx1_join_ctx, ISAC_LORAWAN_FPORT, ul_frame, 10U, &ul_toa) == ISAC_LORAWAN_TX_OK,
               "SendClassA with RX1 OTAA Join failed");
    /* Join TX ends at 2000 + 57 = 2057 ms -> min DataUp TX start = 2057 + 6200 = 8257 ms -> DataUp TX ends >= 8314 ms */
    HIL_ASSERT(g_hil.tx_done_at_ms >= (2057UL + 6200UL + 57UL),
               "First DataUp violated EU868 1%% post-Join off-time (tx_done_at=%lu ms < 8314 ms)!",
               (unsigned long)g_hil.tx_done_at_ms);
    HIL_ASSERT(g_hil.saw_iq_std_on_ul && g_hil.saw_iq_inv_on_dl && ((g_hil.tx_mod_reg & 0x04U) != 0U),
               "SX1262 0x0736 IQ polarity or 0x0889 BW125 TxModulation workaround missing!");

    /* (6) Adaptive SF12 (DR0) under wet/IPA radome & SF9 (DR3, 86% energy saving) under Glaze Ice */
    isac_duty_tracker_t dc_sf;
    ISAC_DutyCycle_Init(&dc_sf, 0UL);
    HIL_ASSERT(ISAC_Select_Uplink_SF(ISAC_SURFACE_DRY_AIR, &dc_sf, 0UL, 4UL) == 7U &&
               ISAC_Select_Uplink_SF(ISAC_SURFACE_OIL, &dc_sf, 0UL, 4UL) == 7U,
               "Dry Air / Oil should remain on SF7BW125 (DR5)");
    HIL_ASSERT(ISAC_Select_Uplink_SF(ISAC_SURFACE_GLAZE_ICE, &dc_sf, 0UL, 4UL) == 9U,
               "Glaze Ice should step uplink to SF9BW125 (DR3, 206 ms ToA per rf_link_budget.md)!");
    HIL_ASSERT(ISAC_Select_Uplink_SF(ISAC_SURFACE_LIQUID_WATER, &dc_sf, 0UL, 4UL) == 12U &&
               ISAC_Select_Uplink_SF(ISAC_SURFACE_IPA, &dc_sf, 0UL, 4UL) == 12U,
               "Wet/IPA radome did not step uplink to SF12BW125 (DR0, +12.5 dB gain)!");
    dc_sf.used_airtime_ms = 35000UL; /* Only 1,000 ms left in 1-hour 1% budget (< 1,483 ms SF12, > 371 ms SF10) */
    HIL_ASSERT(ISAC_Select_Uplink_SF(ISAC_SURFACE_LIQUID_WATER, &dc_sf, 0UL, 4UL) == 10U,
               "Duty-constrained wet fallback should step to SF10 (371 ms) when SF12 exceeds cap");
}

static void test_reve5_remediation_suite(void)
{
    printf("[8/8] Verifying Rev E.5 Closures: 2-Point Calibrated Water/IPA Separation (>= 0.50 dB), PA9 Q2 Split & +4 dBm Headroom...\n");

    /* Verify 2-point factory calibration (dry tare + reference intercept offset cal_ref_cdb)
     * achieves >= 0.50 dB (50 cB) separation margin between LIQUID_WATER (-26.35 dBm) and IPA (-27.75 dBm)
     * across +/-2.00 dB (+/-200 cdb) LT5538 log-intercept / PA output tolerance */
    const int16_t shifts_cdb[3] = { 0, +200, -200 };
    const uint16_t nom_dry_mv[3] = { 818U, 759U, 884U };

    memset(&g_hil, 0, sizeof(g_hil));
    hil_reset_trace();
    HIL_ASSERT(ISAC_Init_Radio_And_SMPS(), "Rev E.5 init failed");
    g_hil.vdda_true_100uv = 33000UL;
    g_hil.vbat_true_mv    = 3650UL;
    g_hil.vrefint_cal     = 1650U;

    for (uint32_t s = 0U; s < 3U; ++s) {
        const int16_t d_cdb = shifts_cdb[s];
        const int32_t dv_u100 = ((int32_t)d_cdb * 19) / 10;
        const uint16_t unit_dry_mv[3] = {
            (uint16_t)((int32_t)nom_dry_mv[0] + (dv_u100 / 10)),
            (uint16_t)((int32_t)nom_dry_mv[1] + (dv_u100 / 10)),
            (uint16_t)((int32_t)nom_dry_mv[2] + (dv_u100 / 10))
        };
        isac_raw_sweep_t sw_w = { 0 }, sw_ipa = { 0 };
        isac_telemetry_t tel_w = { 0 }, tel_ipa = { 0 };

        ISAC_Sensing_SetCalibration2Pt(unit_dry_mv, true, d_cdb, true);

        /* Water film @ +4.0 dBm: [1.1984, 1.1860, 1.1751] V + unit intercept shift */
        g_hil.tone_vout_100uv[0] = (uint32_t)(11984 + dv_u100);
        g_hil.tone_vout_100uv[1] = (uint32_t)(11860 + dv_u100);
        g_hil.tone_vout_100uv[2] = (uint32_t)(11751 + dv_u100);
        HIL_ASSERT(ISAC_Acquire_3Tone_Sweep(&sw_w), "Water sweep failed");
        ISAC_Extract_Features_And_Classify(&sw_w, &tel_w);

        /* IPA @ +4.0 dBm: [1.1739, 1.1595, 1.1463] V + unit intercept shift */
        g_hil.tone_vout_100uv[0] = (uint32_t)(11739 + dv_u100);
        g_hil.tone_vout_100uv[1] = (uint32_t)(11595 + dv_u100);
        g_hil.tone_vout_100uv[2] = (uint32_t)(11463 + dv_u100);
        HIL_ASSERT(ISAC_Acquire_3Tone_Sweep(&sw_ipa), "IPA sweep failed");
        ISAC_Extract_Features_And_Classify(&sw_ipa, &tel_ipa);

        const int32_t lvl_cal_w   = (int32_t)tel_w.level_dbm_x100   - (int32_t)d_cdb;
        const int32_t lvl_cal_ipa = (int32_t)tel_ipa.level_dbm_x100 - (int32_t)d_cdb;
        const int32_t sep_cdb     = lvl_cal_w - lvl_cal_ipa;
        HIL_ASSERT(tel_w.state == ISAC_SURFACE_LIQUID_WATER &&
                   tel_ipa.state == ISAC_SURFACE_IPA &&
                   (lvl_cal_w - (-2705)) >= 50 &&
                   ((-2705) - lvl_cal_ipa) >= 50 &&
                   sep_cdb >= 130,
                   "(d_cdb=%+d) — Water/IPA cal separation failed (w=%s %d cdb, ipa=%s %d cdb, sep=%d cdb)",
                   (int)d_cdb, state_name(tel_w.state), (int)lvl_cal_w,
                   state_name(tel_ipa.state), (int)lvl_cal_ipa, (int)sep_cdb);
    }
    ISAC_Sensing_SetCalibration2Pt(NULL, false, 0, false);
}

static void test_principal_audit_closures(const benchmark_curve_t *curves, uint32_t num_curves)
{
    printf("[9/9] Verifying LoRaWAN 1.0.3 §7 24h Sliding-Window Join Backoff & Monotonic eps_est_x100...\n");

    /* 1. Exhaustive 96-hour sliding-window JoinRequest airtime audit across SF7, SF9, SF10, SF12 */
    {
        static const uint8_t k_sfs[4] = { 7U, 9U, 10U, 12U };
        for (uint32_t s = 0U; s < 4U; ++s) {
            const uint8_t  sf     = k_sfs[s];
            const uint32_t toa_ms = ISAC_LoRaWAN_CalcTimeOnAirMs(sf, ISAC_LORAWAN_JOIN_REQ_PHY_LEN);
            uint64_t tx_start_ms[128];
            uint32_t n_tx = 0U;
            uint64_t t_ms = 0ULL;

            while ((t_ms < (96ULL * 3600000ULL)) && (n_tx < 128U)) {
                tx_start_ms[n_tx] = t_ms;
                const uint32_t attempt = n_tx + 1U;
                const uint32_t bo_ms   = ISAC_LoRaWAN_NextJoinBackoffMs(attempt, toa_ms);
                n_tx++;
                t_ms += (uint64_t)toa_ms + (uint64_t)bo_ms;
            }

            /* (a) Hour 1 [0, 3,600,000 ms): < 36,000 ms AND attempt 11 MUST NOT transmit inside Hour 1 */
            uint32_t h1_airtime_ms = 0UL;
            for (uint32_t k = 0U; k < n_tx; ++k) {
                if (tx_start_ms[k] < 3600000ULL) {
                    h1_airtime_ms += toa_ms;
                }
            }
            HIL_ASSERT(h1_airtime_ms < 36000UL && (n_tx <= 10U || tx_start_ms[10] >= 3600000ULL),
                       "(SF%u, ToA=%lu ms) — Hour-1 airtime=%lu ms or Tier-2 bled into Hour 1 (t11=%llu ms)",
                       sf, (unsigned long)toa_ms, (unsigned long)h1_airtime_ms,
                       (unsigned long long)((n_tx > 10U) ? tx_start_ms[10] : 0ULL));

            /* (b) Hours 1..11 [3,600,000, 39,600,000 ms): < 36,000 ms AND attempt 21 MUST NOT bleed into [3.6M, 39.6M) */
            uint32_t h10_airtime_ms = 0UL;
            for (uint32_t k = 0U; k < n_tx; ++k) {
                if ((tx_start_ms[k] >= 3600000ULL) && (tx_start_ms[k] < 39600000ULL)) {
                    h10_airtime_ms += toa_ms;
                }
            }
            HIL_ASSERT(h10_airtime_ms < 36000UL && (n_tx <= 20U || tx_start_ms[20] >= 39600000ULL),
                       "(SF%u, ToA=%lu ms) — 10-hour Tier-2 airtime=%lu ms >= 36,000 ms",
                       sf, (unsigned long)toa_ms, (unsigned long)h10_airtime_ms);

            /* (c) Every 24-hour sliding window [t_i, t_i + 86,400,000 ms) starting in Tier 3 (i >= 20): strictly < 8,700 ms */
            uint32_t max_24h_airtime_ms = 0UL;
            for (uint32_t i = 20U; i < n_tx; ++i) {
                const uint64_t win_end = tx_start_ms[i] + 86400000ULL;
                uint32_t win_airtime = 0UL;
                for (uint32_t j = i; (j < n_tx) && (tx_start_ms[j] < win_end); ++j) {
                    win_airtime += toa_ms;
                }
                if (win_airtime > max_24h_airtime_ms) {
                    max_24h_airtime_ms = win_airtime;
                }
            }
            HIL_ASSERT(max_24h_airtime_ms > 0UL && max_24h_airtime_ms < 8700UL,
                       "(SF%u, ToA=%lu ms) — Tier-3 24h sliding-window airtime %lu ms >= 8,700 ms limit!",
                       sf, (unsigned long)toa_ms, (unsigned long)max_24h_airtime_ms);
        }
    }

    /* 2. Verify strictly monotonic eps_est_x100 across tilt (-500..+300 cB) & all FDTD media */
    {
        uint16_t prev_eps = 0U;
        bool monotonic_ok = true;
        /* Enable 2-point calibrated mode (ref offset = 0 cdb) at dielectric level (< -26.94 dBm water knee)
         * so estimate_loaded_eps_x100(tilt_x100) is directly exercised across [-500 .. +300] cB */
        ISAC_Sensing_SetCalibration2Pt(NULL, false, 0, true);
        for (int32_t tilt = -500; tilt <= 300; tilt += 5) {
            isac_raw_sweep_t sw = { 0 };
            isac_telemetry_t tel = { 0 };
            const int32_t dv_u100 = (tilt * 19) / 10;
            sw.vbat_mv = 3650U;
            sw.vdda_mv = 3300U;
            sw.smps_dcdc_enabled = true;
            sw.det_100uv[1] = 11000UL;
            sw.det_100uv[2] = 11000UL;
            sw.det_100uv[0] = (uint32_t)(11000 + dv_u100);
            sw.det_mv[0] = (uint16_t)(sw.det_100uv[0] / 10UL);
            sw.det_mv[1] = 1100U;
            sw.det_mv[2] = 1100U;
            ISAC_Extract_Features_And_Classify_WithTemp(&sw, -50, &tel);
            if (tel.eps_est_x100 < prev_eps) {
                monotonic_ok = false;
            }
            prev_eps = tel.eps_est_x100;
        }
        ISAC_Sensing_SetCalibration2Pt(NULL, false, 0, false);
        HIL_ASSERT(monotonic_ok && prev_eps == 980U,
                   "estimate_loaded_eps_x100 non-monotonic or wrong upper knot (%u != 980)",
                   prev_eps);

        /* Verify every pair (a, b) of physical FDTD benchmark curves satisfies:
         * curves[a].eps_real < curves[b].eps_real => curve_eps[a] < curve_eps[b] (0 inversions) */
        uint16_t curve_eps[16] = { 0U };
        for (uint32_t idx = 0U; idx < num_curves; ++idx) {
            isac_raw_sweep_t sw_c = { 0 };
            isac_telemetry_t tel_c = { 0 };
            g_hil.vdda_true_100uv = 33000UL;
            g_hil.vbat_true_mv    = 3650UL;
            g_hil.vrefint_cal     = 1650U;
            for (uint32_t t = 0U; t < ISAC_NUM_TONES; ++t) {
                g_hil.tone_vout_100uv[t] = (uint32_t)llround(curves[idx].vout_v[t] * 10000.0);
            }
            ISAC_Acquire_3Tone_Sweep(&sw_c);
            ISAC_Extract_Features_And_Classify(&sw_c, &tel_c);
            curve_eps[idx] = tel_c.eps_est_x100;
        }
        bool pairs_monotonic = true;
        for (uint32_t a = 0U; a < num_curves; ++a) {
            for (uint32_t b = 0U; b < num_curves; ++b) {
                if ((curves[a].eps_real + 0.05) < curves[b].eps_real) {
                    if (curve_eps[a] >= curve_eps[b]) {
                        pairs_monotonic = false;
                    }
                }
            }
        }
        HIL_ASSERT(pairs_monotonic,
                   "FDTD media eps_est_x100 violated physical permittivity ordering!");
    }

    /* 3. 49.71-day (2^32 ms) & 24.85-day (2^31 ms) tick rollover immunity across 100 rollovers (>13.6 yrs) */
    {
        isac_duty_tracker_t dc_wrap;
        const uint32_t t_pre_wrap = 0xFFFE0000UL; /* 131.072 s before 2^32 rollover */

        ISAC_DutyCycle_Init(&dc_wrap, t_pre_wrap);
        ISAC_DutyCycle_RecordSubband0p1AirTime(&dc_wrap, 2UL, t_pre_wrap); /* min_next_0p1 = 0xFFFE07D0 */
        ISAC_DutyCycle_RecordAirTime(&dc_wrap, 61UL, t_pre_wrap);          /* min_next_tx  = 0xFFFE17D4 */

        /* Still inside backoff 500 ms later -> MUST reject */
        HIL_ASSERT(!ISAC_DutyCycle_CanTransmitSubband0p1(&dc_wrap, 2UL, t_pre_wrap + 500UL) &&
                   !ISAC_DutyCycle_CanTransmit(&dc_wrap, 61UL, t_pre_wrap + 500UL),
                   "Premature TX inside active pre-wrap backoff was not blocked");

        /* Next 15-minute STOP2 wakeup (+900,000 ms -> wraps modulo 2^32 to 0x000BBBA0) -> MUST allow TX */
        const uint32_t t_post_wrap = (uint32_t)(t_pre_wrap + 900000U);
        HIL_ASSERT(ISAC_DutyCycle_CanTransmitSubband0p1(&dc_wrap, 2UL, t_post_wrap) &&
                   ISAC_DutyCycle_CanTransmit(&dc_wrap, 61UL, t_post_wrap),
                   "49.71-day uint32_t tick rollover caused false duty-cycle radio blackout!");

        /* Cross-boundary backoff: TX at 0xFFFFFC18 (-1000 ms) -> 2000 ms backoff wraps to 0x000003E8 (+1000 ms) */
        const uint32_t t_straddle = 0xFFFFFC18UL;
        ISAC_DutyCycle_RecordSubband0p1AirTime(&dc_wrap, 2UL, t_straddle);
        HIL_ASSERT(!ISAC_DutyCycle_CanTransmitSubband0p1(&dc_wrap, 2UL, 0x00000100UL) &&
                   ISAC_DutyCycle_CanTransmitSubband0p1(&dc_wrap, 2UL, 0x000003E8UL),
                   "Backoff straddling 0xFFFFFFFF -> 0x000003E8 mishandled!");

        /* Multi-year 100-rollover (4,971 days > 13.6 years) + 35-day (> 24.85-day 2^31 ms) low-battery hibernation */
        isac_lorawan_ctx_t lw_wrap;
        uint8_t z8[8] = { 0 }, z16[16] = { 0 };
        uint32_t sim_ms = 0UL;
        bool multi_year_ok = true;

        ISAC_DutyCycle_Init(&dc_wrap, 0UL);
        ISAC_LoRaWAN_InitOTAA(&lw_wrap, z8, z8, z16);
        lw_wrap.join_attempts        = 5U;
        lw_wrap.next_join_allowed_ms = 36000UL;

        /* Simulate 35 days (3,360 x 900 s = 3,024,000,000 ms > 2^31 ms) of winter low-battery inhibit */
        for (uint32_t w = 0U; w < 3360U; ++w) {
            sim_ms += 900000UL;
            ISAC_DutyCycle_Tick(&dc_wrap, sim_ms);
            ISAC_LoRaWAN_TickBackoff(&lw_wrap, sim_ms);
        }
        if (!ISAC_DutyCycle_CanTransmitSubband0p1(&dc_wrap, 2UL, sim_ms) ||
            !ISAC_DutyCycle_CanTransmit(&dc_wrap, 65UL, sim_ms) ||
            ((int32_t)(sim_ms - lw_wrap.next_join_allowed_ms) < 0)) {
            multi_year_ok = false;
        }

        /* Continue across 100 full 49.71-day uint32_t rollovers (477,300 wakeups) of normal 15-min operation */
        for (uint32_t w = 0U; (w < 477300U) && multi_year_ok; ++w) {
            sim_ms += 900000UL;
            ISAC_DutyCycle_Tick(&dc_wrap, sim_ms);
            ISAC_LoRaWAN_TickBackoff(&lw_wrap, sim_ms);
            if (!ISAC_DutyCycle_CanTransmitSubband0p1(&dc_wrap, 2UL, sim_ms) ||
                !ISAC_DutyCycle_CanTransmit(&dc_wrap, 65UL, sim_ms)) {
                multi_year_ok = false;
                break;
            }
            ISAC_DutyCycle_RecordSubband0p1AirTime(&dc_wrap, 2UL, sim_ms);
            ISAC_DutyCycle_RecordAirTime(&dc_wrap, 65UL, sim_ms);
        }
        HIL_ASSERT(multi_year_ok,
                   "Multi-year 100-rollover + 35-day low-battery simulation suffered false blackout!");
    }
}

static void test_lbs_interference_blanking_and_soft_cw_quench(void)
{
    printf("[10/10] Verifying Rev E.5 Firmware Hardening: Listen-Before-Sense (LBS) RF Jammer Blanking & -9 dBm Soft-Ramp CW Quench...\n");

    memset(&g_hil, 0, sizeof(g_hil));
    hil_reset_trace();
    HIL_ASSERT(ISAC_Init_Radio_And_SMPS(), "LBS test init failed");

    g_hil.vdda_true_100uv        = 33000UL;
    g_hil.vbat_true_mv           = 3650UL;
    g_hil.vrefint_cal            = 1650U;
    g_hil.mock_die_temp_degc_x10 = -50; /* -5.0 C sub-zero glaze-ice regime */
    g_hil.tone_vout_100uv[0]     = 11435UL;
    g_hil.tone_vout_100uv[1]     = 11425UL;
    g_hil.tone_vout_100uv[2]     = 11437UL;

    /* 1. Quiet RF channel (140 mV TX-off floor <= 320 mV): verify soft-ramp -9 dBm quench on all 3 tones */
    {
        isac_raw_sweep_t sw = { 0 };
        isac_telemetry_t tel = { 0 };
        hil_reset_trace();
        HIL_ASSERT(ISAC_Acquire_3Tone_Sweep(&sw), "Quiet-channel sweep failed");
        ISAC_Extract_Features_And_Classify_WithTemp(&sw, sw.die_temp_degc_x10, &tel);

        HIL_ASSERT(!sw.lbs_jammed && sw.lbs_pre_mv == 140U && sw.lbs_post_mv == 140U,
                   "LBS quiet floor mismatch: jammed=%d pre=%u mV post=%u mV",
                   (int)sw.lbs_jammed, sw.lbs_pre_mv, sw.lbs_post_mv);
        HIL_ASSERT(g_hil.lbs_tx_off_samples == 2U,
                   "Expected exactly 2 TX-off LBS ADC checks (pre + post), got %u",
                   g_hil.lbs_tx_off_samples);
        HIL_ASSERT(g_hil.cw_soft_quench_count == ISAC_NUM_TONES,
                   "Soft-ramp -9 dBm CW quench (>=50 us before SET_STANDBY) observed %u/%u tones!",
                   g_hil.cw_soft_quench_count, ISAC_NUM_TONES);
        HIL_ASSERT(g_hil.delay_since_cw_off_us >= ISAC_LBS_DISCHARGE_US,
                   "Post-sweep LBS did not wait >= %lu us for C_LPF=100nF discharge (got %lu us)",
                   (unsigned long)ISAC_LBS_DISCHARGE_US, (unsigned long)g_hil.delay_since_cw_off_us);
        HIL_ASSERT(g_hil.last_tx_power_dbm == ISAC_LORAWAN_TX_DBM && tel.state == ISAC_SURFACE_GLAZE_ICE,
                   "Quiet sweep did not restore +14 dBm or classify GLAZE_ICE (%s)",
                   state_name(tel.state));
    }

    /* 2. Transient LTE/LoRa burst jammer (460 mV on 1st check, clears after 20 ms PA8=0 backoff -> recovers) */
    {
        isac_raw_sweep_t sw = { 0 };
        isac_telemetry_t tel = { 0 };
        const uint32_t t0_ms = g_hil.sim_tick_ms;
        hil_reset_trace();
        g_hil.ambient_pre_100uv           = 0UL;
        g_hil.jammer_pre_bursts_remaining = 1U; /* 1st check = 460 mV (> 320 mV), retry #1 = 140 mV */

        HIL_ASSERT(ISAC_Acquire_3Tone_Sweep(&sw), "Transient-jammer sweep failed");
        ISAC_Extract_Features_And_Classify_WithTemp(&sw, sw.die_temp_degc_x10, &tel);

        HIL_ASSERT(!sw.lbs_jammed && sw.lbs_pre_mv == 140U && sw.lbs_post_mv == 140U,
                   "Transient jammer did not recover cleanly on retry #1 (pre=%u, jammed=%d)",
                   sw.lbs_pre_mv, (int)sw.lbs_jammed);
        HIL_ASSERT((g_hil.sim_tick_ms - t0_ms) >= ISAC_LBS_BACKOFF_MS && g_hil.lbs_tx_off_samples == 3U,
                   "Expected 20 ms LBS backoff + 3 TX-off checks (2 pre + 1 post), dt=%lu ms samples=%u",
                   (unsigned long)(g_hil.sim_tick_ms - t0_ms), g_hil.lbs_tx_off_samples);
        HIL_ASSERT(tel.state == ISAC_SURFACE_GLAZE_ICE,
                   "Recovered sweep misclassified %s instead of GLAZE_ICE!", state_name(tel.state));
    }

    /* 3. Persistent external RF jammer (480 mV across all retries -> 0 CW transmitted, deterministic FAULT) */
    {
        isac_raw_sweep_t sw = { 0 };
        isac_telemetry_t tel = { 0 };
        const uint32_t t0_ms = g_hil.sim_tick_ms;
        hil_reset_trace();
        g_hil.ambient_pre_100uv = 4800UL; /* Continuous 480.0 mV (~-63.5 dBm) out-of-band LTE/GSM carrier */

        HIL_ASSERT(ISAC_Acquire_3Tone_Sweep(&sw), "Persistent-jammer LBS abort must still return radio_ok=true");
        ISAC_Extract_Features_And_Classify_WithTemp(&sw, sw.die_temp_degc_x10, &tel);

        HIL_ASSERT(sw.lbs_jammed && sw.lbs_pre_mv == 480U,
                   "Persistent jammer not flagged (lbs_jammed=%d, pre=%u mV)",
                   (int)sw.lbs_jammed, sw.lbs_pre_mv);
        HIL_ASSERT(g_hil.cw_trigger_count == 0U &&
                   sw.tone_cw_ms[0] == 0U && sw.tone_cw_ms[1] == 0U && sw.tone_cw_ms[2] == 0U,
                   "Persistent pre-sweep jammer MUST emit 0 ms RF airtime (cw_triggers=%u)!",
                   g_hil.cw_trigger_count);
        HIL_ASSERT((g_hil.sim_tick_ms - t0_ms) >= (ISAC_LBS_MAX_RETRIES * ISAC_LBS_BACKOFF_MS) &&
                   g_hil.lbs_tx_off_samples == (ISAC_LBS_MAX_RETRIES + 1U),
                   "Expected %u retries (%lu ms), got samples=%u dt=%lu ms",
                   ISAC_LBS_MAX_RETRIES, (unsigned long)(ISAC_LBS_MAX_RETRIES * ISAC_LBS_BACKOFF_MS),
                   g_hil.lbs_tx_off_samples, (unsigned long)(g_hil.sim_tick_ms - t0_ms));
        HIL_ASSERT(!g_hil.det_en_high && !g_hil.adc_enabled &&
                   tel.state == ISAC_SURFACE_FAULT && tel.eps_est_x100 == 0U,
                   "Persistent jammer failed to power down PA8/ADC or force ISAC_SURFACE_FAULT (%s)!",
                   state_name(tel.state));
        g_hil.ambient_pre_100uv = 0UL;
    }

    /* 4. Mid-sweep RF packet collision (quiet pre-sweep 140 mV, burst 450 mV on post-sweep check):
     *    Must preserve tone_cw_ms[0..2] >= 2 ms for ETSI duty-cycle accounting while forcing FAULT */
    {
        isac_raw_sweep_t sw = { 0 };
        isac_telemetry_t tel = { 0 };
        hil_reset_trace();
        g_hil.ambient_pre_100uv  = 0UL;
        g_hil.ambient_post_100uv = 4500UL; /* 450.0 mV packet collided mid-sweep */

        HIL_ASSERT(ISAC_Acquire_3Tone_Sweep(&sw), "Mid-sweep collision sweep failed");
        ISAC_Extract_Features_And_Classify_WithTemp(&sw, sw.die_temp_degc_x10, &tel);

        HIL_ASSERT(sw.lbs_jammed && sw.lbs_pre_mv == 140U && sw.lbs_post_mv == 450U,
                   "Mid-sweep collision not caught by post-sweep LBS (pre=%u, post=%u, jammed=%d)",
                   sw.lbs_pre_mv, sw.lbs_post_mv, (int)sw.lbs_jammed);
        HIL_ASSERT(sw.tone_cw_ms[0] >= ISAC_TONE1_CW_AIRTIME_MS &&
                   sw.tone_cw_ms[1] >= ISAC_TONE1_CW_AIRTIME_MS &&
                   sw.tone_cw_ms[2] >= ISAC_TONE1_CW_AIRTIME_MS,
                   "ETSI duty-cycle violation: mid-sweep collision must preserve emitted CW airtime!");
        HIL_ASSERT(tel.state == ISAC_SURFACE_FAULT && tel.eps_est_x100 == 0U,
                   "Mid-sweep RF collision corrupted detector voltage without forcing FAULT (%s)!",
                   state_name(tel.state));
        g_hil.ambient_post_100uv = 0UL;
    }
}

int main(int argc, char **argv)
{
    const char *json_path = "test/data/design_values.json";
    char rel_json_path[512];
    benchmark_curve_t curves[16];

    if (argc > 1) {
        json_path = argv[1];
    }

    uint32_t num_curves = load_design_values_curves(json_path, curves, 15U);
    if ((num_curves == 0U) && (argc <= 1)) {
        json_path  = "firmware/test/data/design_values.json";
        num_curves = load_design_values_curves(json_path, curves, 15U);
    }
    if ((num_curves == 0U) && (argc <= 1)) {
        const char *slash = strrchr(__FILE__, '/');
        if (slash != NULL) {
            const size_t dir_len = (size_t)(slash - __FILE__);
            if ((dir_len + 28U) < sizeof(rel_json_path)) {
                memcpy(rel_json_path, __FILE__, dir_len);
                strcpy(rel_json_path + dir_len, "/data/design_values.json");
                json_path  = rel_json_path;
                num_curves = load_design_values_curves(json_path, curves, 15U);
            }
        }
    }

    printf("================================================================================\n");
    printf("ISAC_868 Rev E.5 — Host HIL Firmware Verification Suite (RAK3172LP-SiP C11)\n");
    printf("================================================================================\n");
    printf("Loaded %u physical EM/bridge transfer curves from: %s\n", num_curves, json_path);

    HIL_ASSERT(num_curves >= 5U, "Failed to load >= 5 benchmark curves from %s", json_path);

    if (num_curves < 16U) {
        benchmark_curve_t *oil = &curves[num_curves++];
        strcpy(oil->name, "Mineral Oil");
        oil->eps_real       = 2.20;
        oil->vout_v[0]      = 1.0550;
        oil->vout_v[1]      = 1.0630;
        oil->vout_v[2]      = 1.0763;
        oil->tilt_db        = (1.0550 - 1.0763) / 0.019;
        oil->level_dbm      = (((1.0550 + 1.0630 + 1.0763) / 3.0) / 0.019) - 88.80;
        oil->expected_state = ISAC_SURFACE_OIL;
    }

    test_pin_map_and_smps_sequence();
    test_vrefint_droop_and_drift_and_classification(curves, num_curves);
    test_fport10_serialization_and_etsi_duty_cycle();
    test_lorawan_aes_cmac_otaa_and_class_a();
    test_reve3_rx2_sf12_brownout_etsi0p1_and_tare();
    test_reve4_remediation_suite();
    test_reve5_remediation_suite();
    test_principal_audit_closures(curves, num_curves);
    test_lbs_interference_blanking_and_soft_cw_quench();

    printf("--------------------------------------------------------------------------------\n");
    printf("HIL SUMMARY: %u assertions PASSED, %u FAILED\n", g_tests_passed, g_tests_failed);
    printf("================================================================================\n");

    return (g_tests_failed == 0U) ? 0 : 1;
}
