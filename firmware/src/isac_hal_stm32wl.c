/**
 * @file isac_hal_stm32wl.c
 * @brief Bare-Metal STM32WLE5JC (RAK3172LP-SiP) Hardware Register Driver
 */
#include "isac_hal.h"
#include "isac_board_pins.h"
#include "isac_sensing.h"

#include <stddef.h>

/* Default 4 MHz MSI startup clock -> 4,000 cycles per 1 ms SysTick tick */
#define ISAC_MSI_DEFAULT_HZ             4000000UL
#define ISAC_MSI_DEFAULT_CYCLES_PER_US  4UL
#define ISAC_HW_TIMEOUT_LOOPS           200000UL
#define ISAC_LSE_TIMEOUT_LOOPS          1000000UL

static volatile uint32_t g_systick_ms      = 0UL;
static uint32_t          g_rtc_period_ms   = ISAC_DEFAULT_REPORT_PERIOD_S * 1000UL;
static volatile uint32_t g_rtc_wakeup_hits = 0UL;
static bool              g_subghz_sleeping = false;

static void systick_init_1ms(void)
{
    ISAC_SYSTICK->CSR = 0UL;
    ISAC_SYSTICK->RVR = (ISAC_MSI_DEFAULT_HZ / 1000UL) - 1UL;
    ISAC_SYSTICK->CVR = 0UL;
    ISAC_SYSTICK->CSR = ISAC_SYSTICK_CSR_CLKSOURCE
                      | ISAC_SYSTICK_CSR_TICKINT
                      | ISAC_SYSTICK_CSR_ENABLE;
}

void SysTick_Handler(void)
{
    g_systick_ms = g_systick_ms + 1UL;
}

void RTC_WKUP_IRQHandler(void)
{
    if ((ISAC_RTC->SR & ISAC_RTC_SR_WUTF) != 0UL) {
        ISAC_RTC->SCR = ISAC_RTC_SCR_CWUTF;
    }
    g_rtc_wakeup_hits = g_rtc_wakeup_hits + 1UL;
}

uint32_t ISAC_HAL_GetTickMs(void)
{
    return g_systick_ms;
}

void ISAC_HAL_DelayUs(uint32_t us)
{
    if (us == 0UL) {
        return;
    }
    /* BLK-06 fix: Hardware wrap-safe SysTick->CVR tick accumulator (exact 4.00 ticks/us @ 4 MHz MSI) */
    if ((ISAC_SYSTICK->CSR & ISAC_SYSTICK_CSR_ENABLE) != 0UL) {
        const uint32_t reload    = ISAC_SYSTICK->RVR + 1UL;
        uint32_t       remaining = us * ISAC_MSI_DEFAULT_CYCLES_PER_US;
        uint32_t       prev      = ISAC_SYSTICK->CVR;
        while (remaining > 0UL) {
            const uint32_t now   = ISAC_SYSTICK->CVR;
            const uint32_t delta = (now <= prev) ? (prev - now) : (prev + reload - now);
            prev = now;
            if (delta >= remaining) {
                break;
            }
            remaining -= delta;
        }
        return;
    }
    /* Pre-SysTick fallback: calibrated register-only loop (nop=1 + subs=1 + bne=2 -> 4.0 cycles/us) */
    __asm volatile (
        "1:\n\t"
        "nop\n\t"
        "subs %[cnt], %[cnt], #1\n\t"
        "bne 1b\n\t"
        : [cnt] "+r" (us)
        :
        : "cc"
    );
}

void ISAC_HAL_DelayMs(uint32_t ms)
{
    const uint32_t start = ISAC_HAL_GetTickMs();
    while ((ISAC_HAL_GetTickMs() - start) < ms) {
        __asm volatile ("wfi");
    }
}

static bool wait_rfbusy_low(void)
{
    uint32_t guard = ISAC_HW_TIMEOUT_LOOPS;
    while (((ISAC_PWR->SR2 & ISAC_PWR_SR2_RFBUSYS) != 0UL) && (guard > 0UL)) {
        --guard;
    }
    return ((ISAC_PWR->SR2 & ISAC_PWR_SR2_RFBUSYS) == 0UL);
}

static bool subghz_spi_xfer(uint8_t tx_byte, uint8_t *out_rx)
{
    uint32_t guard = ISAC_HW_TIMEOUT_LOOPS;
    while (((ISAC_SUBGHZSPI->SR & ISAC_SPI_SR_TXE) == 0UL) && (guard > 0UL)) {
        --guard;
    }
    if ((ISAC_SUBGHZSPI->SR & ISAC_SPI_SR_TXE) == 0UL) {
        return false;
    }
    *((volatile uint8_t *)&ISAC_SUBGHZSPI->DR) = tx_byte;

    guard = ISAC_HW_TIMEOUT_LOOPS;
    while (((ISAC_SUBGHZSPI->SR & ISAC_SPI_SR_RXNE) == 0UL) && (guard > 0UL)) {
        --guard;
    }
    if ((ISAC_SUBGHZSPI->SR & ISAC_SPI_SR_RXNE) == 0UL) {
        return false;
    }
    const uint8_t rx_byte = *((volatile uint8_t *)&ISAC_SUBGHZSPI->DR);
    if (out_rx != NULL) {
        *out_rx = rx_byte;
    }
    return true;
}

static bool subghz_nss_release(void)
{
    uint32_t guard = ISAC_HW_TIMEOUT_LOOPS;
    while (((ISAC_SUBGHZSPI->SR & ISAC_SPI_SR_BSY) != 0UL) && (guard > 0UL)) {
        --guard;
    }
    ISAC_PWR->SUBGHZSPICR = ISAC_PWR_SUBGHZSPICR_NSS;
    return ((ISAC_SUBGHZSPI->SR & ISAC_SPI_SR_BSY) == 0UL);
}

