/**
 * @file isac_board_pins.h
 * @brief Exact Schematic-Matched Hardware Pin & Register Map for ISAC_868_KiCad9 (Rev E.5)
 *
 * Target SiP: RAKwireless RAK3172LP-SiP (73-pad LGA, 12x12 mm, STM32WLE5JC + internal SX1262 RFO_LP)
 *
 * Verified 1:1 Pin Parity with `ISAC_868_KiCad9.kicad_sch` (`tools/gen_sch.py`):
 *   - PA8  (SiP Pin 51)          -> DET_EN     (Drives Q1 TPS22919DCKR VBAT -> 3V3_DET LT5538 rail)
 *   - PA9  (SiP Pin 50)          -> BAT_MON_EN (Drives Q2 NX3008CBKS VBAT divider independently of LT5538)
 *   - PA15 (SiP Pin 8, ADC_IN11) -> DET_ADC    (LT5538 OUT via R_LPF=1k + C_LPF=100nF, fc=1.59 kHz)
 *   - PB4  (SiP Pin 15, ADC_IN3) -> BAT_SENSE  (Gated R_B1=4.7k / R_B2=4.7k 0.1% + C_BAT=1nF divider)
 *   - PA2  (SiP Pin 29, Analog)  -> UART_TX    (Default Analog High-Z for 0 nA STOP2; opt-in AF7 via ISAC_HAL_UART2_InitDiagnostic)
 *   - PA3  (SiP Pin 30, Analog)  -> UART_RX    (Default Analog High-Z for 0 nA STOP2; opt-in AF7 via ISAC_HAL_UART2_InitDiagnostic)
 *   - PA13 (SiP Pin 1, AF0)      -> SWDIO      (JTMS/SWDIO via D_SWD PESD5V0U2BT to J4.2)
 *   - PA14 (SiP Pin 2, AF0)      -> SWCLK      (JTCK/SWCLK via D_SWD PESD5V0U2BT to J4.3)
 *   - PH3  (SiP Pin 43)          -> BOOT0      (10k R_BOOT pulldown + J3 header)
 *   - NRST (SiP Pin 44)          -> RST        (10k R_RST pullup + 100nF C_RST + SW1 + D_RST PESD5V0S1BA)
 *   - Pins 10, 11, 13            -> VFBSMPS / VDDSMPS / VLXSMPS (External 15 uH Murata LQH2MCN150K02L wirewound buck, Isat=300mA)
 *   - Pins 6, 7                  -> VREF+ / VDDA (FB_VDDA BLM15AG121SN1D isolated 3.3V analog reference)
 *   - Pin 37                     -> RF_OUT     (50.0 Ohm CPWG -> Return-Loss Bridge -> AE1 IFA+IDE)
 *   - Internal RAK3172LP-SiP Connections (inside LGA-73 SiP substrate):
 *       PA0  (internal MCU pin)  = RFSW_VC1 (Internal SPDT RF switch CTRL1)
 *       PA1  (internal MCU pin)  = RFSW_VC2 (Internal SPDT RF switch CTRL2)
 *       PB0  (VDD_TCXO / DIO3)   = 32 MHz TCXO supply (enabled via SetDIO3AsTCXOCtrl 0x97)
 *       PC14 / PC15 (OSC32)      = Internal 32.768 kHz LSE crystal for STOP2 RTC wakeup
 *       Official RAK3172LP-SiP SPDT RF Switch Truth Table:
 *         * IDLE / STOP2 : PA0 = 0, PA1 = 0  (0 nA sleep quiescent current)
 *         * RX           : PA0 = 1, PA1 = 0  (Pin 37 RF_OUT -> SX1262 RFI_N/P LNA)
 *         * TX (RFO_LP)  : PA0 = 0, PA1 = 1  (SX1262 RFO_LP +14 dBm PA -> Pin 37 RF_OUT)
 */
#ifndef ISAC_BOARD_PINS_H
#define ISAC_BOARD_PINS_H

#include <stddef.h>
#include <stdint.h>

/* =========================================================================
 * 1. RAK3172LP-SiP (LGA-73) Physical Package Pin Numbers & GPIO Indices
 * ========================================================================= */
