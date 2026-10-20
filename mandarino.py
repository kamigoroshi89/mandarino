#!/usr/bin/env python3
"""Mandarino – convertitore di file offline per Ubuntu (GTK4 + Wayland)."""
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading

APP_ID = "it.mandarino.App"

IMG_EXT = {"jpg", "jpeg", "png", "webp", "tif", "tiff", "bmp", "gif", "heic", "heif", "avif"}
HEIF_EXT = {"heic", "heif", "avif"}
DOC_EXT = {"doc", "docx", "odt", "rtf", "txt", "md", "markdown", "epub", "html", "htm"}
LO_SRC = {"doc", "docx", "odt", "rtf", "txt"}
LO_DST = {"pdf", "docx", "odt", "rtf", "txt", "html"}

IMG_TARGETS = ["png", "jpg", "webp", "tiff", "bmp", "gif", "pdf"]
PDF_TARGETS = ["docx", "odt", "png", "jpg", "txt"]
DOC_TARGETS = ["pdf", "docx", "odt", "md", "html", "epub", "rtf", "txt"]

LO_PROFILE = "-env:UserInstallation=file:///tmp/mandarino-lo"


class ConvError(Exception):
    """Errore leggibile da mostrare all'utente."""


# ---------------------------------------------------------------- utilità

def ext_of(path):
    return os.path.splitext(path)[1].lower().lstrip(".")


def category(path):
    if os.path.isdir(path):
        return "dir"
    e = ext_of(path)
    if e in IMG_EXT:
        return "img"
    if e == "pdf":
        return "pdf"
    if e in DOC_EXT:
        return "doc"
    return "other"


def norm_ext(e):
    return {"jpeg": "jpg", "tif": "tiff", "markdown": "md", "htm": "html", "heif": "heic"}.get(e, e)


def need(prog):
    p = shutil.which(prog)
    if not p:
        raise ConvError(f"Programma mancante: {prog}")
    return p


def run(cmd, ok_codes=(0,), cwd=None):
    """Esegue un programma esterno (mai tramite shell)."""
    need(cmd[0])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=600)
    except subprocess.TimeoutExpired:
        raise ConvError(f"{cmd[0]}: tempo scaduto")
    if r.returncode not in ok_codes:
        msg = (r.stderr or r.stdout or "").strip().splitlines()
        raise ConvError(f"{cmd[0]} ha fallito: {msg[-1] if msg else r.returncode}")
    return r


def unique_path(path):
    """Restituisce un percorso libero: nome.ext, nome (1).ext, ..."""
    if not os.path.lexists(path):
        return path
    base, ext = os.path.splitext(path)
    n = 1
    while os.path.lexists(f"{base} ({n}){ext}"):
        n += 1
    return f"{base} ({n}){ext}"


def deliver(tmp_files, dest_dir):
    """Sposta i risultati accanto all'originale senza sovrascrivere."""
    out = []
    for f in tmp_files:
        if not os.path.isfile(f) or os.path.getsize(f) == 0:
            raise ConvError(f"Risultato vuoto o mancante: {os.path.basename(f)}")
        dst = unique_path(os.path.join(dest_dir, os.path.basename(f)))
        shutil.move(f, dst)
        out.append(dst)
    return out


def stem(path):
    return os.path.splitext(os.path.basename(path))[0]


def magick_cmd():
    for p in ("magick", "convert"):
        if shutil.which(p):
            return [p]
    raise ConvError("Programma mancante: imagemagick")


# ---------------------------------------------------------------- immagini

def img_to_png_if_heif(src, tmp):
    """HEIC/HEIF/AVIF -> PNG con heif-convert; altrimenti il file stesso."""
    if ext_of(src) in HEIF_EXT:
        out = os.path.join(tmp, stem(src) + "-heif.png")
        run(["heif-convert", src, out])
        if not os.path.exists(out):
            # heif-convert può aggiungere un suffisso -1 se ci sono più immagini
            cands = sorted(f for f in os.listdir(tmp) if f.startswith(stem(src) + "-heif"))
            if not cands:
                raise ConvError("heif-convert non ha prodotto file")
            out = os.path.join(tmp, cands[0])
        return out
    return src


def first_frame(path):
    return path + "[0]" if ext_of(path) == "gif" else path


