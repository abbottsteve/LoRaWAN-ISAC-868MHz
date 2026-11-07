# ==============================================================================
# ISAC_868 Rev E.5 — Self-Contained Host HIL & Bare-Metal RAK3172LP-SiP Build
#   Pinned toolchain recorded in firmware/TOOLCHAIN.lock (arm-none-eabi-gcc 12.2.1)
# ==============================================================================
HOST_CC      ?= gcc
CROSS_CC     ?= arm-none-eabi-gcc
CROSS_SIZE   ?= arm-none-eabi-size
CROSS_OBJCOPY?= arm-none-eabi-objcopy
EXPECTED_ARM_GCC_VER ?= 12.2.1

BUILD_DIR    ?= build
INC_DIR      := include
DESIGN_JSON  ?= test/data/design_values.json

HOST_CFLAGS  := -std=c11 -O2 -Wall -Wextra -Werror -I$(INC_DIR)
HOST_LDFLAGS := -lm

TARGET_MCU   := -mcpu=cortex-m4 -mthumb
TARGET_CFLAGS:= -std=c11 $(TARGET_MCU) -Os -Wall -Wextra -Werror -Wstack-usage=2048 \
                -ffreestanding -nostdlib -fdata-sections -ffunction-sections \
                -I$(INC_DIR)
TARGET_LDFLAGS := $(TARGET_MCU) -nostdlib -T linker/stm32wle5jc.ld \
                  -Wl,--gc-sections -Wl,-Map="$(BUILD_DIR)/isac_rak3172lp_sip.map"

HOST_BIN     := $(BUILD_DIR)/isac_fw_selftest
NVM_BIN      := $(BUILD_DIR)/isac_nvm_selftest
TARGET_ELF   := $(BUILD_DIR)/isac_rak3172lp_sip.elf
TARGET_HEX   := $(BUILD_DIR)/isac_rak3172lp_sip.hex
TARGET_BIN   := $(BUILD_DIR)/isac_rak3172lp_sip.bin

FW_HEADERS   := $(INC_DIR)/isac_board_pins.h \
                $(INC_DIR)/isac_hal.h \
                $(INC_DIR)/isac_sensing.h \
                $(INC_DIR)/isac_lorawan_eu868.h \
                $(INC_DIR)/isac_nvm.h

HOST_SRCS    := src/isac_sensing.c \
                src/isac_lorawan_eu868.c \
                "$(CURDIR)/test/test_isac_hil.c"

TARGET_SRCS  := src/startup_stm32wle5jc.c \
                src/isac_hal_stm32wl.c \
                src/isac_nvm.c \
                src/isac_sensing.c \
                src/isac_lorawan_eu868.c \
                src/main_target.c

.PHONY: all host_test selftest target_elf clean

all: host_test target_elf

selftest: host_test

$(BUILD_DIR):
	@mkdir -p "$(BUILD_DIR)"

$(HOST_BIN): src/isac_sensing.c src/isac_lorawan_eu868.c test/test_isac_hil.c $(FW_HEADERS) | $(BUILD_DIR)
	$(HOST_CC) $(HOST_CFLAGS) $(HOST_SRCS) -o "$(HOST_BIN)" $(HOST_LDFLAGS)

$(NVM_BIN): test/test_isac_nvm.c src/isac_nvm.c src/isac_lorawan_eu868.c $(FW_HEADERS) | $(BUILD_DIR)
	$(HOST_CC) $(HOST_CFLAGS) "$(CURDIR)/test/test_isac_nvm.c" src/isac_nvm.c src/isac_lorawan_eu868.c -o "$(NVM_BIN)" $(HOST_LDFLAGS)

host_test: $(HOST_BIN) $(NVM_BIN)
	"$(if $(filter /%,$(HOST_BIN)),$(HOST_BIN),./$(HOST_BIN))" "$(DESIGN_JSON)"
	"$(if $(filter /%,$(NVM_BIN)),$(NVM_BIN),./$(NVM_BIN))"

$(TARGET_ELF): $(TARGET_SRCS) $(FW_HEADERS) linker/stm32wle5jc.ld | $(BUILD_DIR)
	@$(CROSS_CC) --version | head -n 1 | grep -q "$(EXPECTED_ARM_GCC_VER)" || \
		echo "[WARN] $(CROSS_CC) version differs from pinned $(EXPECTED_ARM_GCC_VER) in TOOLCHAIN.lock"
	$(CROSS_CC) $(TARGET_CFLAGS) $(TARGET_SRCS) $(TARGET_LDFLAGS) -o "$(TARGET_ELF)"
	$(CROSS_OBJCOPY) -O ihex "$(TARGET_ELF)" "$(TARGET_HEX)"
	$(CROSS_OBJCOPY) -O binary "$(TARGET_ELF)" "$(TARGET_BIN)"
	$(CROSS_SIZE) "$(TARGET_ELF)"

target_elf: $(TARGET_ELF)

clean:
	rm -rf "$(BUILD_DIR)"