#define ISAC_SIP_PIN_SWDIO          1U   /* PA13 / JTMS-SWDIO */
#define ISAC_SIP_PIN_SWCLK          2U   /* PA14 / JTCK-SWCLK */
#define ISAC_SIP_PIN_VDD1           3U   /* 3V3 digital rail */
#define ISAC_SIP_PIN_VBAT_MCU       4U   /* 3V3 backup rail */
#define ISAC_SIP_PIN_VREF_PLUS      6U   /* FB_VDDA isolated analog reference */
#define ISAC_SIP_PIN_VDDA           7U   /* FB_VDDA isolated analog supply */
#define ISAC_SIP_PIN_DET_ADC        8U   /* PA15 / ADC_IN11 (LT5538 video LPF output) */
#define ISAC_SIP_PIN_VFBSMPS        10U  /* 15 uH SMPS feedback sense */
#define ISAC_SIP_PIN_VDDSMPS        11U  /* 15 uH SMPS input supply */
#define ISAC_SIP_PIN_VLXSMPS        13U  /* 15 uH SMPS switching node */
#define ISAC_SIP_PIN_BAT_SENSE      15U  /* PB4 / ADC_IN3 (Gated VBAT/2 divider) */
#define ISAC_SIP_PIN_UART2_TX       29U  /* PA2 / USART2_TX */
#define ISAC_SIP_PIN_UART2_RX       30U  /* PA3 / USART2_RX */
#define ISAC_SIP_PIN_RF_OUT         37U  /* 50 Ohm RFO_LP / RFI port */
#define ISAC_SIP_PIN_BOOT0          43U  /* PH3-BOOT0 */
#define ISAC_SIP_PIN_NRST           44U  /* NRST */
#define ISAC_SIP_PIN_BAT_MON_EN     50U  /* PA9 -> Q2 (VBAT_SW gated battery divider) */
#define ISAC_SIP_PIN_DET_EN         51U  /* PA8 -> Q1 (3V3_DET VBAT-fed LT5538 load switch) */
#define ISAC_SIP_PIN_VDDPA          53U  /* FB_PA isolated PA rail */
#define ISAC_SIP_PIN_VDDRF          54U  /* FB_RF isolated RF rail */
#define ISAC_SIP_PIN_VDD2           55U  /* 3V3 digital rail */

/* STM32WLE5JC GPIO Pin Indices (0..15) */
#define ISAC_GPIOA_PIN_RFSW_VC1     0U   /* PA0  -> Internal RAK3172LP-SiP SPDT VC1 */
#define ISAC_GPIOA_PIN_RFSW_VC2     1U   /* PA1  -> Internal RAK3172LP-SiP SPDT VC2 */
#define ISAC_GPIOA_PIN_UART2_TX     2U   /* PA2  */
#define ISAC_GPIOA_PIN_UART2_RX     3U   /* PA3  */
#define ISAC_GPIOA_PIN_DET_EN       8U   /* PA8  */
#define ISAC_GPIOA_PIN_BAT_MON_EN   9U   /* PA9  */
#define ISAC_GPIOA_PIN_SWDIO        13U  /* PA13 */
#define ISAC_GPIOA_PIN_SWCLK        14U  /* PA14 */
#define ISAC_GPIOA_PIN_DET_ADC      15U  /* PA15 -> ADC_IN11 */

#define ISAC_GPIOB_PIN_BAT_SENSE    4U   /* PB4  -> ADC_IN3  */

/* STM32WLE5JC 12-bit SAR ADC Channel Numbers (RM0453 Section 16.3.5) */
#define ISAC_ADC_CH_BAT_SENSE       3U   /* PB4  = ADC_IN3  */
#define ISAC_ADC_CH_DET_ADC         11U  /* PA15 = ADC_IN11 */
#define ISAC_ADC_CH_TEMPSENSOR      12U  /* RM0453 §15.3.12: ADC_IN12 = Internal MCU Die Temp Sensor */
#define ISAC_ADC_CH_VREFINT         13U  /* RM0453 §15.3.11: ADC_IN13 = Internal VREFINT */

/* STM32WLE5JC Factory OTP Calibration Addresses (calibrated at VDDA = 3000 mV, DS13105 Table 12) */
#define ISAC_TS_CAL1_ADDR           0x1FFF75A8UL /* TS_CAL1 raw 12-bit ADC @ +30 C, VDDA = 3000 mV  */
#define ISAC_VREFINT_CAL_ADDR       0x1FFF75AAUL /* VREFINT_CAL raw 12-bit ADC @ +30 C, 3000 mV     */
#define ISAC_TS_CAL2_ADDR           0x1FFF75CAUL /* TS_CAL2 raw 12-bit ADC @ +130 C, VDDA = 3000 mV */
#define ISAC_VREFINT_CAL_VREF_MV    3000UL
#define ISAC_TS_CAL1_TEMP_C         30L
#define ISAC_TS_CAL2_TEMP_C         130L

/* STM32WLE5JC Unique 64-bit Device ID Base (RM0453 §39.1.4 — used for deterministic DevEUI) */
#define ISAC_UID64_BASE             0x1FFF7580UL

/* Default Autonomous RTC STOP2 Wakeup Period [seconds] (15 min = 900 s) */
#define ISAC_DEFAULT_REPORT_PERIOD_S 900UL

/* =========================================================================
 * 2. Minimal Dependency-Free STM32WLE5JC Cortex-M4 Register Definitions
 * ========================================================================= */
typedef struct {
    volatile uint32_t MODER;    /* +0x00 */
    volatile uint32_t OTYPER;   /* +0x04 */
    volatile uint32_t OSPEEDR;  /* +0x08 */
    volatile uint32_t PUPDR;    /* +0x0C */
    volatile uint32_t IDR;      /* +0x10 */
    volatile uint32_t ODR;      /* +0x14 */
    volatile uint32_t BSRR;     /* +0x18 */
    volatile uint32_t LCKR;     /* +0x1C */
    volatile uint32_t AFRL;     /* +0x20 */
    volatile uint32_t AFRH;     /* +0x24 */
    volatile uint32_t BRR;      /* +0x28 */
} ISAC_GPIO_Regs_t;

