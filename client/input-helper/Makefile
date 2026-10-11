# Input helpers run inside the game's wine prefix (64-bit PE, no x87sidecar).
# Needs mingw-w64 (brew install mingw-w64).
CC = x86_64-w64-mingw32-gcc
CFLAGS = -O2 -Wall

all: sendinput.exe

%.exe: %.c
	$(CC) $(CFLAGS) -o $@ $< -luser32
