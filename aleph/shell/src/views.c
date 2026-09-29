#include <math.h>
#include <stdio.h>
#include <string.h>

#include "shell.h"

#define CONTENT_Y BAR_H
#define CONTENT_H (SCREEN_H - BAR_H)

static bool wants_frame;

/* layout ------------------------------------------------------------------ */

int row_height(Page *p, int i)
{
    Item *it = &p->items[i];
    if (it->header)
        return HEADER_H;
    return p->tall && it->subtitle ? ROW_TALL_H : ROW_H;
}

int item_y(Page *p, int i)
{
    int y = 0;
    for (int k = 0; k < i && k < p->count; k++)
        y += row_height(p, k);
    return y;
}

int list_height(Page *p)
{
    return item_y(p, p->count);
}

static float page_scroll(Page *p)
{
    float t = ease_out((SDL_GetTicks() - p->scroll_at) / (float)ANIM_SCROLL_MS);
    if (t < 1)
        wants_frame = true;
    return p->scroll_from + (p->scroll_to - p->scroll_from) * t;
}

/* pieces ------------------------------------------------------------------ */

static void draw_switch(int x, int y, bool on, bool selected)
{
    Rgba track = on ? C_GREEN : (selected ? RGBA(255, 255, 255, 90) : C_SWITCH_OFF);
    fill_round(x, y, 52, 32, 16, track);
    int kx = on ? x + 22 : x + 2;
    fill_round(kx + 1, y + 3, 28, 28, 14, RGBA(0, 0, 0, 30));
    fill_round(kx, y + 2, 28, 28, 14, C_WHITE);
}

static void draw_selection(int x, int y, int w, int h)
{
    fill_gradient(x, y, w, h, C_SEL_TOP, C_SEL_BOTTOM);
    fill_rect(x, y, w, 1, RGB(126, 184, 246));
    fill_rect(x, y + h - 1, w, 1, C_SEL_LINE);
}

static const char *device_icon(const char *kind)
{
    if (!kind)
        return NULL;
    if (!strcmp(kind, "audio"))
        return "dev-headphones";
    if (!strcmp(kind, "input"))
        return "dev-gamepad";
    return "dev-bluetooth";
}

static void draw_row(Page *p, int i, int x, int y, int w, bool selected)
{
    Item *it = &p->items[i];
    int h = row_height(p, i);
    if (it->header) {
        fill_rect(x, y, w, h, C_HEADER_BG);
        int tw = draw_text(FONT_SEMIBOLD, FONT_HEADER, it->title, x + PAD_X, y + 7, C_TEXT2, w - 2 * PAD_X);
        if (it->spinner) {
            draw_spinner(x + PAD_X + tw + 20, y + h / 2, C_TEXT2);
            wants_frame = true;
        }
        return;
    }
    if (selected)
        draw_selection(x, y, w, h);
    Rgba text = selected ? C_WHITE : C_TEXT;
    Rgba text2 = selected ? RGBA(255, 255, 255, 215) : C_TEXT2;
    int left = x + PAD_X, right = x + w - PAD_X;

    if (p->tall && it->subtitle) {
        const char *fallback = !SDL_strncmp(p->path, "/radio", 6) ? "art-radio" : "art-default";
        draw_image(it->art, fallback, left, y + (h - ART_THUMB) / 2, ART_THUMB, 0);
        fill_rect(left, y + (h - ART_THUMB) / 2 + ART_THUMB, ART_THUMB, 1, RGBA(0, 0, 0, 25));
        left += ART_THUMB + 14;
    } else if (it->icon) {
        const char *name = device_icon(it->icon);
        draw_icon(name, left, y + (h - 28) / 2, selected ? C_WHITE : C_ACCENT);
        left += 40;
    }

    switch (it->accessory) {
    case ACC_CHEVRON:
        draw_icon("chevron", right - 11, y + (h - 20) / 2, selected ? C_WHITE : C_TEXT3);
        right -= 26;
        break;
    case ACC_CHECK:
        draw_icon("check", right - 20, y + (h - 18) / 2, selected ? C_WHITE : C_ACCENT);
        right -= 34;
        break;
    case ACC_SWITCH:
        draw_switch(right - 52, y + (h - 32) / 2, it->on, selected);
        right -= 64;
        break;
    case ACC_SPINNER:
        draw_spinner(right - 12, y + h / 2, selected ? C_WHITE : C_TEXT2);
        wants_frame = true;
        right -= 34;
        break;
    case ACC_PLAYING:
        draw_icon("speaker", right - 22, y + (h - 20) / 2, selected ? C_WHITE : C_ACCENT);
        right -= 36;
        break;
    case ACC_STAR:
        draw_icon("star", right - 20, y + (h - 20) / 2, selected ? C_WHITE : RGB(255, 184, 0));
        right -= 34;
        break;
    }
    if (it->signal >= 0) {
        char name[16];
        snprintf(name, sizeof(name), "wifi-%d", it->signal);
        draw_icon(name, right - 26, y + (h - 20) / 2, selected ? C_WHITE : C_TEXT);
        right -= 36;
    }
    if (it->lock) {
        draw_icon("lock", right - 14, y + (h - 20) / 2, selected ? C_WHITE : C_TEXT);
        right -= 26;
    }
    if (it->value) {
        int vw = draw_text_right(FONT_REGULAR, FONT_VALUE, it->value, right, y + (h - 28) / 2, text2);
        right -= vw + 16;
    }

    int title_w = right - left;
    int ty = p->tall && it->subtitle ? y + 10 : y + (h - 31) / 2;
    if (selected && text_overflows(FONT_SEMIBOLD, FONT_ROW, it->title, title_w)) {
        draw_marquee(FONT_SEMIBOLD, FONT_ROW, it->title, left, ty, title_w, text, p->marquee_at);
        wants_frame = true;
    } else {
        draw_text(FONT_SEMIBOLD, FONT_ROW, it->title, left, ty, text, title_w);
    }
    if (p->tall && it->subtitle)
        draw_text(FONT_REGULAR, FONT_SUB, it->subtitle, left, y + 41, text2, title_w);
}