typedef struct {
    volatile uint32_t CR;          /* +0x00 */
    volatile uint32_t ICSCR;       /* +0x04 */
    volatile uint32_t CFGR;        /* +0x08 */
    volatile uint32_t PLLCFGR;     /* +0x0C */
    uint32_t          RESERVED0[6];/* +0x10..0x24 */
    volatile uint32_t AHB1RSTR;    /* +0x28 */
    volatile uint32_t AHB2RSTR;    /* +0x2C */
    volatile uint32_t AHB3RSTR;    /* +0x30 */
    uint32_t          RESERVED1;   /* +0x34 */
    volatile uint32_t APB1RSTR1;   /* +0x38 */
    volatile uint32_t APB1RSTR2;   /* +0x3C */
    volatile uint32_t APB2RSTR;    /* +0x40 */
    volatile uint32_t APB3RSTR;    /* +0x44 */
    volatile uint32_t AHB1ENR;     /* +0x48 */
    volatile uint32_t AHB2ENR;     /* +0x4C */
    volatile uint32_t AHB3ENR;     /* +0x50 */
    uint32_t          RESERVED2;   /* +0x54 */
    volatile uint32_t APB1ENR1;    /* +0x58 */
    volatile uint32_t APB1ENR2;    /* +0x5C */
    volatile uint32_t APB2ENR;     /* +0x60 */
    volatile uint32_t APB3ENR;     /* +0x64 */
    uint32_t          RESERVED3[8];/* +0x68..0x84 */
    volatile uint32_t CCIPR;       /* +0x88 */
    uint32_t          RESERVED4;   /* +0x8C */
    volatile uint32_t BDCR;        /* +0x90 */
    volatile uint32_t CSR;         /* +0x94 */
} ISAC_RCC_Regs_t;

typedef struct {
    volatile uint32_t CR1;         /* +0x00 */
    volatile uint32_t CR2;         /* +0x04 */
    volatile uint32_t CR3;         /* +0x08 */
    volatile uint32_t CR4;         /* +0x0C */
    volatile uint32_t SR1;         /* +0x10 */
    volatile uint32_t SR2;         /* +0x14 */
    volatile uint32_t SCR;         /* +0x18 */
    volatile uint32_t CR5;         /* +0x1C */
    uint32_t          RESERVED0[28];/* +0x20..0x8C */
    volatile uint32_t SUBGHZSPICR; /* +0x90 */
} ISAC_PWR_Regs_t;

typedef struct {
    volatile uint32_t ISR;         /* +0x00 */
    volatile uint32_t IER;         /* +0x04 */
    volatile uint32_t CR;          /* +0x08 */
    volatile uint32_t CFGR1;       /* +0x0C */
    volatile uint32_t CFGR2;       /* +0x10 */
    volatile uint32_t SMPR;        /* +0x14 */
    uint32_t          RESERVED0[2];/* +0x18..0x1C */
    volatile uint32_t TR1;         /* +0x20 */
    volatile uint32_t TR2;         /* +0x24 */
    volatile uint32_t CHSELR;      /* +0x28 */
    volatile uint32_t TR3;         /* +0x2C */
    uint32_t          RESERVED1[4];/* +0x30..0x3C */
    volatile uint32_t DR;          /* +0x40 */
} ISAC_ADC_Regs_t;

typedef struct {
    volatile uint32_t CCR;         /* +0x00 */
} ISAC_ADC_Common_Regs_t;

typedef struct {
    volatile uint32_t CR1;         /* +0x00 */
    volatile uint32_t CR2;         /* +0x04 */
    volatile uint32_t SR;          /* +0x08 */
    volatile uint32_t DR;          /* +0x0C */
} ISAC_SPI_Regs_t;

/* STM32WLE5JC RTC3 Register Block (RM0453 §27.7, Base 0x40002800) */
typedef struct {
    volatile uint32_t TR;          /* +0x00 */
    volatile uint32_t DR;          /* +0x04 */
    volatile uint32_t SSR;         /* +0x08 */
    volatile uint32_t ICSR;        /* +0x0C */
    volatile uint32_t PRER;        /* +0x10 */
    volatile uint32_t WUTR;        /* +0x14 */
    volatile uint32_t CR;          /* +0x18 */
    uint32_t          RESERVED0[2];/* +0x1C..0x20 */
    volatile uint32_t WPR;         /* +0x24 */
    volatile uint32_t CALR;        /* +0x28 */
    volatile uint32_t SHIFTR;      /* +0x2C */
    volatile uint32_t TSTR;        /* +0x30 */
    volatile uint32_t TSDR;        /* +0x34 */
    volatile uint32_t TSSSR;       /* +0x38 */
    uint32_t          RESERVED1;   /* +0x3C */
    volatile uint32_t ALRMAR;      /* +0x40 */
    volatile uint32_t ALRMASSR;    /* +0x44 */
    volatile uint32_t ALRMBR;      /* +0x48 */
    volatile uint32_t ALRMBSSR;    /* +0x4C */
    volatile uint32_t SR;          /* +0x50 */
    volatile uint32_t MISR;        /* +0x54 */
    uint32_t          RESERVED2;   /* +0x58 */
    volatile uint32_t SCR;         /* +0x5C */
} ISAC_RTC_Regs_t;

