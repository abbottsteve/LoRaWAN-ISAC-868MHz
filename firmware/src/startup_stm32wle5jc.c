/**
 * @file startup_stm32wle5jc.c
 * @brief Freestanding Cortex-M4 Vector Table & C11 Startup for STM32WLE5JC (RAK3172LP-SiP)
 */
#include "isac_board_pins.h"

#include <stddef.h>
#include <stdint.h>

extern uint32_t _estack;
extern uint32_t _sidata;
extern uint32_t _sdata;
extern uint32_t _edata;
extern uint32_t _sbss;
extern uint32_t _ebss;

extern int main(void);

void Reset_Handler(void);
void Default_Handler(void);

void NMI_Handler(void)          __attribute__((weak, alias("Default_Handler")));
void HardFault_Handler(void)    __attribute__((weak, alias("Default_Handler")));
void MemManage_Handler(void)    __attribute__((weak, alias("Default_Handler")));
void BusFault_Handler(void)     __attribute__((weak, alias("Default_Handler")));
void UsageFault_Handler(void)   __attribute__((weak, alias("Default_Handler")));
void SVC_Handler(void)          __attribute__((weak, alias("Default_Handler")));
void DebugMon_Handler(void)     __attribute__((weak, alias("Default_Handler")));
void PendSV_Handler(void)       __attribute__((weak, alias("Default_Handler")));
void SysTick_Handler(void)      __attribute__((weak, alias("Default_Handler")));

/* STM32WLE5JC Peripheral Interrupts Required for Autonomous STOP2 & Sub-GHz Operation */
void RTC_WKUP_IRQHandler(void)     __attribute__((weak, alias("Default_Handler")));
void SUBGHZ_Radio_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));

typedef union {
    void     (*handler)(void);
    uint32_t *stack_top;
} isr_vector_entry_t;

#define ISR_DEFAULT  { .handler = Default_Handler }