static void draw_empty(Page *p, int x, int y, int w, int h)
{
    int cy = y + h / 2;
    if (p->empty_icon) {
        char name[48];
        snprintf(name, sizeof(name), "empty-%s", p->empty_icon);
        draw_icon(name, x + w / 2 - 36, cy - 110, C_TEXT3);
    } else {
        cy -= 40;
    }
    draw_text_center(FONT_SEMIBOLD, FONT_BIG - 6, p->empty_title ? p->empty_title : S("empty_list", ""),
                     x + w / 2, cy - 18, C_TEXT, w - 60);
    if (p->empty_text)
        draw_text_wrap_center(FONT_REGULAR, FONT_SUB, p->empty_text, x + w / 2, cy + 24, w - 80, 30, 3, C_TEXT2);
}

static void draw_list(Page *p, int x, int y, int w, int h)
{
    SDL_RenderSetClipRect(app.renderer, &(SDL_Rect){x < 0 ? 0 : x, y, w, h});
    if (!p->loaded) {
        if (SDL_GetTicks() - p->opened_at > 180)
            draw_spinner(x + w / 2, y + h / 2, C_TEXT2);
        wants_frame = true;
    } else if (p->count == 0) {
        draw_empty(p, x, y, w, h);
    } else {
        float scroll = page_scroll(p);
        int total = list_height(p);
        int yy = 0;
        for (int i = 0; i < p->count; i++) {
            int rh = row_height(p, i);
            if (yy + rh > scroll && yy < scroll + h)
                draw_row(p, i, x, y + yy - (int)scroll, w, i == p->sel);
            yy += rh;
            if (yy > scroll + h)
                break;
        }
        if (total > h) {
            int track_h = h - 8;
            int thumb = track_h * h / total;
            if (thumb < 28)
                thumb = 28;
            int ty = y + 4 + (int)((track_h - thumb) * (scroll / (total - h)));
            fill_round(x + w - 8, y + 4, 5, track_h, 2, RGBA(0, 0, 0, 14));
            fill_round(x + w - 8, ty, 5, thumb, 2, RGBA(0, 0, 0, 90));
        }
    }
    SDL_RenderSetClipRect(app.renderer, NULL);
}

/* now playing ------------------------------------------------------------- */

static double live_elapsed(Player *pl)
{
    double e = pl->elapsed;
    if (!strcmp(pl->state, "play"))
        e += (SDL_GetTicks() - pl->elapsed_at) / 1000.0;
    if (pl->duration > 0 && e > pl->duration)
        e = pl->duration;
    return e;
}