/* STM32WLE5JC EXTI Register Block (RM0453 §13.5, Base 0x58000800) */
typedef struct {
    volatile uint32_t RTSR1;       /* +0x00 */
    volatile uint32_t FTSR1;       /* +0x04 */
    volatile uint32_t SWIER1;      /* +0x08 */
    volatile uint32_t PR1;         /* +0x0C */
    uint32_t          RESERVED0[28];/* +0x10..0x7C */
    volatile uint32_t IMR1;        /* +0x80 */
    volatile uint32_t EMR1;        /* +0x84 */
} ISAC_EXTI_Regs_t;

/* Cortex-M4 SysTick & System Control Block */
typedef struct {
    volatile uint32_t CSR;         /* +0x00 */
    volatile uint32_t RVR;         /* +0x04 */
    volatile uint32_t CVR;         /* +0x08 */
    volatile uint32_t CALIB;       /* +0x0C */
} ISAC_SysTick_Regs_t;

typedef struct {
    volatile uint32_t CPUID;       /* +0x00 */
    volatile uint32_t ICSR;        /* +0x04 */
    volatile uint32_t VTOR;        /* +0x08 */
    volatile uint32_t AIRCR;       /* +0x0C */
    volatile uint32_t SCR;         /* +0x10 */
} ISAC_SCB_Regs_t;

/* STM32WLE5JC Base Addresses (RM0453 Table 3) */
#define ISAC_RTC_BASE               0x40002800UL
#define ISAC_ADC_BASE               0x40012400UL
#define ISAC_ADC_COMMON_BASE        0x40012708UL
#define ISAC_GPIOA_BASE             0x48000000UL
#define ISAC_GPIOB_BASE             0x48000400UL
#define ISAC_GPIOC_BASE             0x48000800UL
#define ISAC_RCC_BASE               0x58000000UL
#define ISAC_PWR_BASE               0x58000400UL
#define ISAC_EXTI_BASE              0x58000800UL
#define ISAC_SUBGHZSPI_BASE         0x58010000UL
#define ISAC_SYSTICK_BASE           0xE000E010UL
#define ISAC_NVIC_ISER0_ADDR        0xE000E100UL
#define ISAC_NVIC_ICPR0_ADDR        0xE000E280UL
#define ISAC_SCB_BASE               0xE000ED00UL
#define ISAC_DCB_DHCSR_ADDR         0xE000EDF0UL

#define ISAC_RTC                    ((ISAC_RTC_Regs_t *)ISAC_RTC_BASE)
#define ISAC_GPIOA                  ((ISAC_GPIO_Regs_t *)ISAC_GPIOA_BASE)
#define ISAC_GPIOB                  ((ISAC_GPIO_Regs_t *)ISAC_GPIOB_BASE)
#define ISAC_GPIOC                  ((ISAC_GPIO_Regs_t *)ISAC_GPIOC_BASE)
#define ISAC_ADC                    ((ISAC_ADC_Regs_t *)ISAC_ADC_BASE)
#define ISAC_ADC_COMMON             ((ISAC_ADC_Common_Regs_t *)ISAC_ADC_COMMON_BASE)
#define ISAC_SUBGHZSPI              ((ISAC_SPI_Regs_t *)ISAC_SUBGHZSPI_BASE)
#define ISAC_RCC                    ((ISAC_RCC_Regs_t *)ISAC_RCC_BASE)
#define ISAC_PWR                    ((ISAC_PWR_Regs_t *)ISAC_PWR_BASE)
#define ISAC_EXTI                   ((ISAC_EXTI_Regs_t *)ISAC_EXTI_BASE)
#define ISAC_SYSTICK                ((ISAC_SysTick_Regs_t *)ISAC_SYSTICK_BASE)
#define ISAC_SCB                    ((ISAC_SCB_Regs_t *)ISAC_SCB_BASE)
#define ISAC_NVIC_ISER0             (*((volatile uint32_t *)ISAC_NVIC_ISER0_ADDR))
#define ISAC_NVIC_ICPR0             (*((volatile uint32_t *)ISAC_NVIC_ICPR0_ADDR))
#define ISAC_DCB_DHCSR              (*((volatile uint32_t *)ISAC_DCB_DHCSR_ADDR))

/* STM32WLE5JC Interrupt Numbers (RM0453 Table 52) */
#define ISAC_RTC_WKUP_IRQn          3U   /* Vector index 19 (offset 0x004C), EXTI Line 20 */
#define ISAC_SUBGHZ_RADIO_IRQn      50U  /* Vector index 66 (offset 0x0108) */