void ISAC_HAL_GPIO_InitBoardPins(void)
{
    /* Enable GPIOA, GPIOB, GPIOC peripheral clocks & 1 ms SysTick timebase */
    ISAC_RCC->AHB2ENR |= (ISAC_RCC_AHB2ENR_GPIOAEN |
                          ISAC_RCC_AHB2ENR_GPIOBEN |
                          ISAC_RCC_AHB2ENR_GPIOCEN);
    (void)ISAC_RCC->AHB2ENR;
    systick_init_1ms();

    /* 0. MED-05 fix: Lock ALL unused GPIOA, GPIOB, GPIOC pins to Analog mode (MODER = 0b11, PUPDR = 0)
     *    before configuring active pins, preserving PA13/PA14 (SWDIO/SWCLK AF0) so STOP2 Schmitt-trigger
     *    input leakage is strictly 0 nA across all 29+ unbonded/unused MCU pads (including PB3 JTDO). */
    ISAC_GPIOA->MODER = 0xEBFFFFFFUL; /* All Analog (0b11), except PA13/PA14 = AF (0b10) */
    ISAC_GPIOA->PUPDR = ISAC_GPIOA->PUPDR & (0xFUL << (ISAC_GPIOA_PIN_SWDIO * 2U));
    ISAC_GPIOB->MODER = 0xFFFFFFFFUL; /* All PB0..PB15 Analog (0b11), clears PB3 JTDO AF0 */
    ISAC_GPIOB->PUPDR = 0x00000000UL;
    ISAC_GPIOC->MODER = 0xFFFFFFFFUL; /* All PC0..PC15 Analog (0b11) */
    ISAC_GPIOC->PUPDR = 0x00000000UL;

    /* 1. PA8 (SiP Pin 51, DET_EN) & PA9 (SiP Pin 50, BAT_MON_EN):
     *    Push-pull outputs, default LOW (0 nA sleep drain; independent Q1 LT5538 & Q2 VBAT gating) */
    ISAC_GPIOA->BSRR   = (1UL << (ISAC_GPIOA_PIN_DET_EN + 16U))
                       | (1UL << (ISAC_GPIOA_PIN_BAT_MON_EN + 16U));
    ISAC_GPIOA->MODER  = (ISAC_GPIOA->MODER & ~((3UL << (ISAC_GPIOA_PIN_DET_EN * 2U)) |
                                                (3UL << (ISAC_GPIOA_PIN_BAT_MON_EN * 2U))))
                       | (1UL << (ISAC_GPIOA_PIN_DET_EN * 2U))
                       | (1UL << (ISAC_GPIOA_PIN_BAT_MON_EN * 2U));
    ISAC_GPIOA->OTYPER &= ~((1UL << ISAC_GPIOA_PIN_DET_EN) |
                            (1UL << ISAC_GPIOA_PIN_BAT_MON_EN));
    ISAC_GPIOA->PUPDR  &= ~((3UL << (ISAC_GPIOA_PIN_DET_EN * 2U)) |
                            (3UL << (ISAC_GPIOA_PIN_BAT_MON_EN * 2U)));

    /* 2. PA15 (SiP Pin 8, ADC_IN11 DET_ADC) & PB4 (SiP Pin 15, ADC_IN3 BAT_SENSE):
     *    Analog mode (MODER = 0b11, PUPDR = 0b00) -> zero Schmitt-trigger sleep leakage! */
    ISAC_GPIOA->MODER |=  (3UL << (ISAC_GPIOA_PIN_DET_ADC * 2U));
    ISAC_GPIOA->PUPDR &= ~(3UL << (ISAC_GPIOA_PIN_DET_ADC * 2U));

    ISAC_GPIOB->MODER |=  (3UL << (ISAC_GPIOB_PIN_BAT_SENSE * 2U));
    ISAC_GPIOB->PUPDR &= ~(3UL << (ISAC_GPIOB_PIN_BAT_SENSE * 2U));

    /* 3. Internal RAK3172LP-SiP SPDT RF Switch (CRIT-02 fix!):
     *    PA0 (VC1) & PA1 (VC2) push-pull LOW (0,0 = isolated 0 nA STOP2 state) */
    ISAC_GPIOA->BSRR   = (1UL << (ISAC_GPIOA_PIN_RFSW_VC1 + 16U))
                       | (1UL << (ISAC_GPIOA_PIN_RFSW_VC2 + 16U));
    ISAC_GPIOA->MODER  = (ISAC_GPIOA->MODER & ~((3UL << (ISAC_GPIOA_PIN_RFSW_VC1 * 2U)) |
                                                (3UL << (ISAC_GPIOA_PIN_RFSW_VC2 * 2U))))
                       | (1UL << (ISAC_GPIOA_PIN_RFSW_VC1 * 2U))
                       | (1UL << (ISAC_GPIOA_PIN_RFSW_VC2 * 2U));
    ISAC_GPIOA->OTYPER &= ~((1UL << ISAC_GPIOA_PIN_RFSW_VC1) |
                            (1UL << ISAC_GPIOA_PIN_RFSW_VC2));
    ISAC_GPIOA->PUPDR  &= ~((3UL << (ISAC_GPIOA_PIN_RFSW_VC1 * 2U)) |
                            (3UL << (ISAC_GPIOA_PIN_RFSW_VC2 * 2U)));

    /* 4. HIGH-05 fix: Leave PA2 / PA3 (SiP Pins 29/30, USART2) in Analog High-Z (MODER = 0b11, PUPDR = 0)
     *    established in step 0 so unpopulated J5 never floats a digital Schmitt-trigger input in STOP2.
     *    Bench diagnostics opt in explicitly via ISAC_HAL_UART2_InitDiagnostic(). */
    ISAC_GPIOA->MODER |=  ((3UL << (ISAC_GPIOA_PIN_UART2_TX * 2U)) |
                           (3UL << (ISAC_GPIOA_PIN_UART2_RX * 2U)));
    ISAC_GPIOA->PUPDR &= ~((3UL << (ISAC_GPIOA_PIN_UART2_TX * 2U)) |
                           (3UL << (ISAC_GPIOA_PIN_UART2_RX * 2U)));
}

void ISAC_HAL_UART2_InitDiagnostic(void)
{
    ISAC_RCC->AHB2ENR  |= ISAC_RCC_AHB2ENR_GPIOAEN;
    ISAC_RCC->APB1ENR1 |= ISAC_RCC_APB1ENR1_USART2EN;
    (void)ISAC_RCC->APB1ENR1;
    ISAC_GPIOA->PUPDR = (ISAC_GPIOA->PUPDR & ~((3UL << (ISAC_GPIOA_PIN_UART2_TX * 2U)) |
                                               (3UL << (ISAC_GPIOA_PIN_UART2_RX * 2U))))
                      | (1UL << (ISAC_GPIOA_PIN_UART2_RX * 2U)); /* Weak pull-up on RX when enabled */
    ISAC_GPIOA->MODER = (ISAC_GPIOA->MODER & ~((3UL << (ISAC_GPIOA_PIN_UART2_TX * 2U)) |
                                               (3UL << (ISAC_GPIOA_PIN_UART2_RX * 2U))))
                      | (2UL << (ISAC_GPIOA_PIN_UART2_TX * 2U))
                      | (2UL << (ISAC_GPIOA_PIN_UART2_RX * 2U));
    ISAC_GPIOA->AFRL  = (ISAC_GPIOA->AFRL & ~((0xFUL << (ISAC_GPIOA_PIN_UART2_TX * 4U)) |
                                              (0xFUL << (ISAC_GPIOA_PIN_UART2_RX * 4U))))
                      | (7UL << (ISAC_GPIOA_PIN_UART2_TX * 4U))
                      | (7UL << (ISAC_GPIOA_PIN_UART2_RX * 4U));
}

void ISAC_HAL_GPIO_SetDetEnable(bool enable)
{
    if (enable) {
        ISAC_GPIOA->BSRR = (1UL << ISAC_GPIOA_PIN_DET_EN);
    } else {
        ISAC_GPIOA->BSRR = (1UL << (ISAC_GPIOA_PIN_DET_EN + 16U));
    }
}

void ISAC_HAL_GPIO_SetBatMonEnable(bool enable)
{
    if (enable) {
        ISAC_GPIOA->BSRR = (1UL << ISAC_GPIOA_PIN_BAT_MON_EN);
    } else {
        ISAC_GPIOA->BSRR = (1UL << (ISAC_GPIOA_PIN_BAT_MON_EN + 16U));
    }
}