static void draw_reflection(const char *path, const char *fallback, int x, int y, int size)
{
    SDL_Texture *t = image(path, size);
    if (!t && fallback) {
        char p[768];
        snprintf(p, sizeof(p), "%s/%s.png", app.asset_dir, fallback);
        t = image(p, size);
    }
    if (!t)
        return;
    const int slices = 18, slice = 3;
    for (int i = 0; i < slices; i++) {
        SDL_Rect src = {0, size - (i + 1) * slice, size, slice};
        SDL_Rect dst = {x, y + i * slice, size, slice};
        SDL_SetTextureColorMod(t, 255, 255, 255);
        SDL_SetTextureAlphaMod(t, (Uint8)(70 * (1 - i / (float)slices)));
        SDL_RenderCopyEx(app.renderer, t, &src, &dst, 0, NULL, SDL_FLIP_VERTICAL);
    }
    SDL_SetTextureAlphaMod(t, 255);
}

static void draw_progress_row(Player *pl, int y)
{
    int bx = 110, bw = 420;
    bool hud = app.hud_at && SDL_GetTicks() - app.hud_at < HUD_MS && !strcmp(app.hud_kind, "volume");
    if (hud) {
        draw_icon("speaker-low", 58, y - 11, C_TEXT2);
        fill_round(bx, y - 5, bw, 10, 5, C_TRACK);
        fill_round(bx, y - 5, bw * app.hud_value / 100, 10, 5, C_ACCENT);
        draw_icon("speaker-high", 548, y - 11, C_TEXT2);
        wants_frame = true;
        return;
    }
    if (!strcmp(pl->kind, "radio")) {
        if (pl->buffering) {
            const char *text = S("connecting", "Connecting…");
            int tw = text_width(FONT_SEMIBOLD, FONT_SMALL, text);
            draw_spinner(SCREEN_W / 2 - tw / 2 - 18, y, C_TEXT2);
            draw_text(FONT_SEMIBOLD, FONT_SMALL, text, SCREEN_W / 2 - tw / 2 + 4, y - 13, C_TEXT2, 0);
            wants_frame = true;
            return;
        }
        const char *live = S("live", "LIVE");
        int tw = text_width(FONT_SEMIBOLD, FONT_SMALL, live);
        bool on_air = !strcmp(pl->state, "play");
        fill_round(SCREEN_W / 2 - tw / 2 - 22, y - 7, 14, 14, 7, on_air ? C_RED : C_TEXT3);
        draw_text(FONT_SEMIBOLD, FONT_SMALL, live, SCREEN_W / 2 - tw / 2, y - 13, C_TEXT2, 0);
        return;
    }
    double e = live_elapsed(pl);
    char a[16], b[16];
    fmt_time(e, a, sizeof(a));
    b[0] = '-';
    fmt_time(pl->duration - e, b + 1, sizeof(b) - 1);
    draw_text_right(FONT_REGULAR, FONT_SMALL, a, bx - 12, y - 13, C_TEXT2);
    draw_text(FONT_REGULAR, FONT_SMALL, b, bx + bw + 12, y - 13, C_TEXT2, 0);
    fill_round(bx, y - 5, bw, 10, 5, C_TRACK);
    int fw = pl->duration > 0 ? (int)(bw * (e / pl->duration)) : 0;
    if (fw > 0) {
        fill_round(bx, y - 5, fw < 10 ? 10 : fw, 10, 5, C_ACCENT);
        fill_rect(bx + 3, y - 4, (fw < 10 ? 10 : fw) - 6, 3, RGBA(255, 255, 255, 60));
    }
}