/* Key Register Bitmasks */
#define ISAC_RCC_CR_MSIPLLEN        (1UL << 2)   /* RM0453 §7.4.1: Hardware auto-trim MSI via 32.768 kHz LSE */
#define ISAC_RCC_AHB2ENR_GPIOAEN    (1UL << 0)
#define ISAC_RCC_AHB2ENR_GPIOBEN    (1UL << 1)
#define ISAC_RCC_AHB2ENR_GPIOCEN    (1UL << 2)
#define ISAC_RCC_APB1ENR1_RTCAPBEN  (1UL << 10)
#define ISAC_RCC_APB1ENR1_USART2EN  (1UL << 17)
#define ISAC_RCC_APB2ENR_ADCEN      (1UL << 9)
#define ISAC_RCC_APB3ENR_SUBGHZSPIEN (1UL << 0)
#define ISAC_RCC_BDCR_LSEON         (1UL << 0)
#define ISAC_RCC_BDCR_LSERDY        (1UL << 1)
#define ISAC_RCC_BDCR_RTCSEL_MASK   (3UL << 8)
#define ISAC_RCC_BDCR_RTCSEL_LSE    (1UL << 8)
#define ISAC_RCC_BDCR_RTCSEL_LSI    (2UL << 8)
#define ISAC_RCC_BDCR_RTCEN         (1UL << 15)
#define ISAC_RCC_CSR_LSION          (1UL << 0)
#define ISAC_RCC_CSR_LSIRDY         (1UL << 1)
#define ISAC_RCC_CSR_RFRSTF         (1UL << 14)
#define ISAC_RCC_CSR_RFRST          (1UL << 15)

#define ISAC_PWR_CR1_LPMS_MASK      (7UL << 0)
#define ISAC_PWR_CR1_LPMS_STOP2     (2UL << 0)
#define ISAC_PWR_CR1_DBP            (1UL << 8)   /* Disable backup domain write protection */
#define ISAC_PWR_CR5_RFEOLEN        (1UL << 14)
#define ISAC_PWR_CR5_SMPSEN         (1UL << 15)  /* External 15 uH L_SMPS step-down enable (RM0453 §6.6.8) */
#define ISAC_PWR_SR2_RFBUSYS        (1UL << 1)   /* Radio BUSY raw signal status (RM0453 §6.6.6) */
#define ISAC_PWR_SR2_RFBUSYMS       (1UL << 2)   /* Radio BUSY masked signal status */
#define ISAC_PWR_SR2_SMPSRDY        (1UL << 3)   /* SMPS step-down converter ready flag (RM0453 §6.6.6) */
#define ISAC_PWR_SR2_LDORDY         (1UL << 4)   /* Main LDO ready flag (RM0453 §6.6.6) */
#define ISAC_PWR_SCR_CWUF           (7UL << 0)
#define ISAC_PWR_SUBGHZSPICR_NSS    (1UL << 15)

#define ISAC_RTC_ICSR_RSF           (1UL << 5)
#define ISAC_RTC_ICSR_INITF         (1UL << 6)
#define ISAC_RTC_ICSR_INIT          (1UL << 7)
#define ISAC_RTC_ICSR_WUTWF         (1UL << 2)
#define ISAC_RTC_CR_WUCKSEL_MASK    (7UL << 0)
#define ISAC_RTC_CR_WUCKSEL_CK_SPRE (4UL << 0)   /* 1 Hz ck_spre (16-bit WUTR -> 1..65536 s) */
#define ISAC_RTC_CR_WUTE            (1UL << 10)
#define ISAC_RTC_CR_WUTIE           (1UL << 14)
#define ISAC_RTC_SR_WUTF            (1UL << 2)
#define ISAC_RTC_SCR_CWUTF          (1UL << 2)
#define ISAC_EXTI_IMR1_IM20         (1UL << 20)  /* Direct EXTI Line 20 = RTC Wakeup */

#define ISAC_ADC_ISR_ADRDY          (1UL << 0)
#define ISAC_ADC_ISR_EOC            (1UL << 2)
#define ISAC_ADC_ISR_CCRDY          (1UL << 13)
#define ISAC_ADC_CR_ADEN            (1UL << 0)
#define ISAC_ADC_CR_ADDIS           (1UL << 1)
#define ISAC_ADC_CR_ADSTART         (1UL << 2)
#define ISAC_ADC_CR_ADVREGEN        (1UL << 28)
#define ISAC_ADC_CR_ADCAL           (1UL << 31)
#define ISAC_ADC_CFGR2_OVSE         (1UL << 0)
#define ISAC_ADC_CFGR2_OVSR_16X     (3UL << 2)   /* 16x hardware oversampling (OVSS=0 -> 0..65520) */
#define ISAC_ADC_CFGR2_CKMODE_PCLK2 (1UL << 30)  /* Synchronous PCLK/2 SAR ADC clock (CRIT-04 fix!) */
#define ISAC_ADC_CCR_VREFEN         (1UL << 22)
#define ISAC_ADC_CCR_TSEN           (1UL << 23)  /* Internal die temperature sensor enable */

