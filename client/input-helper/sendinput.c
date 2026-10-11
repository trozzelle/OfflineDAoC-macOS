// sendinput.exe — inject key/mouse events from inside wine (no macOS Accessibility).
// Usage:
//   sendinput sc <scancode-hex> <down|up> [ms-hold]   scancode-based (DirectInput-visible)
//   sendinput vk <vkey-hex> <down|up> [ms-hold]       vkey-based
//   sendinput click <x> <y> [ms]                      absolute move + left click
//   sendinput type <text>                             unicode text via VK_PACKET
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
    if (!strcmp(argv[1], "click") && argc >= 4) {
        int x = atoi(argv[2]), y = atoi(argv[3]);
        int hold = argc >= 5 ? atoi(argv[4]) : 50;
        INPUT in[3] = {0};
        in[0].type = INPUT_MOUSE;
        in[0].mi.dwFlags = MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_MOVE;
        in[0].mi.dx = (DWORD)(x * 65535.0 / GetSystemMetrics(SM_CXSCREEN));
        in[0].mi.dy = (DWORD)(y * 65535.0 / GetSystemMetrics(SM_CYSCREEN));
        in[1] = in[0]; in[1].mi.dwFlags = MOUSEEVENTF_LEFTDOWN;
        in[2] = in[0]; in[2].mi.dwFlags = MOUSEEVENTF_LEFTUP;
        SendInput(1, &in[0], sizeof(INPUT)); Sleep(hold);
        SendInput(2, &in[1], sizeof(INPUT));
        return 0;
    }
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