static void draw_nowplaying(int x)
{
    Player *pl = &app.status.player;
    if (!pl->count && !strcmp(pl->state, "stop")) {
        draw_text_center(FONT_SEMIBOLD, FONT_NP_LINE, S("nothing_playing", ""), x + SCREEN_W / 2,
                         CONTENT_Y + CONTENT_H / 2 - 16, C_TEXT2, SCREEN_W - 80);
        return;
    }
    bool radio = !strcmp(pl->kind, "radio");
    if (!radio && pl->count) {
        char counter[64];
        const char *fmt = S("of", "{pos} of {count}");
        char pos[12], cnt[12];
        snprintf(pos, sizeof(pos), "%d", pl->pos);
        snprintf(cnt, sizeof(cnt), "%d", pl->count);
        const char *p1 = strstr(fmt, "{pos}"), *p2 = strstr(fmt, "{count}");
        if (p1 && p2 && p1 < p2)
            snprintf(counter, sizeof(counter), "%.*s%s%.*s%s%s", (int)(p1 - fmt), fmt, pos,
                     (int)(p2 - p1 - 5), p1 + 5, cnt, p2 + 7);
        else
            snprintf(counter, sizeof(counter), "%s / %s", pos, cnt);
        draw_text(FONT_REGULAR, FONT_SMALL, counter, x + 36, CONTENT_Y + 12, C_TEXT2, 0);
    }
    int ix = x + SCREEN_W - 36;
    if (pl->repeat) {
        draw_icon(pl->single ? "repeat-one" : "repeat", ix - 24, CONTENT_Y + 14, C_ACCENT);
        ix -= 34;
    }
    if (pl->shuffle)
        draw_icon("shuffle", ix - 24, CONTENT_Y + 14, C_ACCENT);

    const int art = 250, ax = x + 36, ay = CONTENT_Y + 50;
    const char *fallback = radio ? "art-radio" : "art-default";
    for (int s = 3; s >= 1; s--)
        fill_round(ax - s * 2, ay - s * 2 + 6, art + s * 4, art + s * 4, 6 + s * 2, RGBA(0, 0, 0, 10));
    draw_image(pl->art, fallback, ax, ay, art, 0);
    stroke_round(ax, ay, art, art, 2, 1, RGBA(0, 0, 0, 30));
    draw_reflection(pl->art, fallback, ax, ay + art + 2, art);

    int tx = ax + art + 28, tw = x + SCREEN_W - 30 - tx;
    int title_lines = text_width(FONT_BOLD, FONT_NP_TITLE, pl->title) > tw ? 2 : 1;
    bool has_album = pl->album && *pl->album;
    int block = title_lines * 38 + 10 + 32 + (has_album ? 32 : 0);
    int ty = ay + art / 2 - block / 2;
    int lines = draw_text_wrap(FONT_BOLD, FONT_NP_TITLE, pl->title, tx, ty, tw, 38, 2, C_TEXT);
    ty += lines * 38 + 10;
    if (pl->artist && *pl->artist)
        draw_text_wrap(FONT_REGULAR, FONT_NP_LINE, pl->artist, tx, ty, tw, 32, radio ? 2 : 1, C_TEXT);
    if (has_album)
        draw_text(FONT_REGULAR, FONT_NP_LINE, pl->album, tx, ty + 32, C_TEXT2, tw);

    draw_progress_row(pl, SCREEN_H - 42);
}

/* slider ------------------------------------------------------------------ */

static void draw_slider(Page *p, int x)
{
    int value = p->value, lo = p->min, hi = p->max > p->min ? p->max : 100;
    char text[16];
    snprintf(text, sizeof(text), "%d%%", value);
    draw_icon("sun-large", x + SCREEN_W / 2 - 28, CONTENT_Y + 70, C_TEXT2);
    draw_text_center(FONT_BOLD, FONT_BIG, text, x + SCREEN_W / 2, CONTENT_Y + 150, C_TEXT, 0);
    int bx = x + 110, bw = 420, by = CONTENT_Y + 250;
    draw_icon("sun-small", x + 62, by - 12, C_TEXT2);
    draw_icon("sun-large-outline", x + 548, by - 16, C_TEXT2);
    fill_round(bx, by - 6, bw, 12, 6, C_TRACK);
    int fw = bw * (value - lo) / (hi - lo);
    fill_round(bx, by - 6, fw < 12 ? 12 : fw, 12, 6, C_ACCENT);
    int kx = bx + fw - 16;
    fill_round(kx + 1, by - 14, 32, 32, 16, RGBA(0, 0, 0, 40));
    fill_round(kx, by - 16, 32, 32, 16, C_WHITE);
}

/* chrome ------------------------------------------------------------------- */

static void draw_bar(const char *title, Uint8 alpha, const char *old_title, Uint8 old_alpha)
{
    fill_gradient(0, 0, SCREEN_W, BAR_H, C_BAR_TOP, C_BAR_BOTTOM);
    fill_rect(0, BAR_H - 1, SCREEN_W, 1, C_BAR_LINE);
    if (old_title && old_alpha)
        draw_text_center(FONT_SEMIBOLD, FONT_BAR, old_title, SCREEN_W / 2, 8, RGBA(17, 17, 17, old_alpha), 340);
    if (title)
        draw_text_center(FONT_SEMIBOLD, FONT_BAR, title, SCREEN_W / 2, 8, RGBA(17, 17, 17, alpha), 340);

    Player *pl = &app.status.player;
    if (!strcmp(pl->state, "play"))
        draw_icon("play", 18, 13, RGB(60, 60, 67));
    else if (!strcmp(pl->state, "pause"))
        draw_icon("pause", 18, 13, RGB(60, 60, 67));

    int bx = SCREEN_W - 18 - 38;
    draw_battery(bx, 13, app.status.battery, app.status.charging);
    if (app.status.bt_audio)
        draw_icon("bt-headphones", bx - 34, 11, C_ACCENT);
}