/* Dual ADC->SMPR sample-time configuration (RM0453 §15.11.6, 2 MHz synchronous PCLK/2):
 *   - SMP1 = 3 (12.5 cycles = 6.25 us -> 200 us 16x oversample) for C_LPF=100nF DET_ADC (Ch 11)
 *   - SMP2 = 5 (39.5 cycles = 19.75 us > 12 us min -> 416 us 16x oversample) for Ch 3, Ch 12, Ch 13 */
#define ISAC_ADC_SMPR_SMP1_12P5     (3UL << 0)
#define ISAC_ADC_SMPR_SMP2_39P5     (5UL << 4)
#define ISAC_ADC_SMPR_SMPSEL_BIT(c) (1UL << (8U + (uint32_t)(c)))

#define ISAC_SPI_CR1_MSTR           (1UL << 2)
#define ISAC_SPI_CR1_SPE            (1UL << 6)
#define ISAC_SPI_CR1_SSI            (1UL << 8)
#define ISAC_SPI_CR1_SSM            (1UL << 9)
#define ISAC_SPI_CR2_FRXTH          (1UL << 12)  /* 8-bit RX FIFO threshold */
#define ISAC_SPI_CR2_DS_8BIT        (7UL << 8)
#define ISAC_SPI_SR_RXNE            (1UL << 0)
#define ISAC_SPI_SR_TXE             (1UL << 1)
#define ISAC_SPI_SR_BSY             (1UL << 7)

#define ISAC_SYSTICK_CSR_ENABLE     (1UL << 0)
#define ISAC_SYSTICK_CSR_TICKINT    (1UL << 1)
#define ISAC_SYSTICK_CSR_CLKSOURCE  (1UL << 2)
#define ISAC_SCB_SCR_SLEEPDEEP      (1UL << 2)
#define ISAC_SCB_AIRCR_SYSRESETREQ  0x05FA0004UL
#define ISAC_DCB_DHCSR_C_DEBUGEN    (1UL << 0)

/* =========================================================================
 * 5. Compile-Time CMSIS / RM0453 Register-Map Offset Verification (F-01)
 * ========================================================================= */
/* GPIO (RM0453 §9.4) */
_Static_assert(offsetof(ISAC_GPIO_Regs_t, MODER)   == 0x00U, "GPIO MODER offset");
_Static_assert(offsetof(ISAC_GPIO_Regs_t, OTYPER)  == 0x04U, "GPIO OTYPER offset");
_Static_assert(offsetof(ISAC_GPIO_Regs_t, OSPEEDR) == 0x08U, "GPIO OSPEEDR offset");
_Static_assert(offsetof(ISAC_GPIO_Regs_t, PUPDR)   == 0x0CU, "GPIO PUPDR offset");
_Static_assert(offsetof(ISAC_GPIO_Regs_t, IDR)     == 0x10U, "GPIO IDR offset");
_Static_assert(offsetof(ISAC_GPIO_Regs_t, ODR)     == 0x14U, "GPIO ODR offset");
_Static_assert(offsetof(ISAC_GPIO_Regs_t, BSRR)    == 0x18U, "GPIO BSRR offset");
_Static_assert(offsetof(ISAC_GPIO_Regs_t, LCKR)    == 0x1CU, "GPIO LCKR offset");
_Static_assert(offsetof(ISAC_GPIO_Regs_t, AFRL)    == 0x20U, "GPIO AFRL offset");
_Static_assert(offsetof(ISAC_GPIO_Regs_t, AFRH)    == 0x24U, "GPIO AFRH offset");
_Static_assert(offsetof(ISAC_GPIO_Regs_t, BRR)     == 0x28U, "GPIO BRR offset");