def img_convert(src, fmt, tmp):
    fmt = norm_ext(fmt)
    work = img_to_png_if_heif(src, tmp)
    name = stem(src)
    out = os.path.join(tmp, f"{name}.{fmt}")
    if fmt == "pdf":
        _pil_to_pdf([work], out)
        return [out]
    cmd = magick_cmd() + [first_frame(work)]
    if fmt in ("jpg", "bmp"):
        cmd += ["-background", "white", "-alpha", "remove", "-alpha", "off"]
    if fmt == "gif" and ext_of(work) == "gif":
        cmd = magick_cmd() + [work]  # GIF -> GIF: mantieni l'animazione
    run(cmd + [out])
    return [out]


def _pil_to_pdf(paths, out):
    from PIL import Image
    imgs = []
    for p in paths:
        im = Image.open(p)
        im.seek(0)
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, "white")
            bg.paste(im, mask=im.split()[-1])
            im = bg
        else:
            im = im.convert("RGB")
        imgs.append(im)
    if not imgs:
        raise ConvError("Nessuna immagine da unire")
    imgs[0].save(out, "PDF", resolution=100.0, save_all=True, append_images=imgs[1:])


def img_compress(src, tmp):
    work = img_to_png_if_heif(src, tmp)
    e = ext_of(work)
    outext = "jpg" if ext_of(src) in HEIF_EXT else norm_ext(e)
    out = os.path.join(tmp, f"{stem(src)}-compresso.{outext}")
    cmd = magick_cmd() + [first_frame(work), "-strip"]
    if outext in ("jpg", "webp"):
        cmd += ["-quality", "75"]
    if outext == "jpg":
        cmd += ["-background", "white", "-alpha", "remove", "-alpha", "off"]
    elif outext == "png":
        cmd += ["-define", "png:compression-level=9"]
    run(cmd + [out])
    return [out]


def img_simple(src, tmp, suffix, args):
    work = img_to_png_if_heif(src, tmp)
    e = "png" if ext_of(src) in HEIF_EXT else norm_ext(ext_of(work))
    out = os.path.join(tmp, f"{stem(src)}-{suffix}.{e}")
    first = work if ext_of(work) == "gif" and suffix == "ruotato" else first_frame(work)
    run(magick_cmd() + [first] + args + [out])
    return [out]


def img_merge_pdf(srcs, tmp):
    paths = [img_to_png_if_heif(s, tmp) for s in srcs]
    out = os.path.join(tmp, f"{stem(srcs[0])}-unito.pdf")
    _pil_to_pdf(paths, out)
    return [out]


# ---------------------------------------------------------------- PDF

def pdf_convert(src, fmt, tmp):
    name = stem(src)
    if fmt in ("docx", "odt"):
        return lo_convert(src, fmt, tmp, infilter="writer_pdf_import")
    if fmt in ("png", "jpg"):
        flag = "-png" if fmt == "png" else "-jpeg"
        run(["pdftoppm", flag, "-r", "300", src, os.path.join(tmp, name)])
        files = sorted(os.path.join(tmp, f) for f in os.listdir(tmp)
                       if f.startswith(name + "-") and f.endswith("." + fmt))
        if not files:
            raise ConvError("pdftoppm non ha prodotto pagine")
        return files
    if fmt == "txt":
        out = os.path.join(tmp, name + ".txt")
        run(["pdftotext", "-layout", src, out])
        return [out]
    raise ConvError(f"Formato non supportato: {fmt}")


def pdf_compress(src, tmp):
    out = os.path.join(tmp, f"{stem(src)}-compresso.pdf")
    run(["gs", "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.4", "-dPDFSETTINGS=/ebook",
         "-dNOPAUSE", "-dQUIET", "-dBATCH", f"-sOutputFile={out}", src])
    return [out]


def pdf_split(src, tmp):
    name = stem(src)
    run(["qpdf", "--split-pages", src, os.path.join(tmp, f"{name}-pagina-%d.pdf")], ok_codes=(0, 3))
    files = [os.path.join(tmp, f) for f in os.listdir(tmp) if f.startswith(name + "-pagina-")]
    files.sort(key=lambda p: int(re.search(r"-pagina-(\d+)\.pdf$", p).group(1)))
    if not files:
        raise ConvError("qpdf non ha prodotto pagine")
    return files


def pdf_rotate(src, tmp):
    out = os.path.join(tmp, f"{stem(src)}-ruotato.pdf")
    run(["qpdf", "--rotate=+90", src, out], ok_codes=(0, 3))
    return [out]


