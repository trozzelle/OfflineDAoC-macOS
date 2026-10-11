// sendinput.exe — inject key/mouse events from inside wine (no macOS Accessibility).
// Usage:
//   sendinput sc <scancode-hex> <down|up> [ms-hold]   scancode-based (DirectInput-visible)
//   sendinput vk <vkey-hex> <down|up> [ms-hold]       vkey-based
//   sendinput click|rclick <x> <y> [ms]               absolute move + left/right click (px, or fractions like 0.5)
//   sendinput type <text>                             unicode text via VK_PACKET
//   sendinput chat <text>                             Enter, <text> as US-layout scancodes,
//                                                     Enter: one chat line / slash command
//                                                     (DAoC's chat reads scancodes, not VK_PACKET)
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void tap_scancode(WORD sc, int hold) {
    INPUT in[2] = {0};
    in[0].type = INPUT_KEYBOARD; in[0].ki.wScan = sc; in[0].ki.dwFlags = KEYEVENTF_SCANCODE;
    in[1] = in[0]; in[1].ki.dwFlags = KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP;
    SendInput(1, &in[0], sizeof(INPUT));
    if (hold > 0) Sleep(hold);
    SendInput(1, &in[1], sizeof(INPUT));
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

static void key_scancode(WORD sc, int up) {
    INPUT in = {0};
    in.type = INPUT_KEYBOARD; in.ki.wScan = sc;
    in.ki.dwFlags = KEYEVENTF_SCANCODE | (up ? KEYEVENTF_KEYUP : 0);
    SendInput(1, &in, sizeof(INPUT));
}

static int type_chat(const char *text) {
    const WORD ENTER = 0x1C, LSHIFT = 0x2A;
    tap_scancode(ENTER, 40); Sleep(150);   // open the chat line
    for (const char *p = text; *p; ++p) {
        int shift;
        WORD sc = us_scancode(*p, &shift);
        if (!sc) { fprintf(stderr, "sendinput: unsupported character '%c'\n", *p); return 2; }
        if (shift) { key_scancode(LSHIFT, 0); Sleep(15); }
        tap_scancode(sc, 20);
        if (shift) { Sleep(15); key_scancode(LSHIFT, 1); }
        Sleep(20);
    }
    Sleep(100);
    tap_scancode(ENTER, 40);                // submit
    return 0;
}
static void tap_vk(WORD vk, int hold) {
    INPUT in[2] = {0};
    in[0].type = INPUT_KEYBOARD; in[0].ki.wVk = vk;
    in[1] = in[0]; in[1].ki.dwFlags = KEYEVENTF_KEYUP;
    SendInput(1, &in[0], sizeof(INPUT));
    if (hold > 0) Sleep(hold);
    SendInput(1, &in[1], sizeof(INPUT));
}

int main(int argc, char **argv) {
    if (argc < 2) { fprintf(stderr, "usage: sendinput sc|vk|click|type ...\n"); return 2; }
    if (!strcmp(argv[1], "sc") && argc >= 4) {
        WORD sc = (WORD)strtol(argv[2], NULL, 16);
        int down = !strcmp(argv[3], "down");
        int hold = argc >= 5 ? atoi(argv[4]) : 0;
        if (down && hold > 0) { tap_scancode(sc, hold); }
        else {
            INPUT in = {0}; in.type = INPUT_KEYBOARD;
            in.ki.wScan = sc; in.ki.dwFlags = KEYEVENTF_SCANCODE;
            if (!down) in.ki.dwFlags |= KEYEVENTF_KEYUP;
            SendInput(1, &in, sizeof(INPUT));
        }
        return 0;
    }
    if (!strcmp(argv[1], "vk") && argc >= 4) {
        WORD vk = (WORD)strtol(argv[2], NULL, 16);
        int down = !strcmp(argv[3], "down");
        int hold = argc >= 5 ? atoi(argv[4]) : 0;
        if (down && hold > 0) { tap_vk(vk, hold); }
        else {
            INPUT in = {0}; in.type = INPUT_KEYBOARD;
            in.ki.wVk = vk;
            if (!down) in.ki.dwFlags |= KEYEVENTF_KEYUP;
            SendInput(1, &in, sizeof(INPUT));
        }
        return 0;
    }
    if ((!strcmp(argv[1], "click") || !strcmp(argv[1], "rclick")) && argc >= 4) {
        int right = argv[1][0] == 'r';
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
        in[1] = in[0]; in[1].mi.dwFlags = right ? MOUSEEVENTF_RIGHTDOWN : MOUSEEVENTF_LEFTDOWN;
        in[2] = in[0]; in[2].mi.dwFlags = right ? MOUSEEVENTF_RIGHTUP : MOUSEEVENTF_LEFTUP;
        SendInput(1, &in[0], sizeof(INPUT)); Sleep(hold);
        SendInput(1, &in[1], sizeof(INPUT)); Sleep(40);
        SendInput(1, &in[2], sizeof(INPUT));
        return 0;
    }
    if (!strcmp(argv[1], "chat") && argc == 3) return type_chat(argv[2]);
    if (!strcmp(argv[1], "type") && argc == 3) {
        for (char *p = argv[2]; *p; ++p) {
            INPUT in = {0}; in.type = INPUT_KEYBOARD;
            in.ki.wScan = (WORD)*p; in.ki.dwFlags = KEYEVENTF_UNICODE;
            SendInput(1, &in, sizeof(INPUT));
            in.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP;
            SendInput(1, &in, sizeof(INPUT));
        }
        return 0;
    }
    return 2;
}