/* RCC (RM0453 §7.4) */
_Static_assert(offsetof(ISAC_RCC_Regs_t, CR)        == 0x00U, "RCC CR offset");
_Static_assert(offsetof(ISAC_RCC_Regs_t, ICSCR)     == 0x04U, "RCC ICSCR offset");
_Static_assert(offsetof(ISAC_RCC_Regs_t, CFGR)      == 0x08U, "RCC CFGR offset");
_Static_assert(offsetof(ISAC_RCC_Regs_t, PLLCFGR)   == 0x0CU, "RCC PLLCFGR offset");
_Static_assert(offsetof(ISAC_RCC_Regs_t, AHB1RSTR)  == 0x28U, "RCC AHB1RSTR offset");
_Static_assert(offsetof(ISAC_RCC_Regs_t, AHB2RSTR)  == 0x2CU, "RCC AHB2RSTR offset");
_Static_assert(offsetof(ISAC_RCC_Regs_t, AHB3RSTR)  == 0x30U, "RCC AHB3RSTR offset");
_Static_assert(offsetof(ISAC_RCC_Regs_t, APB1RSTR1) == 0x38U, "RCC APB1RSTR1 offset");
_Static_assert(offsetof(ISAC_RCC_Regs_t, APB1RSTR2) == 0x3CU, "RCC APB1RSTR2 offset");
_Static_assert(offsetof(ISAC_RCC_Regs_t, APB2RSTR)  == 0x40U, "RCC APB2RSTR offset");
_Static_assert(offsetof(ISAC_RCC_Regs_t, APB3RSTR)  == 0x44U, "RCC APB3RSTR offset");
_Static_assert(offsetof(ISAC_RCC_Regs_t, AHB1ENR)   == 0x48U, "RCC AHB1ENR offset");
_Static_assert(offsetof(ISAC_RCC_Regs_t, AHB2ENR)   == 0x4CU, "RCC AHB2ENR offset");
_Static_assert(offsetof(ISAC_RCC_Regs_t, AHB3ENR)   == 0x50U, "RCC AHB3ENR offset");
_Static_assert(offsetof(ISAC_RCC_Regs_t, APB1ENR1)  == 0x58U, "RCC APB1ENR1 offset");
_Static_assert(offsetof(ISAC_RCC_Regs_t, APB1ENR2)  == 0x5CU, "RCC APB1ENR2 offset");
_Static_assert(offsetof(ISAC_RCC_Regs_t, APB2ENR)   == 0x60U, "RCC APB2ENR offset");
_Static_assert(offsetof(ISAC_RCC_Regs_t, APB3ENR)   == 0x64U, "RCC APB3ENR offset");
_Static_assert(offsetof(ISAC_RCC_Regs_t, CCIPR)     == 0x88U, "RCC CCIPR offset");
_Static_assert(offsetof(ISAC_RCC_Regs_t, BDCR)      == 0x90U, "RCC BDCR offset");
_Static_assert(offsetof(ISAC_RCC_Regs_t, CSR)       == 0x94U, "RCC CSR offset");

/* PWR (RM0453 §6.6 — F-01 critical fix: SR1=0x10, SR2=0x14, SCR=0x18, CR5=0x1C) */
_Static_assert(offsetof(ISAC_PWR_Regs_t, CR1)         == 0x00U, "PWR CR1 offset");
_Static_assert(offsetof(ISAC_PWR_Regs_t, CR2)         == 0x04U, "PWR CR2 offset");
_Static_assert(offsetof(ISAC_PWR_Regs_t, CR3)         == 0x08U, "PWR CR3 offset");
_Static_assert(offsetof(ISAC_PWR_Regs_t, CR4)         == 0x0CU, "PWR CR4 offset");
_Static_assert(offsetof(ISAC_PWR_Regs_t, SR1)         == 0x10U, "PWR SR1 offset");
_Static_assert(offsetof(ISAC_PWR_Regs_t, SR2)         == 0x14U, "PWR SR2 offset");
_Static_assert(offsetof(ISAC_PWR_Regs_t, SCR)         == 0x18U, "PWR SCR offset");
_Static_assert(offsetof(ISAC_PWR_Regs_t, CR5)         == 0x1CU, "PWR CR5 offset");
_Static_assert(offsetof(ISAC_PWR_Regs_t, SUBGHZSPICR) == 0x90U, "PWR SUBGHZSPICR offset");

/* ADC & ADC_Common (RM0453 §15.11, ADC_COMMON_BASE = ADC_BASE + 0x308) */
_Static_assert(offsetof(ISAC_ADC_Regs_t, ISR)    == 0x00U, "ADC ISR offset");
_Static_assert(offsetof(ISAC_ADC_Regs_t, IER)    == 0x04U, "ADC IER offset");
_Static_assert(offsetof(ISAC_ADC_Regs_t, CR)     == 0x08U, "ADC CR offset");
_Static_assert(offsetof(ISAC_ADC_Regs_t, CFGR1)  == 0x0CU, "ADC CFGR1 offset");
_Static_assert(offsetof(ISAC_ADC_Regs_t, CFGR2)  == 0x10U, "ADC CFGR2 offset");
_Static_assert(offsetof(ISAC_ADC_Regs_t, SMPR)   == 0x14U, "ADC SMPR offset");
_Static_assert(offsetof(ISAC_ADC_Regs_t, TR1)    == 0x20U, "ADC TR1 offset");
_Static_assert(offsetof(ISAC_ADC_Regs_t, TR2)    == 0x24U, "ADC TR2 offset");
_Static_assert(offsetof(ISAC_ADC_Regs_t, CHSELR) == 0x28U, "ADC CHSELR offset");
_Static_assert(offsetof(ISAC_ADC_Regs_t, TR3)    == 0x2CU, "ADC TR3 offset");
_Static_assert(offsetof(ISAC_ADC_Regs_t, DR)     == 0x40U, "ADC DR offset");
_Static_assert(offsetof(ISAC_ADC_Common_Regs_t, CCR) == 0x00U, "ADC CCR offset");
_Static_assert((ISAC_ADC_COMMON_BASE - ISAC_ADC_BASE) == 0x308UL, "ADC_COMMON +0x308 offset");

/* SPI / SUBGHZSPI (RM0453 §33.7) */
_Static_assert(offsetof(ISAC_SPI_Regs_t, CR1) == 0x00U, "SPI CR1 offset");
_Static_assert(offsetof(ISAC_SPI_Regs_t, CR2) == 0x04U, "SPI CR2 offset");
_Static_assert(offsetof(ISAC_SPI_Regs_t, SR)  == 0x08U, "SPI SR offset");
_Static_assert(offsetof(ISAC_SPI_Regs_t, DR)  == 0x0CU, "SPI DR offset");