def pdf_merge(srcs, tmp):
    out = os.path.join(tmp, f"{stem(srcs[0])}-unito.pdf")
    run(["qpdf", "--empty", "--pages", *srcs, "--", out], ok_codes=(0, 3))
    return [out]


# ---------------------------------------------------------------- documenti

def lo_convert(src, fmt, tmp, infilter=None):
    need_prog = "soffice" if shutil.which("soffice") else "libreoffice"
    cmd = [need_prog, LO_PROFILE, "--headless"]
    if infilter:
        cmd.append(f"--infilter={infilter}")
    outdir = tempfile.mkdtemp(dir=tmp)
    lo_fmt = "txt:Text" if fmt == "txt" else fmt
    run(cmd + ["--convert-to", lo_fmt, "--outdir", outdir, src])
    out = os.path.join(outdir, stem(src) + "." + fmt)
    if not os.path.isfile(out) or os.path.getsize(out) == 0:
        raise ConvError("LibreOffice non ha prodotto il file")
    final = os.path.join(tmp, os.path.basename(out))
    shutil.move(out, final)
    return [final]


def doc_convert(src, fmt, tmp):
    fmt = norm_ext(fmt)
    se = norm_ext(ext_of(src))
    if se in LO_SRC and fmt in LO_DST:
        return lo_convert(src, fmt, tmp)
    work = src
    if se in ("doc", "rtf", "txt"):
        work = lo_convert(src, "docx", tmp)[0]
        mid = os.path.join(tmp, "mid-" + os.path.basename(work))
        shutil.move(work, mid)
        work = mid
    name = stem(src)
    if fmt in ("pdf", "rtf", "txt"):
        mid = os.path.join(tmp, name + "-mid.docx")
        run(["pandoc", work, "-o", mid])
        res = lo_convert(mid, fmt, tmp)
        final = os.path.join(tmp, f"{name}.{fmt}")
        shutil.move(res[0], final)
        return [final]
    out = os.path.join(tmp, f"{name}.{fmt}")
    cmd = ["pandoc", work]
    if fmt == "md":
        cmd += ["-t", "gfm"]
    elif fmt == "html":
        cmd += ["-s", "--embed-resources", "--metadata", f"title={name}"]
    run(cmd + ["-o", out], cwd=os.path.dirname(os.path.abspath(src)))
    return [out]


# ---------------------------------------------------------------- catalogo voci

def convert_items(cat, first):
    """Voci della scheda Converti: lista di (etichetta, chiave)."""
    se = norm_ext(ext_of(first))
    if cat == "img":
        t = IMG_TARGETS
    elif cat == "pdf":
        t = PDF_TARGETS
    elif cat == "doc":
        t = DOC_TARGETS
    else:
        return []
    return [(x.upper(), x) for x in t if x != se]


def tool_items(cat, n):
    if cat == "img":
        items = [("Comprimi", "compress"), ("Riduci 50%", "half"),
                 ("Ruota 90°", "rotate"), ("Togli metadati", "strip")]
        if n > 1:
            items.append(("Unisci in PDF", "merge"))
        return items
    if cat == "pdf":
        items = [("Comprimi", "compress"), ("Dividi pagine", "split"), ("Ruota 90°", "rotate")]
        if n > 1:
            items.append(("Unisci", "merge"))
        return items
    return []


def process(cat, kind, key, files, progress=None):
    """Esegue il lavoro su `files`. Restituisce (creati, saltati)."""
    created, skipped = [], []
    if kind == "tool" and key == "merge":
        with tempfile.TemporaryDirectory(prefix="mandarino-") as tmp:
            res = img_merge_pdf(files, tmp) if cat == "img" else pdf_merge(files, tmp)
            created += deliver(res, os.path.dirname(files[0]))
        return created, skipped
    for f in files:
        if kind == "conv" and norm_ext(ext_of(f)) == key:
            skipped.append(f)
            continue
        with tempfile.TemporaryDirectory(prefix="mandarino-") as tmp:
            if kind == "conv":
                res = (img_convert(f, key, tmp) if cat == "img" else
                       pdf_convert(f, key, tmp) if cat == "pdf" else
                       doc_convert(f, key, tmp))
            elif cat == "img":
                res = (img_compress(f, tmp) if key == "compress" else
                       img_simple(f, tmp, "ridotto", ["-resize", "50%"]) if key == "half" else
                       img_simple(f, tmp, "ruotato", ["-rotate", "90"]) if key == "rotate" else
                       img_simple(f, tmp, "pulito", ["-strip"]))
            else:
                res = (pdf_compress(f, tmp) if key == "compress" else
                       pdf_split(f, tmp) if key == "split" else
                       pdf_rotate(f, tmp))
            created += deliver(res, os.path.dirname(f))
    return created, skipped