void ISAC_HAL_RFSwitch_SetMode(isac_rf_switch_mode_t mode)
{
    switch (mode) {
    case ISAC_RFSW_RX:
        /* RX (Pin 37 RF_OUT -> internal SX1262 LNA): PA0 (VC1) = HIGH, PA1 (VC2) = LOW */
        ISAC_GPIOA->BSRR = (1UL << (ISAC_GPIOA_PIN_RFSW_VC2 + 16U))
                         | (1UL << ISAC_GPIOA_PIN_RFSW_VC1);
        break;
    case ISAC_RFSW_TX_LP:
        /* TX (SX1262 RFO_LP +14 dBm -> Pin 37 RF_OUT): PA0 (VC1) = LOW, PA1 (VC2) = HIGH */
        ISAC_GPIOA->BSRR = (1UL << (ISAC_GPIOA_PIN_RFSW_VC1 + 16U))
                         | (1UL << ISAC_GPIOA_PIN_RFSW_VC2);
        break;
    case ISAC_RFSW_OFF:
    default:
        /* IDLE / STOP2 (0 nA quiescent drain): PA0 (VC1) = LOW, PA1 (VC2) = LOW */
        ISAC_GPIOA->BSRR = (1UL << (ISAC_GPIOA_PIN_RFSW_VC1 + 16U))
                         | (1UL << (ISAC_GPIOA_PIN_RFSW_VC2 + 16U));
        break;
    }
}

bool ISAC_HAL_System_EnableSMPS(void)
{
    uint32_t guard = ISAC_HW_TIMEOUT_LOOPS;

    /* Engage STM32WLE5JC step-down SMPS buck converter (L_SMPS = 15 uH on Pins 10, 11, 13) */
    ISAC_PWR->CR5 |= ISAC_PWR_CR5_SMPSEN;
    while (((ISAC_PWR->SR2 & ISAC_PWR_SR2_SMPSRDY) == 0UL) && (guard > 0UL)) {
        --guard;
    }
    if (!ISAC_HAL_System_IsSMPSEnabled()) {
        /* BLK-03 safety: Immediately de-assert SMPSEN if SMPSRDY failed so LDO rail stays clean */
        ISAC_PWR->CR5 &= ~ISAC_PWR_CR5_SMPSEN;
        return false;
    }
    return true;
}

bool ISAC_HAL_System_IsSMPSEnabled(void)
{
    return (((ISAC_PWR->CR5 & ISAC_PWR_CR5_SMPSEN) != 0UL) &&
            ((ISAC_PWR->SR2 & ISAC_PWR_SR2_SMPSRDY) != 0UL));
}

void ISAC_HAL_RTC_InitWakeup(uint32_t period_s)
{
    uint32_t guard;
    uint32_t wut_reload;
    bool     use_lse = false;

    if (period_s == 0UL) {
        period_s = 1UL;
    }
    if (period_s > 65536UL) {
        period_s = 65536UL;
    }
    g_rtc_period_ms = period_s * 1000UL;
    wut_reload      = period_s - 1UL;

    /* 1. Enable RTC APB clock & unlock backup domain write protection (PWR_CR1_DBP) */
    ISAC_RCC->APB1ENR1 |= ISAC_RCC_APB1ENR1_RTCAPBEN;
    (void)ISAC_RCC->APB1ENR1;
    ISAC_PWR->CR1 |= ISAC_PWR_CR1_DBP;

    /* 2. Start RAK3172LP-SiP internal 32.768 kHz LSE crystal; fall back to 32 kHz LSI if fault */
    ISAC_RCC->BDCR |= ISAC_RCC_BDCR_LSEON;
    guard = ISAC_LSE_TIMEOUT_LOOPS;
    while (((ISAC_RCC->BDCR & ISAC_RCC_BDCR_LSERDY) == 0UL) && (guard > 0UL)) {
        --guard;
    }
    if ((ISAC_RCC->BDCR & ISAC_RCC_BDCR_LSERDY) != 0UL) {
        use_lse = true;
        if ((ISAC_RCC->BDCR & ISAC_RCC_BDCR_RTCSEL_MASK) != ISAC_RCC_BDCR_RTCSEL_LSE) {
            ISAC_RCC->BDCR = (ISAC_RCC->BDCR & ~ISAC_RCC_BDCR_RTCSEL_MASK) | ISAC_RCC_BDCR_RTCSEL_LSE;
        }
        /* HIGH-03 fix: Hardware-discipline 4 MHz MSI to +/-20 ppm 32.768 kHz LSE (+/-0.25% over -40..+85 C) */
        ISAC_RCC->CR |= ISAC_RCC_CR_MSIPLLEN;
    } else {
        ISAC_RCC->CSR |= ISAC_RCC_CSR_LSION;
        guard = ISAC_HW_TIMEOUT_LOOPS;
        while (((ISAC_RCC->CSR & ISAC_RCC_CSR_LSIRDY) == 0UL) && (guard > 0UL)) {
            --guard;
        }
        ISAC_RCC->BDCR = (ISAC_RCC->BDCR & ~ISAC_RCC_BDCR_RTCSEL_MASK) | ISAC_RCC_BDCR_RTCSEL_LSI;
    }
    ISAC_RCC->BDCR |= ISAC_RCC_BDCR_RTCEN;

    /* 3. Unlock RTC registers via WPR key sequence (0xCA, 0x53) */
    ISAC_RTC->WPR = 0xCAUL;
    ISAC_RTC->WPR = 0x53UL;

    /* 4. Configure 1 Hz ck_spre prescaler (127+1)*(255+1)=32768 for LSE, (127+1)*(249+1)=32000 for LSI */
    ISAC_RTC->ICSR |= ISAC_RTC_ICSR_INIT;
    guard = ISAC_HW_TIMEOUT_LOOPS;
    while (((ISAC_RTC->ICSR & ISAC_RTC_ICSR_INITF) == 0UL) && (guard > 0UL)) {
        --guard;
    }
    ISAC_RTC->PRER = (127UL << 16U) | (use_lse ? 255UL : 249UL);
    ISAC_RTC->ICSR &= ~ISAC_RTC_ICSR_INIT;

    /* 5. Program 16-bit RTC Wakeup Auto-Reload Timer (ck_spre = 1 Hz, WUTR = period_s - 1) */
    ISAC_RTC->CR &= ~(ISAC_RTC_CR_WUTE | ISAC_RTC_CR_WUTIE);
    guard = ISAC_HW_TIMEOUT_LOOPS;
    while (((ISAC_RTC->ICSR & ISAC_RTC_ICSR_WUTWF) == 0UL) && (guard > 0UL)) {
        --guard;
    }
    ISAC_RTC->SCR  = ISAC_RTC_SCR_CWUTF;
    ISAC_RTC->WUTR = wut_reload;
    ISAC_RTC->CR   = (ISAC_RTC->CR & ~ISAC_RTC_CR_WUCKSEL_MASK)
                   | ISAC_RTC_CR_WUCKSEL_CK_SPRE
                   | ISAC_RTC_CR_WUTIE
                   | ISAC_RTC_CR_WUTE;

    /* Re-lock RTC write protection */
    ISAC_RTC->WPR = 0xFFUL;

    /* 6. Unmask Direct EXTI Line 20 (RTC Wakeup) and enable NVIC IRQ 3 (RTC_WKUP_IRQn) */
    ISAC_EXTI->IMR1 |= ISAC_EXTI_IMR1_IM20;
    ISAC_NVIC_ICPR0  = (1UL << ISAC_RTC_WKUP_IRQn);
    ISAC_NVIC_ISER0  = (1UL << ISAC_RTC_WKUP_IRQn);
}