/* 16 Cortex-M4 Core Exceptions + 62 STM32WLE5JC Peripheral IRQs (RM0453 Table 52) */
__attribute__((section(".isr_vector"), used))
const isr_vector_entry_t g_pfnVectors[16 + 62] = {
    { .stack_top = &_estack },              /*  0: Initial Stack Pointer          */
    { .handler   = Reset_Handler },         /*  1: Reset                          */
    { .handler   = NMI_Handler },           /*  2: NMI                            */
    { .handler   = HardFault_Handler },     /*  3: Hard Fault                     */
    { .handler   = MemManage_Handler },     /*  4: MPU Fault                      */
    { .handler   = BusFault_Handler },      /*  5: Bus Fault                      */
    { .handler   = UsageFault_Handler },    /*  6: Usage Fault                    */
    ISR_DEFAULT,                            /*  7: Reserved                       */
    ISR_DEFAULT,                            /*  8: Reserved                       */
    ISR_DEFAULT,                            /*  9: Reserved                       */
    ISR_DEFAULT,                            /* 10: Reserved                       */
    { .handler   = SVC_Handler },           /* 11: SVCall                         */
    { .handler   = DebugMon_Handler },      /* 12: Debug Monitor                  */
    ISR_DEFAULT,                            /* 13: Reserved                       */
    { .handler   = PendSV_Handler },        /* 14: PendSV                         */
    { .handler   = SysTick_Handler },       /* 15: SysTick                        */
    /* External Peripheral IRQs 0..61 (RM0453 Table 52) */
    ISR_DEFAULT,                            /* 16: IRQ  0 WWDG                    */
    ISR_DEFAULT,                            /* 17: IRQ  1 PVD_PVM                 */
    ISR_DEFAULT,                            /* 18: IRQ  2 TAMP_STAMP_LSECSS_SSRU  */
    { .handler   = RTC_WKUP_IRQHandler },   /* 19: IRQ  3 RTC_WKUP (EXTI Line 20) */
    ISR_DEFAULT,                            /* 20: IRQ  4 FLASH                   */
    ISR_DEFAULT,                            /* 21: IRQ  5 RCC                     */
    ISR_DEFAULT,                            /* 22: IRQ  6 EXTI0                   */
    ISR_DEFAULT,                            /* 23: IRQ  7 EXTI1                   */
    ISR_DEFAULT,                            /* 24: IRQ  8 EXTI2                   */
    ISR_DEFAULT,                            /* 25: IRQ  9 EXTI3                   */
    ISR_DEFAULT,                            /* 26: IRQ 10 EXTI4                   */
    ISR_DEFAULT,                            /* 27: IRQ 11 DMA1_Channel1           */
    ISR_DEFAULT,                            /* 28: IRQ 12 DMA1_Channel2           */
    ISR_DEFAULT,                            /* 29: IRQ 13 DMA1_Channel3           */
    ISR_DEFAULT,                            /* 30: IRQ 14 DMA1_Channel4           */
    ISR_DEFAULT,                            /* 31: IRQ 15 DMA1_Channel5           */
    ISR_DEFAULT,                            /* 32: IRQ 16 DMA1_Channel6           */
    ISR_DEFAULT,                            /* 33: IRQ 17 DMA1_Channel7           */
    ISR_DEFAULT,                            /* 34: IRQ 18 ADC                     */
    ISR_DEFAULT,                            /* 35: IRQ 19 DAC                     */
    ISR_DEFAULT,                            /* 36: IRQ 20 Reserved                */
    ISR_DEFAULT,                            /* 37: IRQ 21 COMP                    */
    ISR_DEFAULT,                            /* 38: IRQ 22 EXTI9_5                 */
    ISR_DEFAULT,                            /* 39: IRQ 23 TIM1_BRK                */
    ISR_DEFAULT,                            /* 40: IRQ 24 TIM1_UP                 */
    ISR_DEFAULT,                            /* 41: IRQ 25 TIM1_TRG_COM            */
    ISR_DEFAULT,                            /* 42: IRQ 26 TIM1_CC                 */
    ISR_DEFAULT,                            /* 43: IRQ 27 TIM2                    */
    ISR_DEFAULT,                            /* 44: IRQ 28 TIM16                   */
    ISR_DEFAULT,                            /* 45: IRQ 29 TIM17                   */
    ISR_DEFAULT,                            /* 46: IRQ 30 I2C1_EV                 */
    ISR_DEFAULT,                            /* 47: IRQ 31 I2C1_ER                 */
    ISR_DEFAULT,                            /* 48: IRQ 32 I2C2_EV                 */
    ISR_DEFAULT,                            /* 49: IRQ 33 I2C2_ER                 */
    ISR_DEFAULT,                            /* 50: IRQ 34 SPI1                    */
    ISR_DEFAULT,                            /* 51: IRQ 35 SPI2                    */
    ISR_DEFAULT,                            /* 52: IRQ 36 USART1                  */
    ISR_DEFAULT,                            /* 53: IRQ 37 USART2                  */
    ISR_DEFAULT,                            /* 54: IRQ 38 LPUART1                 */
    ISR_DEFAULT,                            /* 55: IRQ 39 LPTIM1                  */
    ISR_DEFAULT,                            /* 56: IRQ 40 LPTIM2                  */
    ISR_DEFAULT,                            /* 57: IRQ 41 EXTI15_10               */
    ISR_DEFAULT,                            /* 58: IRQ 42 RTC_Alarm               */
    ISR_DEFAULT,                            /* 59: IRQ 43 LPTIM3                  */
    ISR_DEFAULT,                            /* 60: IRQ 44 SUBGHZSPI               */
    ISR_DEFAULT,                            /* 61: IRQ 45 Reserved                */
    ISR_DEFAULT,                            /* 62: IRQ 46 Reserved                */
    ISR_DEFAULT,                            /* 63: IRQ 47 HSEM                    */
    ISR_DEFAULT,                            /* 64: IRQ 48 I2C3_EV                 */
    ISR_DEFAULT,                            /* 65: IRQ 49 I2C3_ER                 */
    { .handler   = SUBGHZ_Radio_IRQHandler },/* 66: IRQ 50 SUBGHZ_Radio           */
    ISR_DEFAULT,                            /* 67: IRQ 51 AES                     */
    ISR_DEFAULT,                            /* 68: IRQ 52 RNG                     */
    ISR_DEFAULT,                            /* 69: IRQ 53 PKA                     */
    ISR_DEFAULT,                            /* 70: IRQ 54 DMA2_Channel1           */
    ISR_DEFAULT,                            /* 71: IRQ 55 DMA2_Channel2           */
    ISR_DEFAULT,                            /* 72: IRQ 56 DMA2_Channel3           */
    ISR_DEFAULT,                            /* 73: IRQ 57 DMA2_Channel4           */
    ISR_DEFAULT,                            /* 74: IRQ 58 DMA2_Channel5           */
    ISR_DEFAULT,                            /* 75: IRQ 59 DMA2_Channel6           */
    ISR_DEFAULT,                            /* 76: IRQ 60 DMA2_Channel7           */
    ISR_DEFAULT                             /* 77: IRQ 61 DMAMUX1_OVR             */
};