# ---------------------------------------------------------------- interfaccia

def run_ui():
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    gi.require_version("PangoCairo", "1.0")
    import cairo
    from gi.repository import Gdk, Gio, GLib, Gtk, Pango, PangoCairo

    CSS = b"""
    @define-color accent #7F77DD;
    window.drop, window.wheel { background: transparent; }

    .drop-disc { min-width: 64px; min-height: 64px; border-radius: 99px;
                 background: rgba(255,255,255,0.80); border: 1px solid alpha(@accent, 0.33);
                 box-shadow: 0 2px 10px rgba(0,0,0,0.2); transition: all 150ms ease; }
    .drop-dot { min-width: 6px; min-height: 6px; border-radius: 99px; background: @accent;
                transition: all 300ms ease; }
    .drop-disc.hover { background: alpha(@accent, 0.33); border-color: @accent;
                       box-shadow: 0 0 18px 2px alpha(@accent, 0.4); }
    .drop-disc.busy { border-color: @accent; }
    .drop-disc.busy .drop-dot { min-width: 14px; min-height: 14px; }
    .drop-disc.busy.pulse .drop-dot { min-width: 8px; min-height: 8px; }
    window.dark .drop-disc { background: rgba(32,32,36,0.73); border-color: rgba(255,255,255,0.4); }
    window.dark .drop-disc.hover { background: alpha(@accent, 0.33); border-color: @accent; }
    window.dark .drop-disc.busy { border-color: @accent; }

    .wheel-box { background: rgba(255,255,255,0.93); border-radius: 250px;
                 border: 1px solid alpha(@accent, 0.33); }
    .wheel-title { font-weight: 600; font-size: 15px; color: #222; }
    .wheel-hint { font-size: 11px; color: rgba(0,0,0,0.5); }
    .wheel-item { background: rgba(0,0,0,0.04); border: 1px solid rgba(0,0,0,0.08);
                  border-radius: 99px; padding: 4px 8px; color: #222; box-shadow: none;
                  transition: all 120ms ease; }
    .wheel-item:hover { background: alpha(@accent, 0.12); }
    .wheel-item.sel { background: alpha(@accent, 0.22); border-color: @accent; }
    .wheel-tab { background: transparent; border-radius: 99px; padding: 2px 8px; min-height: 0;
                 color: rgba(0,0,0,0.55); box-shadow: none; }
    .wheel-tab.sel { background: alpha(@accent, 0.22); color: #222; }
    window.dark .wheel-box { background: rgba(32,32,36,0.85); border-color: rgba(255,255,255,0.25); }
    window.dark .wheel-title, window.dark .wheel-item, window.dark .wheel-tab.sel { color: #eee; }
    window.dark .wheel-hint { color: rgba(255,255,255,0.5); }
    window.dark .wheel-item { background: rgba(255,255,255,0.06); border-color: rgba(255,255,255,0.12); }
    window.dark .wheel-item:hover { background: alpha(@accent, 0.2); }
    window.dark .wheel-item.sel { background: alpha(@accent, 0.35); border-color: @accent; }
    window.dark .wheel-tab { color: rgba(255,255,255,0.6); }
    window.dark .wheel-tab.sel { background: alpha(@accent, 0.35); }
    """
    TABS = [("conv", "Converti"), ("tool", "Strumenti"), ("act", "Azioni")]
    ACTIONS = [("Copia percorso", "copy"), ("Mostra in File", "show"),
               ("Terminale qui", "term"), ("Cestino", "trash")]

    def is_dark():
        src = Gio.SettingsSchemaSource.get_default()
        if src and src.lookup("org.gnome.desktop.interface", True):
            return Gio.Settings.new("org.gnome.desktop.interface").get_string("color-scheme") == "prefer-dark"
        return Gtk.Settings.get_default().get_property("gtk-application-prefer-dark-theme")

    def follow_theme(win):
        """Classe 'dark' sulla finestra, aggiornata se cambia il tema di sistema."""
        def update(*_):
            (win.add_css_class if is_dark() else win.remove_css_class)("dark")
        update()
        src = Gio.SettingsSchemaSource.get_default()
        if src and src.lookup("org.gnome.desktop.interface", True):
            win._theme_settings = Gio.Settings.new("org.gnome.desktop.interface")
            win._theme_settings.connect("changed::color-scheme", update)

    def notify(title, body):
        if shutil.which("notify-send"):
            subprocess.Popen(["notify-send", "-a", "Mandarino", title, body])

    def build_tabs(files):
        """(categoria, voci per scheda, scheda iniziale); `files` si riduce alla categoria del primo."""
        cat = category(files[0])
        if cat != "dir":
            files[:] = [f for f in files if category(f) == cat]
        tabs = {
            "conv": convert_items(cat, files[0]) if cat != "dir" else [],
            "tool": tool_items(cat, len(files)) if cat != "dir" else [],
            "act": ACTIONS,
        }
        tab = "act" if cat == "dir" else next((t for t in ("conv", "tool", "act") if tabs[t]), "act")
        return cat, tabs, tab

    SIZE = 320                 # lato della finestra: la ciambella ci sta dentro, centrata sul cerchio
    R_CORE = 46                # dentro: cerchio centrale
    R_TAB = (46, 90)           # anello interno: schede
    R_ITEM = (96, 152)         # anello esterno: voci della scheda attiva
    ACCENT = (0x7F / 255, 0x77 / 255, 0xDD / 255)

    class Donut(Gtk.DrawingArea):
        """Ciambella a spicchi mostrata mentre si trascina: anello interno = schede, esterno = voci."""

        def __init__(self):
            super().__init__()
            self.set_content_width(SIZE)
            self.set_content_height(SIZE)
            self.set_can_target(False)
            self.set_draw_func(self.draw)
            self.files, self.cat, self.tabs, self.tab = [], None, {}, "act"
            self.hover = None

        def set_files(self, files):
            self.files = list(files)
            self.hover = None
            if self.files:
                self.cat, self.tabs, self.tab = build_tabs(self.files)
            self.queue_draw()

        def tab_keys(self):
            return [k for k, _ in TABS if self.tabs.get(k)]

        @staticmethod
        def index(a, n):
            """Spicchio (0..n-1) che contiene l'angolo a; il primo è centrato in alto."""
            step = 2 * math.pi / n
            return int(((a + math.pi / 2 + step / 2) % (2 * math.pi)) // step)

        @staticmethod
        def span(i, n):
            step = 2 * math.pi / n
            c = -math.pi / 2 + i * step
            return c - step / 2, c + step / 2

        def hit(self, x, y):
            """("core",) | ("tab", chiave) | ("item", indice) | None"""
            dx, dy = x - self.get_width() / 2, y - self.get_height() / 2
            r, a = math.hypot(dx, dy), math.atan2(dy, dx)
            if r < R_CORE:
                return ("core",)
            if not self.files:
                return None
            if r <= R_TAB[1]:
                keys = self.tab_keys()
                return ("tab", keys[self.index(a, len(keys))]) if keys else None
            if R_ITEM[0] <= r <= R_ITEM[1] and self.tabs[self.tab]:
                return ("item", self.index(a, len(self.tabs[self.tab])))
            return None

        def move(self, x, y):
            h = self.hit(x, y)
            if h and h[0] == "tab":
                self.tab = h[1]
            h = h if h and h[0] != "core" else None
            if h != self.hover:
                self.hover = h
                self.queue_draw()

        def draw(self, _area, cr, w, h):
            if not self.files:
                return
            dark = is_dark()
            text = (0.93,) * 3 if dark else (0.13,) * 3
            fill = (0.125, 0.125, 0.14, 0.85) if dark else (1, 1, 1, 0.93)
            edge = (1, 1, 1, 0.25) if dark else (*ACCENT, 0.33)
            cx, cy = w / 2, h / 2

            def piece(r0, r1, a0, a1, state, label, font, width):
                gap = 3
                cr.new_path()
                cr.arc(cx, cy, r1, a0 + gap / r1, a1 - gap / r1)
                cr.arc_negative(cx, cy, r0, a1 - gap / r0, a0 + gap / r0)
                cr.close_path()
                if state == "hover":
                    cr.set_source_rgba(*ACCENT, 0.35)
                elif state == "active":
                    cr.set_source_rgba(*ACCENT, 0.22)
                else:
                    cr.set_source_rgba(*fill)
                cr.fill_preserve()
                cr.set_source_rgba(*ACCENT, 1) if state == "hover" else cr.set_source_rgba(*edge)
                cr.set_line_width(1)
                cr.stroke()
                lay = self.create_pango_layout(label)
                lay.set_font_description(Pango.FontDescription.from_string(font))
                lay.set_width(int(width * Pango.SCALE))
                lay.set_ellipsize(Pango.EllipsizeMode.END)
                lay.set_alignment(Pango.Alignment.CENTER)
                am, rm = (a0 + a1) / 2, (r0 + r1) / 2
                _tw, th = lay.get_pixel_size()
                cr.move_to(cx + rm * math.cos(am) - width / 2, cy + rm * math.sin(am) - th / 2)
                cr.set_source_rgb(*text)
                PangoCairo.update_layout(cr, lay)
                PangoCairo.show_layout(cr, lay)

            keys = self.tab_keys()
            names = dict(TABS)
            for i, k in enumerate(keys):
                a0, a1 = self.span(i, len(keys))
                state = "hover" if self.hover == ("tab", k) else "active" if k == self.tab else "idle"
                piece(*R_TAB, a0, a1, state, names[k], "Sans 9", 76)
            items = self.tabs[self.tab]
            n = len(items)
            width = min(110, 2 * 124 * math.sin(math.pi / n) - 10) if n > 1 else 110
            for i, (label, _key) in enumerate(items):
                a0, a1 = self.span(i, n)
                piece(*R_ITEM, a0, a1, "hover" if self.hover == ("item", i) else "idle", label, "Sans 10", width)

    class Wheel(Gtk.Window):
        def __init__(self, app, files, on_run):
            super().__init__(application=app)
            self.files, self.on_run = files, on_run
            self.cat, self.tabs, self.tab = build_tabs(files)
            self.set_decorated(False)
            self.set_modal(True)
            self.set_resizable(False)
            self.set_default_size(500, 500)
            self.add_css_class("wheel")
            follow_theme(self)
            self.sel = 0
            self.items_btns = []

            self.fixed = Gtk.Fixed()
            self.fixed.set_size_request(500, 500)
            self.fixed.add_css_class("wheel-box")
            self.set_child(self.fixed)

            name = os.path.basename(files[0]) if len(files) == 1 else f"{len(files)} elementi"
            if len(name) > 26:
                name = name[:23] + "…"
            center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            center.set_size_request(230, 150)
            center.set_valign(Gtk.Align.CENTER)
            self.fixed.put(center, 135, 175)
            self.title_lbl = Gtk.Label(label=name)
            self.title_lbl.add_css_class("wheel-title")
            center.append(self.title_lbl)

            tabbox = Gtk.Box(spacing=0)
            tabbox.set_halign(Gtk.Align.CENTER)
            self.tab_btns = {}
            for k, label in TABS:
                b = Gtk.Button(label=label)
                b.add_css_class("flat")
                b.add_css_class("wheel-tab")
                b.connect("clicked", lambda _b, k=k: self.set_tab(k))
                tabbox.append(b)
                self.tab_btns[k] = b
            center.append(tabbox)

            self.empty_lbl = Gtk.Label(label="Niente da fare qui")
            center.append(self.empty_lbl)

            hint = Gtk.Label(label="Shift Converti · Ctrl Strumenti · Alt Azioni\n"
                                   "frecce scelgono · Invio applica · Esc chiude")
            hint.add_css_class("wheel-hint")
            hint.set_justify(Gtk.Justification.CENTER)
            center.append(hint)

            keys = Gtk.EventControllerKey()
            keys.connect("key-pressed", self.on_key)
            self.add_controller(keys)
            self.rebuild()

        def rebuild(self):
            for b in self.items_btns:
                self.fixed.remove(b)
            self.items_btns = []
            items = self.tabs[self.tab]
            self.empty_lbl.set_visible(not items)
            for k, b in self.tab_btns.items():
                (b.add_css_class if k == self.tab else b.remove_css_class)("sel")
            n = len(items)
            self.sel = min(self.sel, max(n - 1, 0))
            # raggio 185, voci 100x34: restano fuori dal blocco centrale (x 135..365)
            for i, (label, key) in enumerate(items):
                ang = -math.pi / 2 + 2 * math.pi * i / max(n, 1)
                cx = 250 + 185 * math.cos(ang)
                cy = 250 + 185 * math.sin(ang)
                b = Gtk.Button(label=label)
                b.add_css_class("flat")
                b.add_css_class("wheel-item")
                b.set_size_request(100, 34)
                b.set_can_focus(False)
                b.connect("clicked", lambda _b, i=i: self.apply(i))
                self.fixed.put(b, cx - 50, cy - 17)
                self.items_btns.append(b)
            self.refresh_sel()

        def refresh_sel(self):
            for i, b in enumerate(self.items_btns):
                (b.add_css_class if i == self.sel else b.remove_css_class)("sel")

        def set_tab(self, k):
            self.tab, self.sel = k, 0
            self.rebuild()

        def on_key(self, _c, keyval, _code, _state):
            n = len(self.items_btns)
            if keyval == Gdk.KEY_Escape:
                self.close()
            elif keyval in (Gdk.KEY_Shift_L, Gdk.KEY_Shift_R):
                self.set_tab("conv")
            elif keyval in (Gdk.KEY_Control_L, Gdk.KEY_Control_R):
                self.set_tab("tool")
            elif keyval in (Gdk.KEY_Alt_L, Gdk.KEY_Alt_R):
                self.set_tab("act")
            elif keyval in (Gdk.KEY_Right, Gdk.KEY_Down) and n:
                self.sel = (self.sel + 1) % n
                self.refresh_sel()
            elif keyval in (Gdk.KEY_Left, Gdk.KEY_Up) and n:
                self.sel = (self.sel - 1) % n
                self.refresh_sel()
            elif keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space) and n:
                self.apply(self.sel)
            else:
                return False
            return True

        def apply(self, i):
            label, key = self.tabs[self.tab][i]
            files, tab, cat = list(self.files), self.tab, self.cat
            self.close()
            self.on_run(cat, tab, key, files)

    class DropWin(Gtk.ApplicationWindow):
        def __init__(self, app):
            super().__init__(application=app, title="Mandarino")
            self.app = app
            self.set_decorated(False)
            self.set_resizable(False)
            self.set_default_size(SIZE, SIZE)
            self.add_css_class("drop")
            follow_theme(self)
            self.busy = False
            self._pulse_id = 0

            handle = Gtk.WindowHandle()
            self.set_child(handle)
            self.handle = handle
            self.box = Gtk.Box()
            self.box.add_css_class("drop-disc")
            self.box.set_halign(Gtk.Align.CENTER)
            self.box.set_valign(Gtk.Align.CENTER)
            self.box.set_tooltip_text("Mandarino · trascina qui i file")
            ov = Gtk.Overlay()
            handle.set_child(ov)
            ov.set_child(self.box)
            self.donut = Donut()
            self.donut.set_visible(False)
            ov.add_overlay(self.donut)
            dot = Gtk.Box()
            dot.add_css_class("drop-dot")
            dot.set_halign(Gtk.Align.CENTER)
            dot.set_valign(Gtk.Align.CENTER)
            dot.set_hexpand(True)
            self.box.append(dot)

            # clic destro: Esci (la WindowHandle altrimenti aprirebbe il menu della finestra)
            menu = Gtk.Popover()
            quit_btn = Gtk.Button(label="Esci")
            quit_btn.add_css_class("flat")
            quit_btn.connect("clicked", lambda _b: app.quit())
            menu.set_child(quit_btn)
            menu.set_parent(self.box)
            right = Gtk.GestureClick(button=3)

            def on_right(g, _n, _x, _y):
                g.set_state(Gtk.EventSequenceState.CLAIMED)
                menu.popup()
            right.connect("pressed", on_right)
            self.box.add_controller(right)

            dt = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
            dt.set_preload(True)   # i file arrivano già durante il trascinamento: servono per le voci
            dt.connect("drop", self.on_drop)
            dt.connect("enter", self.on_enter)
            dt.connect("motion", self.on_motion)
            dt.connect("leave", self.on_leave)
            dt.connect("notify::value", self.on_value)
            self.dt = dt
            self.handle.add_controller(dt)
            self.connect("map", lambda _w: self.catch_all(False))

        def catch_all(self, everything):
            """A riposo la finestra (grande per ospitare la ciambella) intercetta solo il cerchio:
            il resto lascia passare i clic al desktop."""
            surface = self.get_native().get_surface() if self.get_native() else None
            if not surface:
                return
            if everything:
                rect = cairo.RectangleInt(0, 0, SIZE, SIZE)
            else:
                half = 32
                rect = cairo.RectangleInt(SIZE // 2 - half, SIZE // 2 - half, 2 * half, 2 * half)
            surface.set_input_region(cairo.Region(rect))

        def on_value(self, t, _pspec):
            value = t.get_value()
            if value is not None and not self.busy:
                self.donut.set_files([f.get_path() for f in value.get_files() if f.get_path()])

        def on_enter(self, t, _x, _y):
            if self.busy:
                return 0
            self.box.add_css_class("hover")
            self.catch_all(True)
            self.on_value(t, None)
            self.donut.set_visible(True)
            return Gdk.DragAction.COPY

        def on_motion(self, _t, x, y):
            self.donut.move(x, y)
            return 0 if self.busy else Gdk.DragAction.COPY

        def on_leave(self, _t):
            self.close_donut()

        def close_donut(self):
            self.box.remove_css_class("hover")
            self.donut.set_visible(False)
            self.donut.set_files([])
            self.catch_all(False)

        def on_drop(self, _t, value, x, y):
            hit = self.donut.hit(x, y)
            cat, tab, files = self.donut.cat, self.donut.tab, list(self.donut.files)
            items = self.donut.tabs.get(tab, [])
            self.close_donut()
            if self.busy:
                return False
            if hit and hit[0] == "item" and files:
                self.start_job(cat, tab, items[hit[1]][1], files)
                return True
            if hit and hit[0] in ("core", "tab"):   # sul cerchio o sulle schede: ruota classica
                return self.on_drop_paths([f.get_path() for f in value.get_files() if f.get_path()])
            return False

        def on_drop_paths(self, files):
            if not files or self.busy:
                return False
            wheel = Wheel(self.app, files, self.start_job)
            wheel.set_transient_for(self)
            GLib.idle_add(wheel.present)
            return True

        def start_job(self, cat, tab, key, files):
            if tab == "act":
                self.do_action(key, files)
                return
            self.busy = True
            self.set_title("Mandarino · lavoro")  # l'estensione non chiude durante un lavoro
            self.box.add_css_class("busy")
            self._pulse_id = GLib.timeout_add(600, self._pulse)

            def work():
                try:
                    created, skipped = process(cat, tab, key, files)
                    names = "\n".join(os.path.basename(c) for c in created)
                    if skipped and not created:
                        msg = ("Già nel formato scelto", "Nessun file da convertire")
                    else:
                        msg = ("Mandarino: fatto", names or "Nessun file creato")
                except ConvError as e:
                    msg = ("Mandarino: errore", str(e))
                except Exception as e:  # non chiudere mai l'app
                    msg = ("Mandarino: errore", f"{type(e).__name__}: {e}")
                GLib.idle_add(self.job_done, msg)

            threading.Thread(target=work, daemon=True).start()

        def _pulse(self):
            (self.box.remove_css_class if self.box.has_css_class("pulse") else self.box.add_css_class)("pulse")
            return True

        def job_done(self, msg):
            self.busy = False
            self.set_title("Mandarino")
            self.box.remove_css_class("busy")
            self.box.remove_css_class("pulse")
            if self._pulse_id:
                GLib.source_remove(self._pulse_id)
                self._pulse_id = 0
            notify(*msg)
            return False

        def do_action(self, key, files):
            if key == "copy":
                text = "\n".join(files)
                cb = self.get_clipboard()
                try:
                    cb.set(text)
                except Exception:
                    cb.set_content(Gdk.ContentProvider.new_for_value(text))
                notify("Mandarino", "Percorsi copiati")
            elif key == "show":
                subprocess.Popen(["nautilus", "--select", files[0]])
            elif key == "term":
                d = files[0] if os.path.isdir(files[0]) else os.path.dirname(files[0])
                for t, args in (("ptyxis", ["--new-window", "-d", d]),
                                ("gnome-terminal", [f"--working-directory={d}"]),
                                ("kgx", [f"--working-directory={d}"])):
                    if shutil.which(t):
                        subprocess.Popen([t] + args)
                        return
                notify("Mandarino: errore", "Nessun terminale trovato")
            elif key == "trash":
                n = 0
                for f in files:
                    try:
                        Gio.File.new_for_path(f).trash(None)
                        n += 1
                    except GLib.Error as e:
                        notify("Mandarino: errore", f"Cestino: {e.message}")
                if n:
                    notify("Mandarino", f"{n} elementi nel cestino")

    class App(Gtk.Application):
        def __init__(self):
            super().__init__(application_id=APP_ID)

        def do_startup(self):
            Gtk.Application.do_startup(self)
            prov = Gtk.CssProvider()
            prov.load_from_data(CSS)
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        def do_activate(self):
            win = self.props.active_window
            if not win:
                win = DropWin(self)
            win.present()

    return App().run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(run_ui())