static void draw_page(Page *p, int x)
{
    if (!p)
        return;
    if (p->style == STYLE_NOWPLAYING)
        draw_nowplaying(x);
    else if (p->style == STYLE_SLIDER)
        draw_slider(p, x);
    else
        draw_list(p, x, CONTENT_Y, SCREEN_W, CONTENT_H);
}

static float overlay_t(Uint32 at, int ms)
{
    float t = ease_out((SDL_GetTicks() - at) / (float)ms);
    if (t < 1)
        wants_frame = true;
    return t;
}

static void draw_sheet_panel(int top, int height, float t)
{
    fill_rect(0, 0, SCREEN_W, SCREEN_H, RGBA(0, 0, 0, (Uint8)(90 * t)));
    int y = top + (int)((1 - t) * (SCREEN_H - top));
    fill_round(0, y, SCREEN_W, height + 24, 18, C_SHEET);
    fill_round(SCREEN_W / 2 - 24, y + 8, 48, 5, 3, RGB(200, 200, 205));
}

static void draw_overlay_page(Page *p)
{
    float t = overlay_t(p->opened_at, 260);
    int rows = p->loaded ? list_height(p) : ROW_H * 3;
    int h = 64 + (rows > 330 ? 330 : rows);
    int top = SCREEN_H - h;
    draw_sheet_panel(top, h, t);
    int y = top + (int)((1 - t) * h);
    draw_text_center(FONT_SEMIBOLD, FONT_BAR, p->title, SCREEN_W / 2, y + 20, C_TEXT, 400);
    fill_rect(0, y + 60, SCREEN_W, 1, C_SEP);
    draw_list(p, 0, y + 62, SCREEN_W, h - 62);
}

static void draw_action_sheet(void)
{
    Sheet *s = &app.sheet;
    float t = overlay_t(s->at, 240);
    bool has_title = s->title && *s->title;
    int h = (has_title ? 56 : 18) + s->count * ROW_H + 12 + ROW_H + 12;
    int top = SCREEN_H - h;
    draw_sheet_panel(top, h, t);
    int y = top + (int)((1 - t) * h) + (has_title ? 22 : 14);
    if (has_title) {
        draw_text_center(FONT_SEMIBOLD, FONT_HEADER + 1, s->title, SCREEN_W / 2, y, C_TEXT2, 520);
        y += 36;
    }
    for (int i = 0; i <= s->count; i++) {
        bool cancel = i == s->count;
        if (cancel)
            y += 12;
        bool sel = i == s->sel;
        if (sel)
            draw_selection(0, y, SCREEN_W, ROW_H);
        const char *label = cancel ? S("cancel", "Cancel") : s->items[i].title;
        Rgba c = sel ? C_WHITE : (!cancel && s->items[i].destructive ? C_RED : C_ACCENT);
        draw_text_center(cancel ? FONT_SEMIBOLD : FONT_MEDIUM, FONT_ROW, label, SCREEN_W / 2, y + 9, c, 520);
        if (!cancel && s->items[i].value)
            draw_text_right(FONT_REGULAR, FONT_VALUE, s->items[i].value, SCREEN_W - PAD_X, y + 11,
                            sel ? C_WHITE : C_TEXT2);
        y += ROW_H;
    }
}

