/**
 * @file isac_sensing.h
 * @brief 868 MHz 3-Tone ISAC Acquisition, Drift-Canceled Feature Extraction & LoRaWAN FPort 10 API
 */
#ifndef ISAC_SENSING_H
#define ISAC_SENSING_H

#include <stdbool.h>
#include <stdint.h>

/* =========================================================================
 * 1. STM32WLE5JC Internal SX1262 (SUBGHZ) Radio Opcodes & Parameters
 * ========================================================================= */
#define ISAC_SUBGHZ_CMD_CLEAR_IRQ_STATUS        0x02U
#define ISAC_SUBGHZ_CMD_SET_DIO_IRQ_PARAMS      0x08U
#define ISAC_SUBGHZ_CMD_WRITE_REGISTER          0x0DU
#define ISAC_SUBGHZ_CMD_WRITE_BUFFER            0x0EU
#define ISAC_SUBGHZ_CMD_GET_IRQ_STATUS          0x12U
#define ISAC_SUBGHZ_CMD_GET_RX_BUFFER_STATUS    0x13U
#define ISAC_SUBGHZ_CMD_GET_PACKET_STATUS       0x14U
#define ISAC_SUBGHZ_CMD_READ_REGISTER           0x1DU
#define ISAC_SUBGHZ_CMD_READ_BUFFER             0x1EU
#define ISAC_SUBGHZ_CMD_SET_STANDBY             0x80U
#define ISAC_SUBGHZ_CMD_SET_RX                  0x82U
#define ISAC_SUBGHZ_CMD_SET_TX                  0x83U
#define ISAC_SUBGHZ_CMD_SET_SLEEP               0x84U
#define ISAC_SUBGHZ_CMD_SET_RF_FREQUENCY        0x86U
#define ISAC_SUBGHZ_CMD_CALIBRATE               0x89U
#define ISAC_SUBGHZ_CMD_SET_PACKET_TYPE         0x8AU
#define ISAC_SUBGHZ_CMD_SET_MODULATION_PARAMS   0x8BU
#define ISAC_SUBGHZ_CMD_SET_PACKET_PARAMS       0x8CU
#define ISAC_SUBGHZ_CMD_SET_TX_PARAMS           0x8EU
#define ISAC_SUBGHZ_CMD_SET_BUFFER_BASE_ADDR    0x8FU
#define ISAC_SUBGHZ_CMD_SET_PA_CONFIG           0x95U
#define ISAC_SUBGHZ_CMD_SET_REGULATOR_MODE      0x96U
#define ISAC_SUBGHZ_CMD_SET_TCXO_MODE           0x97U
#define ISAC_SUBGHZ_CMD_CALIBRATE_IMAGE         0x98U
#define ISAC_SUBGHZ_CMD_SET_STOP_RX_TIMER_ON_PREAMBLE 0x9FU
#define ISAC_SUBGHZ_CMD_SET_TX_CONTINUOUS_WAVE  0xD1U

#define ISAC_SUBGHZ_STDBY_RC                    0x00U
#define ISAC_SUBGHZ_STDBY_XOSC                  0x01U
#define ISAC_SUBGHZ_SLEEP_WARM_START            0x04U
#define ISAC_SUBGHZ_REGMODE_USE_LDO             0x00U
#define ISAC_SUBGHZ_REGMODE_USE_DCDC            0x01U  /* Engages external 15 uH L_SMPS buck */
#define ISAC_SUBGHZ_PA_DEVSEL_RFO_LP            0x01U  /* RAK3172LP-SiP +14 dBm PA path */
#define ISAC_SUBGHZ_RAMP_40_US                  0x02U
#define ISAC_SUBGHZ_PKT_TYPE_LORA               0x01U
#define ISAC_SUBGHZ_TCXO_CTRL_1_8V              0x02U  /* 1.8 V TCXO trim code (unused) */
#define ISAC_SUBGHZ_TCXO_CTRL_3_0V              0x06U  /* 3.0 V DIO3/PB0 TCXO supply per RAK3172LP-SiP datasheet */
#define ISAC_SUBGHZ_TCXO_TIMEOUT_5MS_TICKS      320UL  /* 320 * 15.625 us = 5.0 ms TCXO settle */
#define ISAC_SUBGHZ_CALIBRATE_ALL_BLOCKS        0x7FU  /* RC64k, RC13M, PLL, ADC, IMG */