bool ISAC_HAL_SubGhz_WakeupAndReset(void)
{
    uint32_t guard = ISAC_HW_TIMEOUT_LOOPS;

    /* Enable internal SUBGHZSPI clock and release Sub-GHz radio reset */
    ISAC_RCC->APB3ENR |= ISAC_RCC_APB3ENR_SUBGHZSPIEN;
    (void)ISAC_RCC->APB3ENR;

    ISAC_RCC->CSR |= ISAC_RCC_CSR_RFRST;
    ISAC_HAL_DelayUs(20U);
    ISAC_RCC->CSR &= ~ISAC_RCC_CSR_RFRST;
    while (((ISAC_RCC->CSR & ISAC_RCC_CSR_RFRSTF) != 0UL) && (guard > 0UL)) {
        --guard;
    }
    if ((ISAC_RCC->CSR & ISAC_RCC_CSR_RFRSTF) != 0UL) {
        return false;
    }

    /* Configure internal SUBGHZSPI: Master, 8-bit, Mode 0, software NSS via PWR_SUBGHZSPICR */
    ISAC_PWR->SUBGHZSPICR = ISAC_PWR_SUBGHZSPICR_NSS;
    ISAC_SUBGHZSPI->CR1   = ISAC_SPI_CR1_MSTR | ISAC_SPI_CR1_SSI | ISAC_SPI_CR1_SSM;
    ISAC_SUBGHZSPI->CR2   = ISAC_SPI_CR2_FRXTH | ISAC_SPI_CR2_DS_8BIT;
    ISAC_SUBGHZSPI->CR1  |= ISAC_SPI_CR1_SPE;

    /* Pulse NSS low for 60 us to wake internal SX1262 from sleep */
    ISAC_PWR->SUBGHZSPICR = 0UL;
    ISAC_HAL_DelayUs(60U);
    ISAC_PWR->SUBGHZSPICR = ISAC_PWR_SUBGHZSPICR_NSS;
    g_subghz_sleeping     = false;
    return wait_rfbusy_low();
}

bool ISAC_HAL_SubGhz_EnsureAwake(void)
{
    /* HIGH-03 fix (RM0453 §5.7.2): Dedicated 60 us internal NSS low pulse + RFBUSYS=0 wait
     * before the first SUBGHZSPI opcode/register transfer whenever waking from SET_SLEEP! */
    if (g_subghz_sleeping) {
        ISAC_PWR->SUBGHZSPICR = 0UL;
        ISAC_HAL_DelayUs(60U);
        ISAC_PWR->SUBGHZSPICR = ISAC_PWR_SUBGHZSPICR_NSS;
        g_subghz_sleeping     = false;
    }
    return wait_rfbusy_low();
}

bool ISAC_HAL_SubGhz_WriteCmd(uint8_t opcode, const uint8_t *params, uint8_t len)
{
    uint8_t i;
    bool    ok;

    if (!ISAC_HAL_SubGhz_EnsureAwake()) {
        return false;
    }
    ISAC_PWR->SUBGHZSPICR = 0UL; /* Assert internal NSS */

    ok = subghz_spi_xfer(opcode, NULL);
    for (i = 0U; ok && (i < len); ++i) {
        ok = subghz_spi_xfer((params != NULL) ? params[i] : 0U, NULL);
    }

    if (!subghz_nss_release() || !ok) {
        return false;
    }
    if (opcode != ISAC_SUBGHZ_CMD_SET_SLEEP) {
        return wait_rfbusy_low();
    }
    g_subghz_sleeping = true;
    return true;
}

bool ISAC_HAL_SubGhz_ReadCmd(uint8_t opcode, uint8_t *rx_buf, uint8_t len)
{
    uint8_t i;
    bool    ok;

    if (!ISAC_HAL_SubGhz_EnsureAwake()) {
        return false;
    }
    ISAC_PWR->SUBGHZSPICR = 0UL;

    ok = subghz_spi_xfer(opcode, NULL);
    if (ok) {
        ok = subghz_spi_xfer(0x00U, NULL); /* SX1262 status byte */
    }
    for (i = 0U; ok && (i < len); ++i) {
        uint8_t b = 0U;
        ok = subghz_spi_xfer(0x00U, &b);
        if (ok && (rx_buf != NULL)) {
            rx_buf[i] = b;
        }
    }

    if (!subghz_nss_release() || !ok) {
        return false;
    }
    return wait_rfbusy_low();
}

bool ISAC_HAL_SubGhz_WriteReg(uint16_t addr, const uint8_t *data, uint8_t len)
{
    uint8_t i;
    bool    ok;

    if (!ISAC_HAL_SubGhz_EnsureAwake()) {
        return false;
    }
    ISAC_PWR->SUBGHZSPICR = 0UL;

    ok = subghz_spi_xfer(ISAC_SUBGHZ_CMD_WRITE_REGISTER, NULL) &&
         subghz_spi_xfer((uint8_t)((addr >> 8U) & 0xFFU), NULL) &&
         subghz_spi_xfer((uint8_t)(addr & 0xFFU), NULL);
    for (i = 0U; ok && (i < len); ++i) {
        ok = subghz_spi_xfer((data != NULL) ? data[i] : 0U, NULL);
    }

    if (!subghz_nss_release() || !ok) {
        return false;
    }
    return wait_rfbusy_low();
}

bool ISAC_HAL_SubGhz_ReadReg(uint16_t addr, uint8_t *data, uint8_t len)
{
    uint8_t i;
    bool    ok;

    if (!ISAC_HAL_SubGhz_EnsureAwake()) {
        return false;
    }
    ISAC_PWR->SUBGHZSPICR = 0UL;

    ok = subghz_spi_xfer(ISAC_SUBGHZ_CMD_READ_REGISTER, NULL) &&
         subghz_spi_xfer((uint8_t)((addr >> 8U) & 0xFFU), NULL) &&
         subghz_spi_xfer((uint8_t)(addr & 0xFFU), NULL) &&
         subghz_spi_xfer(0x00U, NULL); /* SX1262 status byte */
    for (i = 0U; ok && (i < len); ++i) {
        uint8_t b = 0U;
        ok = subghz_spi_xfer(0x00U, &b);
        if (ok && (data != NULL)) {
            data[i] = b;
        }
    }

    if (!subghz_nss_release() || !ok) {
        return false;
    }
    return wait_rfbusy_low();
}

bool ISAC_HAL_SubGhz_WriteBuffer(uint8_t offset, const uint8_t *data, uint8_t len)
{
    uint8_t i;
    bool    ok;

    if (!ISAC_HAL_SubGhz_EnsureAwake()) {
        return false;
    }
    ISAC_PWR->SUBGHZSPICR = 0UL;

    ok = subghz_spi_xfer(ISAC_SUBGHZ_CMD_WRITE_BUFFER, NULL) &&
         subghz_spi_xfer(offset, NULL);
    for (i = 0U; ok && (i < len); ++i) {
        ok = subghz_spi_xfer((data != NULL) ? data[i] : 0U, NULL);
    }

    if (!subghz_nss_release() || !ok) {
        return false;
    }
    return wait_rfbusy_low();
}