static void draw_confirm(void)
{
    Confirm *c = &app.confirm;
    float t = overlay_t(c->at, 200);
    fill_rect(0, 0, SCREEN_W, SCREEN_H, RGBA(0, 0, 0, (Uint8)(100 * t)));
    int w = 440, h = 190, x = (SCREEN_W - w) / 2, y = (SCREEN_H - h) / 2 + (int)((1 - t) * 30);
    fill_round(x, y + 4, w, h, 20, RGBA(0, 0, 0, 30));
    fill_round(x, y, w, h, 20, C_SHEET);
    draw_text_wrap(FONT_SEMIBOLD, FONT_NP_LINE + 1, c->title, x + 30, y + 34, w - 60, 32, 2, C_TEXT);
    const char *labels[2] = {S("cancel", "Cancel"), c->ok ? c->ok : S("ok", "OK")};
    int bw = (w - 60 - 16) / 2;
    for (int i = 0; i < 2; i++) {
        int bx = x + 30 + i * (bw + 16), by = y + h - 72;
        bool sel = c->choice == i;
        if (sel) {
            fill_round(bx, by, bw, 50, 12, C_SEL_BOTTOM);
            fill_gradient(bx + 6, by + 1, bw - 12, 24, RGBA(255, 255, 255, 45), RGBA(255, 255, 255, 0));
        } else {
            fill_round(bx, by, bw, 50, 12, RGB(229, 229, 234));
        }
        Rgba col = sel ? C_WHITE : (i == 1 && c->destructive ? C_RED : C_ACCENT);
        draw_text_center(FONT_SEMIBOLD, FONT_VALUE + 1, labels[i], bx + bw / 2, by + 11, col, bw - 16);
    }
}

static const char *kb_rows[2][2][4] = {
    {{"qwertyuiop", "asdfghjkl", "zxcvbnm", ""}, {"QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM", ""}},
    {{"1234567890", "-/:;()$&@\"", ".,?!'_", ""}, {"[]{}#%^*+=", "\\|~<>`", ".,?!'_", ""}},
};

/* Dubeolsik, in the same shape as the QWERTY rows. */
static const int kb_jamo_rows[2][3][10] = {
    {{0x3142, 0x3148, 0x3137, 0x3131, 0x3145, 0x315B, 0x3155, 0x3151, 0x3150, 0x3154},
     {0x3141, 0x3134, 0x3147, 0x3139, 0x314E, 0x3157, 0x3153, 0x314F, 0x3163},
     {0x314B, 0x314C, 0x314A, 0x314D, 0x3160, 0x315C, 0x3161}},
    {{0x3143, 0x3149, 0x3138, 0x3132, 0x3146, 0x315B, 0x3155, 0x3151, 0x3152, 0x3156},
     {0x3141, 0x3134, 0x3147, 0x3139, 0x314E, 0x3157, 0x3153, 0x314F, 0x3163},
     {0x314B, 0x314C, 0x314A, 0x314D, 0x3160, 0x315C, 0x3161}},
};

int kb_row_len(int row)
{
    Keyboard *k = &app.keyboard;
    if (row == 3)
        return 4;
    int n = (int)strlen(kb_rows[k->symbols][k->shift][row]);
    return row == 2 ? n + 2 : n;
}

/* The jamo under a letter key in Hangul mode, or 0. */
int kb_jamo(int row, int col)
{
    Keyboard *k = &app.keyboard;
    if (!k->hangul || k->symbols || row > 2)
        return 0;
    if (row == 2 && (col == 0 || col == kb_row_len(2) - 1))
        return 0;
    return kb_jamo_rows[k->shift][row][row == 2 ? col - 1 : col];
}

const char *kb_label(int row, int col, char *buf)
{
    Keyboard *k = &app.keyboard;
    if (row == 3) {
        const char *labels[4] = {k->symbols ? (k->hangul ? "가" : "ABC") : "123", k->hangul ? "A" : "한",
                                 S("space", "space"), S("done", "Done")};
        return labels[col];
    }
    if (row == 2 && col == 0)
        return k->symbols ? (k->shift ? "123" : "#+=") : "⇧";
    if (row == 2 && col == kb_row_len(2) - 1)
        return "⌫";
    int jamo = kb_jamo(row, col);
    if (jamo) {
        hangul_utf8(jamo, buf);
        return buf;
    }
    const char *s = kb_rows[k->symbols][k->shift][row];
    int idx = row == 2 ? col - 1 : col;
    buf[0] = s[idx];
    buf[1] = 0;
    return buf;
}