/* SX1262 Internal IRQ Bitmasks, LoRa SyncWord, Silicon Workarounds & SMPS Clock-Detect Register */
#define ISAC_SUBGHZ_IRQ_TX_DONE                 (1U << 0)
#define ISAC_SUBGHZ_IRQ_RX_DONE                 (1U << 1)
#define ISAC_SUBGHZ_IRQ_CRC_ERR                 (1U << 6)
#define ISAC_SUBGHZ_IRQ_TIMEOUT                 (1U << 9)
#define ISAC_SUBGHZ_REG_IQ_POLARITY             0x0736U /* SX1262 §15.4 / RM0453 §5.8.4 SUBGHZ_LIQPOLR */
#define ISAC_SUBGHZ_REG_LORA_SYNC_MSB           0x0740U
#define ISAC_SUBGHZ_LORA_PUBLIC_SYNC_MSB        0x34U  /* LoRaWAN Public Network SyncWord 0x3444 */
#define ISAC_SUBGHZ_LORA_PUBLIC_SYNC_LSB        0x44U
#define ISAC_SUBGHZ_REG_TX_MODULATION           0x0889U /* SX1262 §15.1 BW500/BW125 modulation quality */
#define ISAC_SUBGHZ_REG_RX_GAIN                 0x08ACU /* RM0453 §5.8.4 SUBGHZ_RXGAIN */
#define ISAC_SUBGHZ_RX_GAIN_BOOSTED             0x96U   /* +3 dB boosted LNA gain (~+0.6 mA RX) */
#define ISAC_SUBGHZ_REG_TX_CLAMP_CFG            0x08D8U /* SX1262 §15.2 PA Antenna-Mismatch Clamp Config */
#define ISAC_SUBGHZ_TX_CLAMP_FIX_MASK           0x1EU   /* SX1262 §15.2: set bits [4:1]=0b1111 for high VSWR */
#define ISAC_SUBGHZ_REG_SMPSC0R                 0x0916U /* RM0453 Rev 6 §5.10.57 SUBGHZ_SMPSC0R */
#define ISAC_SUBGHZ_SMPSC0R_CLKDE               0x40U   /* DS13105 Rev 12 §3.9.1 Danger: enable before SMPSEN */

/* =========================================================================
 * 2. EU868 3-Tone Sweep Frequencies, Settling & Analog Constants
 * ========================================================================= */
#define ISAC_NUM_TONES                          3U
#define ISAC_TONE1_FREQ_HZ                      863100000UL  /* EU868 lower band edge  */
#define ISAC_TONE2_FREQ_HZ                      866500000UL  /* Dry-air IFA resonance  */
#define ISAC_TONE3_FREQ_HZ                      869500000UL  /* EU868 g3 high sub-band */

/* Timing & TX power windows for Rev E.5:
 *   - 3000 us wakeup >= TPS22919DCKR max t_ON (~2.5 ms over -40..+85 C) + LT5538 1 nF CAP settling
 *   - 550 us LPF dwell = 5.5 * tau_LPF (R_LPF=1k, C_LPF=100nF, tau=100us -> 99.59% > 99.5%)
 *   - Dual ADC->SMPR: 416 us VREFINT (SMP2=39.5) + 200 us DET_ADC (SMP1=12.5) -> 1.166 ms/tone CW
 *   - Conservative integer ceiling: 2 ms/tone (6 ms total 3-tone sweep; 24 ms/h << 3,600 ms/h 0.1% cap)
 *   - +4 dBm CW sweep power: P_in(LT5538) <= -25.40 dBm (+12.40 dB linear margin below -13 dBm knee) */
