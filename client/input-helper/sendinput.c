// sendinput.exe — inject key/mouse events from inside wine (no macOS Accessibility).
// Usage:
//   sendinput sc <scancode-hex> <down|up> [ms-hold]   scancode-based (DirectInput-visible);
//                                                     E0xx = E0-extended key (arrows: E04B/E04D)
//   sendinput rclick <x> <y> [ms]                     absolute move + right click (px, or fractions like 0.5)
//   sendinput chat <text>                             Enter, <text> as US-layout scancodes,
//                                                     Enter: one chat line / slash command
//                                                     (DAoC's chat reads scancodes, not VK_PACKET)
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

// Scan code 0x00XX, or 0xE0XX for an E0-prefixed key (arrows, Ins/Del/Home/End/
// PgUp/PgDn, right Ctrl/Alt): those need KEYEVENTF_EXTENDEDKEY, or DirectInput
// sees the numpad key with the same scan code.
static void key_scancode(WORD sc, int up) {
    INPUT in = {0};
    in.type = INPUT_KEYBOARD; in.ki.wScan = sc & 0xFF;
    in.ki.dwFlags = KEYEVENTF_SCANCODE | (up ? KEYEVENTF_KEYUP : 0)
                  | ((sc >> 8) == 0xE0 ? KEYEVENTF_EXTENDEDKEY : 0);
    SendInput(1, &in, sizeof(INPUT));
}

static void tap_scancode(WORD sc, int hold) {
    key_scancode(sc, 0);
    if (hold > 0) Sleep(hold);
    key_scancode(sc, 1);
}

// US layout: scancode for a character, or 0 if unsupported; *shift set for
// characters that need it.
static WORD us_scancode(char c, int *shift) {
    static const char row1[] = "qwertyuiop", row2[] = "asdfghjkl", row3[] = "zxcvbnm";
    static const WORD digits[] = {0x0B, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A};
    const char *p;
    *shift = 0;
    if (c >= 'A' && c <= 'Z') { *shift = 1; c = (char)(c - 'A' + 'a'); }
    if ((p = strchr(row1, c)) && c) return (WORD)(0x10 + (p - row1));
    if ((p = strchr(row2, c)) && c) return (WORD)(0x1E + (p - row2));
    if ((p = strchr(row3, c)) && c) return (WORD)(0x2C + (p - row3));
    if (c >= '0' && c <= '9') return digits[c - '0'];
    switch (c) {
    case ' ': return 0x39;
    case '/': return 0x35;
    case '-': return 0x0C;
    case '.': return 0x34;
    case ',': return 0x33;
    case '\'': return 0x28;
    case '[': return 0x1A;
    case ']': return 0x1B;
    case '?': *shift = 1; return 0x35;
    case '!': *shift = 1; return 0x02;
    }
    return 0;
}

static int type_chat(const char *text) {
    const WORD ENTER = 0x1C, LSHIFT = 0x2A;
    int shift;
    // Reject the whole line before opening chat: bailing out mid-line would
    // leave the chat box open and swallow every later keystroke.
    for (const char *p = text; *p; ++p)
        if (!us_scancode(*p, &shift)) { fprintf(stderr, "sendinput: unsupported character '%c'\n", *p); return 2; }
    tap_scancode(ENTER, 40); Sleep(150);   // open the chat line
    for (const char *p = text; *p; ++p) {
        WORD sc = us_scancode(*p, &shift);
        if (shift) { key_scancode(LSHIFT, 0); Sleep(15); }
        tap_scancode(sc, 20);
        if (shift) { Sleep(15); key_scancode(LSHIFT, 1); }
        Sleep(20);
    }
    Sleep(100);
    tap_scancode(ENTER, 40);                // submit
    return 0;
}

int main(int argc, char **argv) {
    if (argc < 2) { fprintf(stderr, "usage: sendinput sc|rclick|chat ...\n"); return 2; }
    if (!strcmp(argv[1], "sc") && argc >= 4) {
        WORD sc = (WORD)strtol(argv[2], NULL, 16);
        int down = !strcmp(argv[3], "down");
        int hold = argc >= 5 ? atoi(argv[4]) : 0;
        if (down && hold > 0) tap_scancode(sc, hold);
        else key_scancode(sc, !down);
        return 0;
    }
    if (!strcmp(argv[1], "rclick") && argc >= 4) {
        // Coordinates in pixels, or as screen fractions when written with a
        // decimal point (e.g. 0.51 0.55): the display size then does not matter.
        double fx = atof(argv[2]), fy = atof(argv[3]);
        int cx = GetSystemMetrics(SM_CXSCREEN), cy = GetSystemMetrics(SM_CYSCREEN);
        int x = strchr(argv[2], '.') ? (int)(fx * cx) : atoi(argv[2]);
        int y = strchr(argv[3], '.') ? (int)(fy * cy) : atoi(argv[3]);
        int hold = argc >= 5 ? atoi(argv[4]) : 50;
        INPUT in[3] = {0};
        in[0].type = INPUT_MOUSE;
        in[0].mi.dwFlags = MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_MOVE;
        in[0].mi.dx = (DWORD)(x * 65535.0 / cx);
        in[0].mi.dy = (DWORD)(y * 65535.0 / cy);
        in[1] = in[0]; in[1].mi.dwFlags = MOUSEEVENTF_RIGHTDOWN;
        in[2] = in[0]; in[2].mi.dwFlags = MOUSEEVENTF_RIGHTUP;
        SendInput(1, &in[0], sizeof(INPUT)); Sleep(hold);
        SendInput(1, &in[1], sizeof(INPUT)); Sleep(40);
        SendInput(1, &in[2], sizeof(INPUT));
        return 0;
    }
    if (!strcmp(argv[1], "chat") && argc == 3) return type_chat(argv[2]);
    return 2;
}