static void draw_keyboard(void)
{
    Keyboard *k = &app.keyboard;
    float t = overlay_t(k->at, 240);
    fill_rect(0, 0, SCREEN_W, SCREEN_H, RGBA(0, 0, 0, (Uint8)(60 * t)));
    int panel = 268, py = SCREEN_H - panel + (int)((1 - t) * panel);

    int fy = BAR_H + 26;
    fill_round(24, fy - 2, SCREEN_W - 48, 128, 16, RGBA(255, 255, 255, 245));
    draw_text(FONT_SEMIBOLD, FONT_VALUE, k->title ? k->title : "", 44, fy + 12, C_TEXT, SCREEN_W - 88);
    fill_round(44, fy + 52, SCREEN_W - 88, 50, 10, RGB(242, 242, 247));
    char shown[512];
    if (k->secret) {
        size_t n = 0;
        for (const char *c = k->text; *c && n + 4 < sizeof(shown); c++)
            if (((unsigned char)*c & 0xC0) != 0x80) {
                memcpy(shown + n, "•", 3);
                n += 3;
            }
        shown[n] = 0;
    } else {
        SDL_strlcpy(shown, k->text, sizeof(shown));
    }
    int tx = 60;
    if (*shown) {
        tx += draw_text(FONT_MEDIUM, FONT_ROW, shown, 60, fy + 62, C_TEXT, SCREEN_W - 140);
    } else if (k->placeholder) {
        draw_text(FONT_REGULAR, FONT_ROW, k->placeholder, 60, fy + 62, C_TEXT3, SCREEN_W - 140);
    }
    if ((SDL_GetTicks() / 530) % 2 == 0)
        fill_rect(tx + 2, fy + 63, 2, 30, C_ACCENT);

    fill_rect(0, py, SCREEN_W, panel, C_KEYBOARD_BG);
    int ky = py + 12;
    char buf[8];
    for (int row = 0; row < 4; row++) {
        int n = kb_row_len(row);
        int gap = 6, kh = 54;
        int widths[12], total = 0;
        for (int c = 0; c < n; c++) {
            if (row == 3)
                widths[c] = c == 2 ? 290 : c == 1 ? 90 : 110;
            else if (row == 2 && (c == 0 || c == n - 1))
                widths[c] = 84;
            else
                widths[c] = 56;
            total += widths[c] + (c ? gap : 0);
        }
        int kx = (SCREEN_W - total) / 2;
        for (int c = 0; c < n; c++) {
            bool special = row == 3 ? c != 2 : (row == 2 && (c == 0 || c == n - 1));
            bool sel = k->row == row && k->col == c;
            fill_round(kx, ky + 2, widths[c], kh, 9, RGBA(0, 0, 0, 45));
            if (sel)
                fill_round(kx, ky, widths[c], kh, 9, C_SEL_BOTTOM);
            else
                fill_round(kx, ky, widths[c], kh, 9, special ? C_KEY_DARK : C_KEY);
            const char *label = kb_label(row, c, buf);
            int size = row == 3 || (row == 2 && special) ? FONT_VALUE : FONT_KEY;
            if (row == 2 && c == 0 && !k->symbols && k->shift && !sel)
                fill_round(kx, ky, widths[c], kh, 9, RGB(255, 255, 255));
            draw_text_center(FONT_MEDIUM, size, label, kx + widths[c] / 2, ky + (kh - size - 10) / 2,
                             sel ? C_WHITE : C_TEXT, widths[c] - 8);
            kx += widths[c] + gap;
        }
        ky += kh + 8;
    }
}

static void draw_toast(void)
{
    Uint32 age = SDL_GetTicks() - app.toast_at;
    if (!app.toast_at || age > TOAST_MS)
        return;
    wants_frame = true;
    float a = age < 160 ? age / 160.0f : age > TOAST_MS - 300 ? (TOAST_MS - age) / 300.0f : 1;
    bool has_icon = app.toast_icon[0] != 0;
    int tw = text_width(FONT_SEMIBOLD, FONT_SMALL, app.toast);
    if (tw > 460)
        tw = 460;
    int w = tw + 44 + (has_icon ? 34 : 0), h = 46, x = (SCREEN_W - w) / 2;
    int y = BAR_H + 14 - (int)((1 - a) * 12);
    fill_round(x, y, w, h, 23, RGBA(28, 28, 30, (Uint8)(228 * a)));
    int cx = x + 22;
    if (has_icon) {
        char name[48];
        snprintf(name, sizeof(name), "toast-%s", app.toast_icon);
        draw_icon(name, cx, y + 12, RGBA(255, 255, 255, (Uint8)(255 * a)));
        cx += 34;
    }
    draw_text(FONT_SEMIBOLD, FONT_SMALL, app.toast, cx, y + 11, RGBA(255, 255, 255, (Uint8)(255 * a)), 460);
}