#define ISAC_WAKEUP_SETTLE_US                   3000UL
#define ISAC_RAIL_SENSE_SETTLE_US               150UL   /* Passive PA9/Q2 + C_BAT=1nF 12-bit settle (7x tau) */
#define ISAC_LPF_SETTLE_US                      550UL
#define ISAC_SENSING_TX_DBM                     4       /* +4 dBm linear CW sweep power */
#define ISAC_CW_QUENCH_DBM                      (-9)    /* -9 dBm RFO_LP min PA setting for 40 us soft ramp-down */
#define ISAC_CW_QUENCH_SETTLE_US                50UL    /* >= 40 us SX1262 PA envelope ramp-down before STDBY_XOSC */
#define ISAC_LORAWAN_TX_DBM                     14      /* +14 dBm LoRaWAN Class A TX power */
#define ISAC_MAX_CW_DWELL_PER_TONE_MS           3UL
#define ISAC_TONE1_CW_AIRTIME_MS                2UL     /* Tone 1 (863.1 MHz, h1.3 <=0.1% DC) ceil(1.22 ms) = 2 ms */
#define ISAC_SWEEP_CW_AIRTIME_MS                6UL     /* 3 x 2 ms conservative integer ceiling */

/* Listen-Before-Sense (LBS) TX-Off Ambient RF Interference Blanking (`Rev E.5` Broadband Detector Guard):
 *   - Quiet LT5538 thermal baseline in 50 Ohm: ~110..160 mV (-83..-80 dBm across -40..+85 C)
 *   - Threshold 320 mV (~-72.0 dBm external LTE/GSM/LoRa ingress) rejects co-channel & out-of-band
 *     jammers before they can bias a -48.9 dBm dry-air bridge null by > 0.05 dB (0 ms wasted airtime) */
#define ISAC_LBS_MAX_AMBIENT_MV                 320U    /* Max clean TX-off LT5538 output [mV] (~-72 dBm) */
#define ISAC_LBS_DISCHARGE_US                   650UL   /* 6.5 * tau_LPF (99.85% C_LPF=100nF decay post-CW) */
#define ISAC_LBS_BACKOFF_MS                     20UL    /* Gated PA8=0 carrier-sense retry backoff [ms] */
#define ISAC_LBS_MAX_RETRIES                    2U      /* Max pre-sweep LBS retries before FAULT blanking */

/* Die-temperature threshold for glaze-ice vs warm-dew disambiguation */
#define ISAC_TEMP_UNAVAILABLE                   (-32768)
#define ISAC_ICE_MAX_TEMP_DEGC_X10              40      /* +4.0 C max die temp for physical GLAZE_ICE */

/* LT5538 Log-Detector Transfer Constants @ 868 MHz:
 *   V_OUT = K_SLOPE * (P_IN_dBm - P_INT_dBm), K_SLOPE = 19.0 mV/dB, P_INT = -88.80 dBm */
#define ISAC_LT5538_SLOPE_UV_PER_CDB            190L    /* 19.0 mV/dB = 190 uV per 0.01 dB */
#define ISAC_LT5538_INTERCEPT_DBM_X100          (-8880L)/* -88.80 dBm */

/* LoRaWAN Application Port & 10-Byte Payload Contract
 * Target battery is 1S Li-ion / LiPo (3.00-4.20 V operating range) or 3.6 V Li-SOCl2 via Q3
 * AO3401A ideal diode (< 4 mV forward drop). PB4 / ADC_IN3 measures post-Q3 `VBAT`:
 *   - Full / nominal 1S Li-ion/LiPo (4.20 V -> 3.15 V) -> healthy (bit 5 = 0).
 *   - Discharge knee warning (`VBAT < 3100 mV`, ~5% remaining above 3.00 V cutoff) -> warn (bit 5 = 1). */
#define ISAC_LORAWAN_FPORT                      10U
#define ISAC_FPORT10_PAYLOAD_LEN                10U
#define ISAC_VBAT_LOW_WARN_MV                   3100U

/* Flag bits in FPort 10 Byte 0 (`state_flags`) */
#define ISAC_FLAG_STATE_MASK                    0x0FU
#define ISAC_FLAG_SMPS_DCDC_ACTIVE              (1U << 4)
#define ISAC_FLAG_LOW_BATTERY                   (1U << 5)
#define ISAC_FLAG_DUTY_THROTTLED                (1U << 6)
#define ISAC_FLAG_REV_E1_FRAME                  (1U << 7)
#define ISAC_FLAG_REV_E0_FRAME                  ISAC_FLAG_REV_E1_FRAME

