/**
 * @file isac_hal.h
 * @brief Hardware Abstraction Layer (HAL) Contract for RAK3172LP-SiP & Host HIL
 *
 * Isolates register-level STM32WLE5JC operations (`isac_hal_stm32wl.c`) from the
 * deterministic 3-tone ISAC acquisition & LoRaWAN 1.0.3 Class A engine,
 * allowing bit-exact execution on both bare-metal Cortex-M4 and host HIL unit tests.
 */
#ifndef ISAC_HAL_H
#define ISAC_HAL_H

#include <stdbool.h>
#include <stdint.h>

/**
 * @brief RAK3172LP-SiP internal SPDT RF switch state (PA0 VC1 / PA1 VC2 truth table).
 */
typedef enum {
    ISAC_RFSW_OFF   = 0,  /**< PA0 = 0, PA1 = 0 : Isolated / STOP2 deep-sleep (0 nA) */
    ISAC_RFSW_RX    = 1,  /**< PA0 = 1, PA1 = 0 : Pin 37 RF_OUT -> internal SX1262 LNA */
    ISAC_RFSW_TX_LP = 2,  /**< PA0 = 0, PA1 = 1 : Internal SX1262 RFO_LP +14 dBm -> Pin 37 RF_OUT */
    ISAC_RFSW_TX    = ISAC_RFSW_TX_LP
} isac_rf_switch_mode_t;

void     ISAC_HAL_GPIO_InitBoardPins(void);
void     ISAC_HAL_UART2_InitDiagnostic(void);
void     ISAC_HAL_GPIO_SetDetEnable(bool enable);
void     ISAC_HAL_GPIO_SetBatMonEnable(bool enable);
void     ISAC_HAL_RFSwitch_SetMode(isac_rf_switch_mode_t mode);

bool     ISAC_HAL_System_EnableSMPS(void);
bool     ISAC_HAL_System_IsSMPSEnabled(void);
void     ISAC_HAL_RTC_InitWakeup(uint32_t period_s);
uint32_t ISAC_HAL_GetTickMs(void);
void     ISAC_HAL_DelayMs(uint32_t ms);

bool     ISAC_HAL_SubGhz_WakeupAndReset(void);
bool     ISAC_HAL_SubGhz_EnsureAwake(void);
bool     ISAC_HAL_SubGhz_WriteCmd(uint8_t opcode, const uint8_t *params, uint8_t len);
bool     ISAC_HAL_SubGhz_ReadCmd(uint8_t opcode, uint8_t *rx_buf, uint8_t len);
bool     ISAC_HAL_SubGhz_WriteReg(uint16_t addr, const uint8_t *data, uint8_t len);
bool     ISAC_HAL_SubGhz_ReadReg(uint16_t addr, uint8_t *data, uint8_t len);
bool     ISAC_HAL_SubGhz_WriteBuffer(uint8_t offset, const uint8_t *data, uint8_t len);
bool     ISAC_HAL_SubGhz_ReadBuffer(uint8_t offset, uint8_t *data, uint8_t len);

void     ISAC_HAL_ADC_EnableAndCalibrate(void);
uint32_t ISAC_HAL_ADC_ReadOversampled16x(uint8_t channel);
int16_t  ISAC_HAL_ADC_ReadDieTempDegCx10(uint16_t vdda_mv);
void     ISAC_HAL_ADC_Disable(void);
uint16_t ISAC_HAL_ReadVrefintCal(void);
uint16_t ISAC_HAL_ReadTsCal1(void);
uint16_t ISAC_HAL_ReadTsCal2(void);
void     ISAC_HAL_ReadUniqueId64(uint8_t uid_be[8]);

void     ISAC_HAL_DelayUs(uint32_t us);

/* ---- Reset diagnostics, option-byte readout, IWDG & STOP2 services (RM0453 §7.4.31) -- */
#define ISAC_RESET_FLAG_RFILA  (1UL << 24)
#define ISAC_RESET_FLAG_OBL    (1UL << 25)
#define ISAC_RESET_FLAG_PIN    (1UL << 26)
#define ISAC_RESET_FLAG_BOR    (1UL << 27)
#define ISAC_RESET_FLAG_SFT    (1UL << 28)
#define ISAC_RESET_FLAG_IWDG   (1UL << 29)
#define ISAC_RESET_FLAG_WWDG   (1UL << 30)
#define ISAC_RESET_FLAG_LPWR   (1UL << 31)

uint32_t ISAC_HAL_ResetCause_ReadAndClear(void);   /**< RCC_CSR reset flags (bits 24..31), then cleared */
uint32_t ISAC_HAL_ReadOptionRegister(void);        /**< FLASH_OPTR                                      */
bool     ISAC_HAL_ReadoutProtectionActive(void);   /**< true if RDP != 0xAA (level 1 or 2)              */
bool     ISAC_HAL_Watchdog_Start(void);            /**< Starts IWDG only if frozen-in-STOP option is set */
void     ISAC_HAL_Watchdog_Kick(void);
void     ISAC_HAL_EnterStop2(void);

#endif /* ISAC_HAL_H */