/* RTC3 (RM0453 §27.7) */
_Static_assert(offsetof(ISAC_RTC_Regs_t, TR)       == 0x00U, "RTC TR offset");
_Static_assert(offsetof(ISAC_RTC_Regs_t, DR)       == 0x04U, "RTC DR offset");
_Static_assert(offsetof(ISAC_RTC_Regs_t, SSR)      == 0x08U, "RTC SSR offset");
_Static_assert(offsetof(ISAC_RTC_Regs_t, ICSR)     == 0x0CU, "RTC ICSR offset");
_Static_assert(offsetof(ISAC_RTC_Regs_t, PRER)     == 0x10U, "RTC PRER offset");
_Static_assert(offsetof(ISAC_RTC_Regs_t, WUTR)     == 0x14U, "RTC WUTR offset");
_Static_assert(offsetof(ISAC_RTC_Regs_t, CR)       == 0x18U, "RTC CR offset");
_Static_assert(offsetof(ISAC_RTC_Regs_t, WPR)      == 0x24U, "RTC WPR offset");
_Static_assert(offsetof(ISAC_RTC_Regs_t, CALR)     == 0x28U, "RTC CALR offset");
_Static_assert(offsetof(ISAC_RTC_Regs_t, SHIFTR)   == 0x2CU, "RTC SHIFTR offset");
_Static_assert(offsetof(ISAC_RTC_Regs_t, TSTR)     == 0x30U, "RTC TSTR offset");
_Static_assert(offsetof(ISAC_RTC_Regs_t, TSDR)     == 0x34U, "RTC TSDR offset");
_Static_assert(offsetof(ISAC_RTC_Regs_t, TSSSR)    == 0x38U, "RTC TSSSR offset");
_Static_assert(offsetof(ISAC_RTC_Regs_t, ALRMAR)   == 0x40U, "RTC ALRMAR offset");
_Static_assert(offsetof(ISAC_RTC_Regs_t, ALRMASSR) == 0x44U, "RTC ALRMASSR offset");
_Static_assert(offsetof(ISAC_RTC_Regs_t, ALRMBR)   == 0x48U, "RTC ALRMBR offset");
_Static_assert(offsetof(ISAC_RTC_Regs_t, ALRMBSSR) == 0x4CU, "RTC ALRMBSSR offset");
_Static_assert(offsetof(ISAC_RTC_Regs_t, SR)       == 0x50U, "RTC SR offset");
_Static_assert(offsetof(ISAC_RTC_Regs_t, MISR)     == 0x54U, "RTC MISR offset");
_Static_assert(offsetof(ISAC_RTC_Regs_t, SCR)      == 0x5CU, "RTC SCR offset");

/* EXTI (RM0453 §13.5) */
_Static_assert(offsetof(ISAC_EXTI_Regs_t, RTSR1)  == 0x00U, "EXTI RTSR1 offset");
_Static_assert(offsetof(ISAC_EXTI_Regs_t, FTSR1)  == 0x04U, "EXTI FTSR1 offset");
_Static_assert(offsetof(ISAC_EXTI_Regs_t, SWIER1) == 0x08U, "EXTI SWIER1 offset");
_Static_assert(offsetof(ISAC_EXTI_Regs_t, PR1)    == 0x0CU, "EXTI PR1 offset");
_Static_assert(offsetof(ISAC_EXTI_Regs_t, IMR1)   == 0x80U, "EXTI IMR1 offset");
_Static_assert(offsetof(ISAC_EXTI_Regs_t, EMR1)   == 0x84U, "EXTI EMR1 offset");

/* Cortex-M4 SysTick & SCB */
_Static_assert(offsetof(ISAC_SysTick_Regs_t, CSR)   == 0x00U, "SysTick CSR offset");
_Static_assert(offsetof(ISAC_SysTick_Regs_t, RVR)   == 0x04U, "SysTick RVR offset");
_Static_assert(offsetof(ISAC_SysTick_Regs_t, CVR)   == 0x08U, "SysTick CVR offset");
_Static_assert(offsetof(ISAC_SysTick_Regs_t, CALIB) == 0x0CU, "SysTick CALIB offset");
_Static_assert(offsetof(ISAC_SCB_Regs_t, CPUID)     == 0x00U, "SCB CPUID offset");
_Static_assert(offsetof(ISAC_SCB_Regs_t, ICSR)      == 0x04U, "SCB ICSR offset");
_Static_assert(offsetof(ISAC_SCB_Regs_t, VTOR)      == 0x08U, "SCB VTOR offset");
_Static_assert(offsetof(ISAC_SCB_Regs_t, AIRCR)     == 0x0CU, "SCB AIRCR offset");
_Static_assert(offsetof(ISAC_SCB_Regs_t, SCR)       == 0x10U, "SCB SCR offset");

#endif /* ISAC_BOARD_PINS_H */