/* ETSI EN 300 220-1 / ERC/REC 70-03 Rolling 1-Hour Duty Cycle Budgets:
 *   - Band h1.3 (863-865 MHz, Tone 1 = 863.1 MHz): <= 0.1% (3,600 ms / 3,600,000 ms)
 *   - Band h1.4 (865-868.6 MHz, Tone 2 & EU868 UL): <= 1.0% (36,000 ms / 3,600,000 ms) */
#define ISAC_ETSI_WINDOW_MS                     3600000UL
#define ISAC_ETSI_MAX_AIRTIME_1PCT_MS           36000UL
#define ISAC_ETSI_DUTY_DENOM_1PCT               100UL
#define ISAC_ETSI_MAX_AIRTIME_0P1PCT_MS         3600UL
#define ISAC_ETSI_DUTY_DENOM_0P1PCT             1000UL

/* =========================================================================
 * 3. Surface Medium Classification Enum & Telemetry Data Structures
 * ========================================================================= */
typedef enum {
    ISAC_SURFACE_DRY_AIR       = 0,  /**< Unloaded dry window (eps_r = 1.00)            */
    ISAC_SURFACE_OIL           = 1,  /**< Nonpolar oil / hydrocarbon / PTFE (eps ~ 2.1) */
    ISAC_SURFACE_GLAZE_ICE     = 2,  /**< Glaze ice accretion (eps_r = 3.20)            */
    ISAC_SURFACE_IPA           = 3,  /**< Lossy polar solvent / medium-eps (eps ~ 6.3)  */
    ISAC_SURFACE_LIQUID_WATER  = 4,  /**< Liquid water film (eps_r ~ 79.9)              */
    ISAC_SURFACE_FAULT         = 15  /**< Sensor/rail diagnostic fault                  */
} isac_surface_state_t;

/**
 * @brief Raw ratiometric 3-tone sweep capture produced by `ISAC_Acquire_3Tone_Sweep()`.
 */
typedef struct {
    uint16_t vrefint_cal;                 /**< Factory VREFINT_CAL @ 3000 mV (0x1FFF75AA) */
    uint32_t vrefint_raw16;               /**< Pre-TX 16x oversampled VREFINT sum          */
    uint32_t vrefint_tone_raw16[ISAC_NUM_TONES]; /**< Per-tone live CW-loaded VREFINT sums */
    uint32_t bat_raw16;                   /**< Live 16x oversampled ADC_IN3 sum (0..65520) */
    uint32_t det_raw16[ISAC_NUM_TONES];   /**< Live 16x oversampled ADC_IN11 sums @ f1..f3 */
    uint16_t vdda_mv;                     /**< Minimum live VDDA rail across sweep [mV]    */
    uint16_t vdda_tone_mv[ISAC_NUM_TONES];/**< Per-tone CW-loaded VDDA rail [mV]           */
    uint16_t vbat_mv;                     /**< Gated battery voltage VBAT [mV]             */
    uint16_t det_mv[ISAC_NUM_TONES];      /**< Ratiometric detector voltages [mV]          */
    uint32_t det_100uv[ISAC_NUM_TONES];   /**< High-res ratiometric voltages [0.1 mV]      */
    uint16_t tone_cw_ms[ISAC_NUM_TONES];  /**< Measured CW airtime per tone (>= 2 ms) [ms] */
    uint16_t lbs_pre_mv;                  /**< Pre-sweep TX-off ambient LT5538 floor [mV]  */
    uint16_t lbs_post_mv;                 /**< Post-sweep TX-off ambient LT5538 floor [mV] */
    int16_t  die_temp_degc_x10;           /**< MCU die temperature [0.1 C]                 */
    bool     smps_dcdc_enabled;           /**< True when live 15 uH SMPS buck is ready     */
    bool     lbs_jammed;                  /**< True when ambient RF jammer > 320 mV seen   */
} isac_raw_sweep_t;

/**
 * @brief Extracted physical RF features & medium classification.
 */
typedef struct {
    int16_t              tilt_db_x100;    /**< (V(f1) - V(f3)) / 19.0 mV/dB [0.01 dB]      */
    int16_t              notch_db_x100;   /**< ((V(f1)+V(f3))/2 - V(f2)) / 19.0 [0.01 dB]  */
    int16_t              level_dbm_x100;  /**< Mean bridge output power [0.01 dBm]         */
    uint16_t             eps_est_x100;    /**< Estimated superstrate eps_r' * 100          */
    uint16_t             vbat_mv;         /**< Battery voltage [mV]                        */
    uint16_t             vdda_mv;         /**< Analog reference rail [mV]                  */
    isac_surface_state_t state;           /**< Classified surface medium                   */
    bool                 smps_dcdc_ok;    /**< True when 15 uH SMPS buck is active         */
} isac_telemetry_t;