bool ISAC_HAL_SubGhz_ReadBuffer(uint8_t offset, uint8_t *data, uint8_t len)
{
    uint8_t i;
    bool    ok;

    if (!ISAC_HAL_SubGhz_EnsureAwake()) {
        return false;
    }
    ISAC_PWR->SUBGHZSPICR = 0UL;

    ok = subghz_spi_xfer(ISAC_SUBGHZ_CMD_READ_BUFFER, NULL) &&
         subghz_spi_xfer(offset, NULL) &&
         subghz_spi_xfer(0x00U, NULL); /* SX1262 status byte */
    for (i = 0U; ok && (i < len); ++i) {
        uint8_t b = 0U;
        ok = subghz_spi_xfer(0x00U, &b);
        if (ok && (data != NULL)) {
            data[i] = b;
        }
    }

    if (!subghz_nss_release() || !ok) {
        return false;
    }
    return wait_rfbusy_low();
}

void ISAC_HAL_ADC_EnableAndCalibrate(void)
{
    uint32_t guard;

    ISAC_RCC->APB2ENR |= ISAC_RCC_APB2ENR_ADCEN;
    (void)ISAC_RCC->APB2ENR;

    /* Ensure ADC is disabled before configuring clock mode & calibration */
    if ((ISAC_ADC->CR & ISAC_ADC_CR_ADEN) != 0UL) {
        ISAC_ADC->CR |= ISAC_ADC_CR_ADDIS;
        guard = ISAC_HW_TIMEOUT_LOOPS;
        while (((ISAC_ADC->CR & ISAC_ADC_CR_ADEN) != 0UL) && (guard > 0UL)) {
            --guard;
        }
    }

    /* 1. Select synchronous PCLK/2 SAR ADC clock BEFORE ADCAL (CRIT-04 fix!) */
    ISAC_ADC->CFGR2 = ISAC_ADC_CFGR2_CKMODE_PCLK2;

    /* 2. Enable internal ADC voltage regulator, VREFINT (ADC_IN13) & Die Temp Sensor (ADC_IN12);
     *    wait max(t_ADCVREG_STUP = 30 us, t_START_TEMPSENSOR = 120 us per DS13105 Table 68) */
    ISAC_ADC->CR |= ISAC_ADC_CR_ADVREGEN;
    ISAC_ADC_COMMON->CCR |= (ISAC_ADC_CCR_VREFEN | ISAC_ADC_CCR_TSEN);
    ISAC_HAL_DelayUs(120U);

    /* 3. Run hardware single-ended linearity calibration (OVSE must be 0 during ADCAL) */
    ISAC_ADC->CR |= ISAC_ADC_CR_ADCAL;
    guard = ISAC_HW_TIMEOUT_LOOPS;
    while (((ISAC_ADC->CR & ISAC_ADC_CR_ADCAL) != 0UL) && (guard > 0UL)) {
        --guard;
    }

    /* 4. HIGH-01 fix: Dual sample-time configuration @ 2 MHz PCLK/2:
     *    - SMP1 = 12.5 cycles (6.25 us, 200 us 16x oversample) for C_LPF=100nF DET_ADC (Ch 11)
     *    - SMP2 = 39.5 cycles (19.75 us > 12 us VREFINT & 15 us TS min, 416 us 16x oversample)
     *      selected via SMPSEL for BAT_SENSE (Ch 3), TEMPSENSOR (Ch 12), and VREFINT (Ch 13) */
    ISAC_ADC->SMPR  = ISAC_ADC_SMPR_SMP1_12P5
                    | ISAC_ADC_SMPR_SMP2_39P5
                    | ISAC_ADC_SMPR_SMPSEL_BIT(ISAC_ADC_CH_BAT_SENSE)
                    | ISAC_ADC_SMPR_SMPSEL_BIT(ISAC_ADC_CH_TEMPSENSOR)
                    | ISAC_ADC_SMPR_SMPSEL_BIT(ISAC_ADC_CH_VREFINT);
    ISAC_ADC->CFGR1 = 0UL;
    ISAC_ADC->CFGR2 = ISAC_ADC_CFGR2_CKMODE_PCLK2
                    | ISAC_ADC_CFGR2_OVSE
                    | ISAC_ADC_CFGR2_OVSR_16X;

    /* 5. Enable ADC and wait for ADRDY */
    ISAC_ADC->ISR = ISAC_ADC_ISR_ADRDY;
    ISAC_ADC->CR |= ISAC_ADC_CR_ADEN;
    guard = ISAC_HW_TIMEOUT_LOOPS;
    while (((ISAC_ADC->ISR & ISAC_ADC_ISR_ADRDY) == 0UL) && (guard > 0UL)) {
        --guard;
    }
}

uint32_t ISAC_HAL_ADC_ReadOversampled16x(uint8_t channel)
{
    uint32_t guard = ISAC_HW_TIMEOUT_LOOPS;

    ISAC_ADC->ISR    = ISAC_ADC_ISR_CCRDY | ISAC_ADC_ISR_EOC;
    ISAC_ADC->CHSELR = (1UL << (channel & 0x1FU));
    while (((ISAC_ADC->ISR & ISAC_ADC_ISR_CCRDY) == 0UL) && (guard > 0UL)) {
        --guard;
    }

    ISAC_ADC->CR |= ISAC_ADC_CR_ADSTART;
    guard = ISAC_HW_TIMEOUT_LOOPS;
    while (((ISAC_ADC->ISR & ISAC_ADC_ISR_EOC) == 0UL) && (guard > 0UL)) {
        --guard;
    }
    return (ISAC_ADC->DR & 0xFFFFUL);
}

void ISAC_HAL_ADC_Disable(void)
{
    uint32_t guard = ISAC_HW_TIMEOUT_LOOPS;
    if ((ISAC_ADC->CR & ISAC_ADC_CR_ADEN) != 0UL) {
        ISAC_ADC->CR |= ISAC_ADC_CR_ADDIS;
        while (((ISAC_ADC->CR & ISAC_ADC_CR_ADEN) != 0UL) && (guard > 0UL)) {
            --guard;
        }
    }
    ISAC_ADC->CR &= ~ISAC_ADC_CR_ADVREGEN;
    ISAC_ADC_COMMON->CCR &= ~(ISAC_ADC_CCR_VREFEN | ISAC_ADC_CCR_TSEN);
    ISAC_RCC->APB2ENR &= ~ISAC_RCC_APB2ENR_ADCEN;
}

uint16_t ISAC_HAL_ReadVrefintCal(void)
{
    return *((const volatile uint16_t *)ISAC_VREFINT_CAL_ADDR);
}

uint16_t ISAC_HAL_ReadTsCal1(void)
{
    return *((const volatile uint16_t *)ISAC_TS_CAL1_ADDR);
}

uint16_t ISAC_HAL_ReadTsCal2(void)
{
    return *((const volatile uint16_t *)ISAC_TS_CAL2_ADDR);
}