/* Freestanding C11 memory primitives required by GCC under -nostdlib */
void *memcpy(void *dst, const void *src, size_t n)
{
    uint8_t       *d = (uint8_t *)dst;
    const uint8_t *s = (const uint8_t *)src;
    while (n-- > 0U) {
        *d++ = *s++;
    }
    return dst;
}

void *memset(void *dst, int val, size_t n)
{
    uint8_t *d = (uint8_t *)dst;
    while (n-- > 0U) {
        *d++ = (uint8_t)val;
    }
    return dst;
}

void Reset_Handler(void)
{
    const uint32_t *src = &_sidata;
    uint32_t       *dst = &_sdata;

    /* STM32WLE5 resets PA15 (JTDI / DET_ADC) and PB4 (NJTRST / BAT_SENSE) into AF0
     * with internal ~45 kOhm pull-ups to VDD (~74 uA/pin while NRST=0 or BOOT0=1). Immediately
     * switch both pins to high-Z analog mode (MODER=0b11, PUPDR=0b00) before .data/.bss init. */
    ISAC_RCC->AHB2ENR |= (ISAC_RCC_AHB2ENR_GPIOAEN | ISAC_RCC_AHB2ENR_GPIOBEN);
    (void)ISAC_RCC->AHB2ENR;
    ISAC_GPIOA->MODER |=  (3UL << (ISAC_GPIOA_PIN_DET_ADC * 2U));
    ISAC_GPIOA->PUPDR &= ~(3UL << (ISAC_GPIOA_PIN_DET_ADC * 2U));
    ISAC_GPIOB->MODER |=  (3UL << (ISAC_GPIOB_PIN_BAT_SENSE * 2U));
    ISAC_GPIOB->PUPDR &= ~(3UL << (ISAC_GPIOB_PIN_BAT_SENSE * 2U));

    while (dst < &_edata) {
        *dst++ = *src++;
    }

    dst = &_sbss;
    while (dst < &_ebss) {
        *dst++ = 0UL;
    }

    (void)main();
    for (;;) {
        __asm volatile ("wfi");
    }
}

void Default_Handler(void)
{
    /* Ensure PA8 (DET_EN), PA9 (BAT_MON_EN), and PA0/PA1 (RF switch) are de-asserted on fault */
    ISAC_GPIOA->BSRR = (1UL << (ISAC_GPIOA_PIN_DET_EN     + 16U))
                     | (1UL << (ISAC_GPIOA_PIN_BAT_MON_EN + 16U))
                     | (1UL << (ISAC_GPIOA_PIN_RFSW_VC1   + 16U))
                     | (1UL << (ISAC_GPIOA_PIN_RFSW_VC2   + 16U));

    if ((ISAC_DCB_DHCSR & ISAC_DCB_DHCSR_C_DEBUGEN) != 0UL) {
        __asm volatile ("bkpt #0");
    }

    /* Autonomous field recovery: request Cortex-M4 system reset via SCB->AIRCR */
    __asm volatile ("dsb 0xF" ::: "memory");
    ISAC_SCB->AIRCR = ISAC_SCB_AIRCR_SYSRESETREQ;
    __asm volatile ("dsb 0xF" ::: "memory");
    for (;;) {
        __asm volatile ("nop");
    }
}