/**
 * @brief ETSI EN 300 220-1 rolling 1-hour duty-cycle tracker (1.0% main + 0.1% 863.1 MHz h1.3).
 */
typedef struct {
    uint32_t window_start_ms;             /**< Timestamp of current 1-hour window [ms]        */
    uint32_t used_airtime_ms;             /**< Cumulative 1.0% sub-band TX airtime [ms]       */
    uint32_t last_tx_end_ms;              /**< End timestamp of most recent TX [ms]           */
    uint32_t min_next_tx_ms;              /**< Earliest next TX allowed by 1% backoff [ms]    */
    uint32_t used_subband_0p1_ms;         /**< Cumulative 0.1% (863.1 MHz h1.3) airtime [ms]  */
    uint32_t min_next_0p1_tx_ms;          /**< Earliest next 863.1 MHz TX (0.1% backoff) [ms] */
    bool     throttled;                   /**< Set if a TX request was deferred by budget     */
} isac_duty_tracker_t;

/* =========================================================================
 * 4. Public Firmware API
 * ========================================================================= */
bool     ISAC_Init_Radio_And_SMPS(void);
bool     ISAC_Is_SMPS_Active(void);
uint32_t ISAC_FreqHz_To_PllStep(uint32_t freq_hz);

bool     ISAC_Acquire_Supply_Rails(uint16_t *out_vbat_mv, uint16_t *out_vdda_mv);
bool     ISAC_Acquire_3Tone_Sweep(isac_raw_sweep_t *out_sweep);
void     ISAC_Sensing_SetCalibration(const uint16_t cal_dry_mv[ISAC_NUM_TONES], bool valid);
void     ISAC_Sensing_SetCalibration2Pt(const uint16_t cal_dry_mv[ISAC_NUM_TONES],
                                        bool dry_valid,
                                        int16_t cal_ref_cdb,
                                        bool ref_valid);
void     ISAC_Extract_Features_And_Classify(const isac_raw_sweep_t *sweep,
                                            isac_telemetry_t *out_tel);
void     ISAC_Extract_Features_And_Classify_WithTemp(const isac_raw_sweep_t *sweep,
                                                     int16_t temp_degc_x10,
                                                     isac_telemetry_t *out_tel);
uint8_t  ISAC_Select_Uplink_SF(isac_surface_state_t state,
                               isac_duty_tracker_t *dc,
                               uint32_t now_ms,
                               uint32_t extra_1pct_ms);

void     ISAC_Pack_LoRaWAN_FPort10(const isac_telemetry_t *tel,
                                   const isac_duty_tracker_t *dc,
                                   uint8_t payload[ISAC_FPORT10_PAYLOAD_LEN]);
void     ISAC_Unpack_LoRaWAN_FPort10(const uint8_t payload[ISAC_FPORT10_PAYLOAD_LEN],
                                     isac_telemetry_t *out_tel,
                                     uint8_t *out_flags);

void     ISAC_DutyCycle_Init(isac_duty_tracker_t *dc, uint32_t now_ms);
void     ISAC_DutyCycle_Tick(isac_duty_tracker_t *dc, uint32_t now_ms);
bool     ISAC_DutyCycle_CanTransmit(isac_duty_tracker_t *dc, uint32_t planned_airtime_ms, uint32_t now_ms);
bool     ISAC_DutyCycle_CanTransmitSubband0p1(isac_duty_tracker_t *dc, uint32_t planned_0p1_ms, uint32_t now_ms);
void     ISAC_DutyCycle_RecordAirTime(isac_duty_tracker_t *dc, uint32_t airtime_ms, uint32_t now_ms);
void     ISAC_DutyCycle_RecordSubband0p1AirTime(isac_duty_tracker_t *dc, uint32_t airtime_0p1_ms, uint32_t now_ms);
uint32_t ISAC_DutyCycle_MinBackoffMs(uint32_t airtime_ms);

#endif /* ISAC_SENSING_H */