int16_t ISAC_HAL_ADC_ReadDieTempDegCx10(uint16_t vdda_mv)
{
    const uint16_t cal1  = ISAC_HAL_ReadTsCal1();
    const uint16_t cal2  = ISAC_HAL_ReadTsCal2();
    const uint32_t raw16 = ISAC_HAL_ADC_ReadOversampled16x(ISAC_ADC_CH_TEMPSENSOR);
    int32_t ts_3v0_x16, c1_x16, span_x16, num, delta_x10;

    if ((cal2 <= cal1) || (cal1 == 0U) || (vdda_mv == 0U) || (raw16 == 0UL)) {
        return 250; /* +25.0 C safe fallback if OTP calibration unprogrammed */
    }
    ts_3v0_x16 = (int32_t)((raw16 * (uint32_t)vdda_mv + 1500UL) / 3000UL);
    c1_x16     = (int32_t)cal1 * 16;
    span_x16   = (int32_t)(cal2 - cal1) * 16;
    num        = (ts_3v0_x16 - c1_x16) * 1000; /* (130.0 - 30.0 C) * 10 = 1000 */
    delta_x10  = (num >= 0) ? ((num + (span_x16 / 2)) / span_x16)
                            : ((num - (span_x16 / 2)) / span_x16);
    return (int16_t)(300 + delta_x10);
}

void ISAC_HAL_ReadUniqueId64(uint8_t uid_be[8])
{
    const volatile uint32_t *uid = (const volatile uint32_t *)ISAC_UID64_BASE;
    uint32_t w0, w1;

    if (uid_be == NULL) {
        return;
    }
    w0 = uid[0];
    w1 = uid[1];
    uid_be[0] = (uint8_t)((w1 >> 24U) & 0xFFU);
    uid_be[1] = (uint8_t)((w1 >> 16U) & 0xFFU);
    uid_be[2] = (uint8_t)((w1 >>  8U) & 0xFFU);
    uid_be[3] = (uint8_t)( w1         & 0xFFU);
    uid_be[4] = (uint8_t)((w0 >> 24U) & 0xFFU);
    uid_be[5] = (uint8_t)((w0 >> 16U) & 0xFFU);
    uid_be[6] = (uint8_t)((w0 >>  8U) & 0xFFU);
    uid_be[7] = (uint8_t)( w0         & 0xFFU);
}

static uint32_t rtc_tr_bcd_to_sec(uint32_t tr)
{
    const uint32_t ht  = (tr >> 20U) & 0x3UL;
    const uint32_t hu  = (tr >> 16U) & 0xFUL;
    const uint32_t mnt = (tr >> 12U) & 0x7UL;
    const uint32_t mnu = (tr >>  8U) & 0xFUL;
    const uint32_t st  = (tr >>  4U) & 0x7UL;
    const uint32_t su  =  tr         & 0xFUL;
    return (((ht * 10UL) + hu) * 3600UL)
         + (((mnt * 10UL) + mnu) * 60UL)
         + ((st * 10UL) + su);
}

static void rtc_read_consistent(uint32_t *out_ssr, uint32_t *out_tr)
{
    /* RM0453 §27.3.8: Read SSR, TR, DR twice until identical to guarantee shadow-coherent snapshot */
    uint32_t s0, t0, s1, t1;
    uint32_t guard = 8UL;
    s1 = ISAC_RTC->SSR & 0xFFFFUL;
    t1 = ISAC_RTC->TR  & 0x003F7F7FUL;
    (void)ISAC_RTC->DR;
    do {
        s0 = s1;
        t0 = t1;
        s1 = ISAC_RTC->SSR & 0xFFFFUL;
        t1 = ISAC_RTC->TR  & 0x003F7F7FUL;
        (void)ISAC_RTC->DR;
        --guard;
    } while (((s0 != s1) || (t0 != t1)) && (guard > 0UL));
    *out_ssr = s1;
    *out_tr  = t1;
}

void ISAC_HAL_EnterStop2(void)
{
    const bool rtc_on = ((ISAC_RCC->BDCR & ISAC_RCC_BDCR_RTCEN) != 0UL);
    uint32_t   ssr0 = 0UL, tr0 = 0UL, ssr1 = 0UL, tr1 = 0UL;
    uint32_t   elapsed_ms = g_rtc_period_ms;

    /* Suspend SysTick during STOP2 so pending TICKINT never aborts WFI entry */
    ISAC_SYSTICK->CSR &= ~ISAC_SYSTICK_CSR_TICKINT;

    if (rtc_on) {
        rtc_read_consistent(&ssr0, &tr0);
    }

    /* Select STOP2 (~1.74 uA typ on RAK3172LP-SiP with 32.768 kHz LSE + RTC WUT wakeup) */
    ISAC_PWR->SCR = ISAC_PWR_SCR_CWUF;
    ISAC_PWR->CR1 = (ISAC_PWR->CR1 & ~ISAC_PWR_CR1_LPMS_MASK) | ISAC_PWR_CR1_LPMS_STOP2;
    ISAC_SCB->SCR |= ISAC_SCB_SCR_SLEEPDEEP;
    __asm volatile ("dsb 0xF" ::: "memory");
    __asm volatile ("wfi");
    __asm volatile ("isb 0xF" ::: "memory");
    ISAC_SCB->SCR &= ~ISAC_SCB_SCR_SLEEPDEEP;

    /* Re-engage LSE hardware PLL auto-trim on 4 MHz MSI after STOP2 exit (HIGH-03) */
    if ((ISAC_RCC->BDCR & ISAC_RCC_BDCR_LSERDY) != 0UL) {
        ISAC_RCC->CR |= ISAC_RCC_CR_MSIPLLEN;
    }

    /* HIGH-02 fix: Compute true elapsed STOP2 sleep milliseconds from hardware RTC calendar + SSR
     * so spurious/early EXTI wakeups never jump g_systick_ms forward by 900 s and bypass ETSI duty guards! */
    if (rtc_on) {
        uint32_t guard = ISAC_HW_TIMEOUT_LOOPS;
        ISAC_RTC->ICSR &= ~ISAC_RTC_ICSR_RSF;
        while (((ISAC_RTC->ICSR & ISAC_RTC_ICSR_RSF) == 0UL) && (guard > 0UL)) {
            --guard;
        }
        rtc_read_consistent(&ssr1, &tr1);
        if ((ssr1 != ssr0) || (tr1 != tr0)) {
            const uint32_t s_div   = (ISAC_RTC->PRER & 0x7FFFUL) + 1UL;
            const uint32_t sec0    = rtc_tr_bcd_to_sec(tr0);
            const uint32_t sec1    = rtc_tr_bcd_to_sec(tr1);
            const uint32_t d_sec   = (sec1 >= sec0) ? (sec1 - sec0) : ((sec1 + 86400UL) - sec0);
            const int32_t  d_sub   = ((int32_t)ssr0 - (int32_t)ssr1) * 1000;
            const int32_t  sub_ms  = (s_div > 0UL) ? (d_sub / (int32_t)s_div) : 0;
            const int32_t  tot_ms  = ((int32_t)d_sec * 1000) + sub_ms;
            elapsed_ms = (tot_ms > 0) ? (uint32_t)tot_ms : 1UL;
        }
    }

    g_systick_ms = g_systick_ms + elapsed_ms;
    systick_init_1ms();
}


/* =========================================================================
 * Rev E.2: Flash (session NVM), reset cause, option bytes, IWDG
 *   Register map per RM0453 (FLASH @0x58004000, IWDG @0x40003000, RCC_CSR @+0x94).
 *   NOTE: no on-target execution evidence yet -- verify on first prototype (docs/OPEN_ITEMS.md O-07).
 * ========================================================================= */