static void draw_hud(void)
{
    Page *p = top();
    Uint32 age = SDL_GetTicks() - app.hud_at;
    if (!app.hud_at || age > HUD_MS || (p && p->style == STYLE_NOWPLAYING && !app.overlay))
        return;
    wants_frame = true;
    float a = age > HUD_MS - 250 ? (HUD_MS - age) / 250.0f : 1;
    int w = 220, h = 190, x = (SCREEN_W - w) / 2, y = (SCREEN_H - h) / 2 + 10;
    fill_round(x, y, w, h, 24, RGBA(28, 28, 30, (Uint8)(215 * a)));
    const char *name = app.hud_value == 0 ? "hud-mute" : (!strcmp(app.status.output, "bluetooth") ? "hud-headphones" : "hud-speaker");
    draw_icon(name, x + w / 2 - 40, y + 30, RGBA(255, 255, 255, (Uint8)(255 * a)));
    fill_round(x + 26, y + h - 40, w - 52, 10, 5, RGBA(255, 255, 255, (Uint8)(60 * a)));
    fill_round(x + 26, y + h - 40, (w - 52) * app.hud_value / 100 + 1, 10, 5, RGBA(255, 255, 255, (Uint8)(255 * a)));
}

static void draw_letter(void)
{
    Uint32 age = SDL_GetTicks() - app.letter_at;
    if (!app.letter_at || age > 600)
        return;
    wants_frame = true;
    float a = age > 400 ? (600 - age) / 200.0f : 1;
    fill_round(SCREEN_W / 2 - 64, SCREEN_H / 2 - 50, 128, 128, 24, RGBA(28, 28, 30, (Uint8)(200 * a)));
    draw_text_center(FONT_BOLD, 60, app.letter, SCREEN_W / 2, SCREEN_H / 2 - 30, RGBA(255, 255, 255, (Uint8)(255 * a)), 0);
}

/* frame --------------------------------------------------------------------- */

void render(void)
{
    wants_frame = false;
    gfx_frame_begin();
    if (!app.status.screen_on) {
        SDL_SetRenderDrawColor(app.renderer, 0, 0, 0, 255);
        SDL_RenderClear(app.renderer);
        SDL_RenderPresent(app.renderer);
        return;
    }
    SDL_SetRenderDrawColor(app.renderer, 255, 255, 255, 255);
    SDL_RenderClear(app.renderer);

    Page *p = top();
    const char *title = p ? p->title : "aleph";
    if (app.transition && app.leaving) {
        float t = ease_out((SDL_GetTicks() - app.transition_at) / (float)ANIM_PUSH_MS);
        int dir = app.transition;
        int off = (int)(SCREEN_W * t);
        draw_page(app.leaving, dir > 0 ? -off : off);
        draw_page(p, dir > 0 ? SCREEN_W - off : off - SCREEN_W);
        draw_bar(title, (Uint8)(255 * t), app.leaving->title, (Uint8)(255 * (1 - t)));
        wants_frame = true;
        if (t >= 1) {
            if (dir < 0)
                page_free(app.leaving);
            app.leaving = NULL;
            app.transition = 0;
        }
    } else {
        draw_page(p, 0);
        draw_bar(title, 255, NULL, 0);
    }
    if (app.overlay)
        draw_overlay_page(app.overlay);
    if (app.sheet.active)
        draw_action_sheet();
    if (app.confirm.active)
        draw_confirm();
    if (app.keyboard.active)
        draw_keyboard();
    draw_letter();
    draw_hud();
    draw_toast();
    SDL_RenderPresent(app.renderer);
}

/* Milliseconds until the next frame is needed; -1 means sleep until an event. */
int next_frame_delay(void)
{
    if (!app.status.screen_on)
        return -1;
    if (wants_frame || app.transition)
        return 16;
    int delay = -1;
    Page *p = top();
    if (p && p->style == STYLE_NOWPLAYING && !strcmp(app.status.player.state, "play")) {
        double e = app.status.player.elapsed + (SDL_GetTicks() - app.status.player.elapsed_at) / 1000.0;
        delay = (int)((1.0 - (e - (int)e)) * 1000) + 5;
    }
    if (app.keyboard.active)
        delay = delay < 0 || delay > 530 ? 530 - (int)(SDL_GetTicks() % 530) + 1 : delay;
    return delay;
}

bool animating(void)
{
    return wants_frame || app.transition;
}