#include "isac_nvm.h"

#define ISAC_FLASH_BASE_ADDR   0x58004000UL
#define ISAC_FLASH_REG(off)    (*((volatile uint32_t *)(ISAC_FLASH_BASE_ADDR + (off))))
#define ISAC_FLASH_ACR         ISAC_FLASH_REG(0x00UL)
#define ISAC_FLASH_KEYR        ISAC_FLASH_REG(0x08UL)
#define ISAC_FLASH_SR          ISAC_FLASH_REG(0x10UL)
#define ISAC_FLASH_CR          ISAC_FLASH_REG(0x14UL)
#define ISAC_FLASH_ECCR        ISAC_FLASH_REG(0x18UL)  /* RM0453 Rev 6 §4.10.4: 72-bit SECDED ECC register */
#define ISAC_FLASH_OPTR        ISAC_FLASH_REG(0x20UL)
#define ISAC_FLASH_ECCR_ECCC   (1UL << 30)             /* Single-bit ECC correction flag (write 1 to clear) */
#define ISAC_FLASH_ECCR_ECCD   (1UL << 31)             /* Double-bit ECC NMI fault flag (write 1 to clear)  */
#define ISAC_FLASH_ACR_DCEN    (1UL << 10)  /* RM0453 Rev 6 §4.10.1 p. 130: CPU1 data cache enable */
#define ISAC_FLASH_ACR_DCRST   (1UL << 12)  /* RM0453 Rev 6 §4.10.1 p. 130: CPU1 data cache reset  */
#define ISAC_FLASH_SR_BSY      (1UL << 16)
#define ISAC_FLASH_SR_CFGBSY   (1UL << 18)
#define ISAC_FLASH_SR_ERRORS   0x0000C3FAUL  /* OPERR,PROGERR,WRPERR,PGAERR,SIZERR,PGSERR,MISERR,FASTERR,RDERR,OPTVERR */
#define ISAC_FLASH_CR_PG       (1UL << 0)
#define ISAC_FLASH_CR_PER      (1UL << 1)
#define ISAC_FLASH_CR_PNB_POS  3U
#define ISAC_FLASH_CR_PNB_MASK (0x7FUL << ISAC_FLASH_CR_PNB_POS) /* RM0453 Rev 6 §4.10.6 p. 136: Bits 9:3 (0..127) */
#define ISAC_FLASH_CR_STRT     (1UL << 16)
#define ISAC_FLASH_CR_LOCK     (1UL << 31)
#define ISAC_FLASH_OPTR_RDP_MASK 0xFFUL
#define ISAC_FLASH_OPTR_IWDG_SW   (1UL << 16)
#define ISAC_FLASH_OPTR_IWDG_STOP (1UL << 17)
#define ISAC_FLASH_MAIN_BASE   0x08000000UL

#define ISAC_IWDG_BASE_ADDR    0x40003000UL
#define ISAC_IWDG_REG(off)     (*((volatile uint32_t *)(ISAC_IWDG_BASE_ADDR + (off))))
#define ISAC_IWDG_KR           ISAC_IWDG_REG(0x00UL)
#define ISAC_IWDG_PR           ISAC_IWDG_REG(0x04UL)
#define ISAC_IWDG_RLR          ISAC_IWDG_REG(0x08UL)
#define ISAC_IWDG_SR           ISAC_IWDG_REG(0x0CUL)

static bool flash_wait_idle(void)
{
    uint32_t guard = 2000000UL;
    while (((ISAC_FLASH_SR & (ISAC_FLASH_SR_BSY | ISAC_FLASH_SR_CFGBSY)) != 0UL) && (guard > 0UL)) {
        --guard;
    }
    return guard > 0UL;
}

static bool flash_unlock(void)
{
    if ((ISAC_FLASH_CR & ISAC_FLASH_CR_LOCK) != 0UL) {
        ISAC_FLASH_KEYR = 0x45670123UL;
        ISAC_FLASH_KEYR = 0xCDEF89ABUL;
    }
    return (ISAC_FLASH_CR & ISAC_FLASH_CR_LOCK) == 0UL;
}

static void flash_lock(void)
{
    ISAC_FLASH_CR |= ISAC_FLASH_CR_LOCK;
}

static void flash_flush_dcache(void)
{
    /* RM0453 Rev 6 §4.10.1 p. 130: DCRST can be written only when DCEN == 0 */
    if ((ISAC_FLASH_ACR & ISAC_FLASH_ACR_DCEN) != 0UL) {
        ISAC_FLASH_ACR &= ~ISAC_FLASH_ACR_DCEN;
        ISAC_FLASH_ACR |= ISAC_FLASH_ACR_DCRST;
        ISAC_FLASH_ACR &= ~ISAC_FLASH_ACR_DCRST;
        ISAC_FLASH_ACR |= ISAC_FLASH_ACR_DCEN;
    }
    __asm volatile ("dsb 0xF" ::: "memory");
}

bool ISAC_HAL_Flash_ErasePage(uint32_t page_addr)
{
    bool     ok;
    uint32_t page;
    uint32_t primask;

    if ((page_addr < ISAC_FLASH_MAIN_BASE) || ((page_addr % ISAC_FLASH_PAGE_SIZE) != 0UL)) {
        return false;
    }
    page = (page_addr - ISAC_FLASH_MAIN_BASE) / ISAC_FLASH_PAGE_SIZE;
    if (page >= 128UL) {
        return false;
    }
    /* MED-04 fix: Never stall single-bank Flash bus while Sub-GHz radio is active (RFBUSYS != 0) */
    if ((ISAC_PWR->SR2 & ISAC_PWR_SR2_RFBUSYS) != 0UL) {
        return false;
    }
    if (!flash_unlock() || !flash_wait_idle()) {
        return false;
    }
    ISAC_HAL_Watchdog_Kick();
    ISAC_FLASH_SR = ISAC_FLASH_SR_ERRORS;
    ISAC_FLASH_CR = (ISAC_FLASH_CR & ~ISAC_FLASH_CR_PNB_MASK) | ISAC_FLASH_CR_PER | (page << ISAC_FLASH_CR_PNB_POS);
    __asm volatile ("mrs %0, primask\n\tcpsid i" : "=r" (primask) :: "memory");
    ISAC_FLASH_CR |= ISAC_FLASH_CR_STRT;
    ok = flash_wait_idle() && ((ISAC_FLASH_SR & ISAC_FLASH_SR_ERRORS) == 0UL);
    ISAC_FLASH_CR &= ~(ISAC_FLASH_CR_PER | ISAC_FLASH_CR_PNB_MASK);
    if ((primask & 1UL) == 0UL) {
        __asm volatile ("cpsie i" ::: "memory");
    }
    /* MED-05 fix: Single-bank Flash erase (~22 ms typ per DS13105 Table 57) stalls Flash instruction fetch,
     * causing at most 1 pending SysTick IRQ to fire; compensate monotonic ms tick counter for missed ticks. */
    if (ok && ((ISAC_SYSTICK->CSR & ISAC_SYSTICK_CSR_ENABLE) != 0UL)) {
        g_systick_ms = g_systick_ms + 21UL;
    }
    flash_flush_dcache();
    flash_lock();
    ISAC_HAL_Watchdog_Kick();
    return ok;
}

bool ISAC_HAL_Flash_ProgramDoubleWord(uint32_t addr, uint32_t lo, uint32_t hi)
{
    bool     ok;
    uint32_t primask;

    if ((addr < ISAC_FLASH_MAIN_BASE) || ((addr & 7UL) != 0UL) ||
        (addr >= (ISAC_FLASH_MAIN_BASE + (128UL * ISAC_FLASH_PAGE_SIZE)))) {
        return false;
    }
    if ((ISAC_PWR->SR2 & ISAC_PWR_SR2_RFBUSYS) != 0UL) {
        return false;
    }
    if (!flash_unlock() || !flash_wait_idle()) {
        return false;
    }
    ISAC_FLASH_SR = ISAC_FLASH_SR_ERRORS;
    __asm volatile ("mrs %0, primask\n\tcpsid i" : "=r" (primask) :: "memory");
    ISAC_FLASH_CR |= ISAC_FLASH_CR_PG;
    *((volatile uint32_t *)addr)         = lo;
    *((volatile uint32_t *)(addr + 4UL)) = hi;
    ok = flash_wait_idle() && ((ISAC_FLASH_SR & ISAC_FLASH_SR_ERRORS) == 0UL);
    ISAC_FLASH_CR &= ~ISAC_FLASH_CR_PG;
    if ((primask & 1UL) == 0UL) {
        __asm volatile ("cpsie i" ::: "memory");
    }
    flash_flush_dcache();
    flash_lock();
    return ok;
}

static volatile bool g_flash_read_guard     = false;
static volatile bool g_flash_ecc_step_fault = false;
static volatile bool g_flash_ecc_latched    = false;

void __attribute__((used)) ISAC_HAL_NMI_Dispatch(uint32_t *sp)
{
    const uint32_t eccr = ISAC_FLASH_ECCR;

    /* BLK-FW-02: Catch STM32WLE5JC 72-bit Flash double-bit ECC NMI on brownout-torn NVM cells
     * inside ISAC_HAL_Flash_Read() so sealed field nodes never enter an NMI -> SYSRESETREQ brick loop. */
    if (((eccr & ISAC_FLASH_ECCR_ECCD) != 0UL) && g_flash_read_guard && (sp != NULL)) {
        const uint32_t pc = sp[6];
        const uint16_t hw = *((const uint16_t *)(pc & ~1UL));

        ISAC_FLASH_ECCR        = (eccr & (ISAC_FLASH_ECCR_ECCD | ISAC_FLASH_ECCR_ECCC));
        g_flash_ecc_step_fault = true;
        g_flash_ecc_latched    = true;
        sp[6]                  = pc + (((hw & 0xF800U) >= 0xE800U) ? 4UL : 2UL);
        __asm volatile ("dsb 0xF\n\tisb 0xF" ::: "memory");
        return;
    }

    /* Unrecoverable NMI outside guarded NVM scan: de-assert PA8, PA9, PA0, PA1 and reset */
    ISAC_GPIOA->BSRR = (1UL << (ISAC_GPIOA_PIN_DET_EN     + 16U))
                     | (1UL << (ISAC_GPIOA_PIN_BAT_MON_EN + 16U))
                     | (1UL << (ISAC_GPIOA_PIN_RFSW_VC1   + 16U))
                     | (1UL << (ISAC_GPIOA_PIN_RFSW_VC2   + 16U));
    if ((ISAC_DCB_DHCSR & ISAC_DCB_DHCSR_C_DEBUGEN) != 0UL) {
        __asm volatile ("bkpt #0");
    }
    __asm volatile ("dsb 0xF" ::: "memory");
    ISAC_SCB->AIRCR = ISAC_SCB_AIRCR_SYSRESETREQ;
    __asm volatile ("dsb 0xF" ::: "memory");
    for (;;) {
        __asm volatile ("nop");
    }
}

void __attribute__((naked)) NMI_Handler(void)
{
    __asm volatile (
        "tst lr, #4\n\t"
        "ite eq\n\t"
        "mrseq r0, msp\n\t"
        "mrsne r0, psp\n\t"
        "b ISAC_HAL_NMI_Dispatch\n\t"
    );
}

bool ISAC_HAL_Flash_ConsumeEccFault(void)
{
    const bool latched = g_flash_ecc_latched;
    g_flash_ecc_latched = false;
    return latched;
}

void ISAC_HAL_Flash_Read(uint32_t addr, void *dst, uint32_t len)
{
    uint8_t *d = (uint8_t *)dst;
    uint32_t i;

    for (i = 0U; i < len; ++i) {
        const uint32_t byte_addr = addr + i;
        uint32_t       val       = 0UL;

        g_flash_ecc_step_fault = false;
        g_flash_read_guard     = true;
        __asm volatile (
            "dsb 0xF\n\t"
            "ldrb %[out], [%[ptr]]\n\t"
            "dsb 0xF\n\t"
            : [out] "+r" (val)
            : [ptr] "r" (byte_addr)
            : "memory"
        );
        g_flash_read_guard = false;
        if (g_flash_ecc_step_fault) {
            flash_flush_dcache();
            d[i] = 0x00U;
        } else {
            d[i] = (uint8_t)val;
        }
    }
}

uint32_t ISAC_HAL_ResetCause_ReadAndClear(void)
{
    /* RM0453 Rev 6 §7.4.31 p. 341: Bits 31:24 = LPWR,WWDG,IWDG,SFT,BOR,PIN,OBL,RFILA */
    const uint32_t flags = ISAC_RCC->CSR & 0xFF000000UL;
    ISAC_RCC->CSR |= (1UL << 23); /* RMVF */
    return flags;
}

uint32_t ISAC_HAL_ReadOptionRegister(void)
{
    return ISAC_FLASH_OPTR;
}

bool ISAC_HAL_ReadoutProtectionActive(void)
{
    return (ISAC_FLASH_OPTR & ISAC_FLASH_OPTR_RDP_MASK) != 0xAAUL;
}

bool ISAC_HAL_Watchdog_Start(void)
{
    const uint32_t optr = ISAC_FLASH_OPTR;
    uint32_t guard = 2000000UL;

    /* IWDG cannot be stopped once started. With a 900 s STOP2 period it is only safe if the
     * option bytes freeze it in STOP (IWDG_STOP = 0) and allow software start (IWDG_SW = 1). */
    if (((optr & ISAC_FLASH_OPTR_IWDG_STOP) != 0UL) || ((optr & ISAC_FLASH_OPTR_IWDG_SW) == 0UL)) {
        return false;
    }
    ISAC_IWDG_KR  = 0xCCCCUL;          /* start (LSI ~32 kHz) */
    ISAC_IWDG_KR  = 0x5555UL;          /* unlock PR/RLR */
    ISAC_IWDG_PR  = 6UL;               /* /256 */
    ISAC_IWDG_RLR = 0x0FFFUL;          /* ~32.8 s awake-time budget */
    while (((ISAC_IWDG_SR & 0x3UL) != 0UL) && (guard > 0UL)) {
        --guard;
    }
    ISAC_IWDG_KR  = 0xAAAAUL;
    return true;
}

void ISAC_HAL_Watchdog_Kick(void)
{
    ISAC_IWDG_KR = 0xAAAAUL;  /* harmless if the IWDG was never started */
}
