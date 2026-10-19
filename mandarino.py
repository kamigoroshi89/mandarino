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
    from gi.repository import Gdk, Gio, GLib, Gtk

    CSS = b"""
    window.drop { background: transparent; }
    .drop-box { background: #ff8a1f; border-radius: 28px; }
    .drop-box.hover { background: #c45f00; }
    .drop-emoji { font-size: 44px; }
    .drop-text { color: white; font-weight: bold; }
    .close-btn { background: rgba(0,0,0,0.18); color: white; border-radius: 99px;
                 min-width: 22px; min-height: 22px; padding: 0; }
    window.wheel { background: transparent; }
    .wheel-box { background: #fafafa; border-radius: 250px; border: 2px solid #ffd2a0; }
    .wheel-title { font-weight: bold; font-size: 15px; color: #333; }
    .wheel-hint { font-size: 11px; color: #888; }
    .wheel-item { background: #ececec; border-radius: 14px; padding: 4px 8px; color: #222; }
    .wheel-item.sel { background: #ff8a1f; color: white; }
    .wheel-tab { background: transparent; border-radius: 99px; padding: 2px 8px; min-height: 0; color: #555; }
    .wheel-tab.sel { background: #ff8a1f; color: white; }
    """
    TABS = [("conv", "Converti"), ("tool", "Strumenti"), ("act", "Azioni")]
    ACTIONS = [("Copia percorso", "copy"), ("Mostra in File", "show"),
               ("Terminale qui", "term"), ("Cestino", "trash")]

    def notify(title, body):
        if shutil.which("notify-send"):
            subprocess.Popen(["notify-send", "-a", "Mandarino", title, body])

    class Wheel(Gtk.Window):
        def __init__(self, app, files, on_run):
            super().__init__(application=app)
            self.files, self.on_run = files, on_run
            self.cat = category(files[0])
            if self.cat != "dir":
                files[:] = [f for f in files if category(f) == self.cat]
            self.set_decorated(False)
            self.set_modal(True)
            self.set_resizable(False)
            self.set_default_size(500, 500)
            self.add_css_class("wheel")
            self.tabs = {
                "conv": convert_items(self.cat, files[0]) if self.cat != "dir" else [],
                "tool": tool_items(self.cat, len(files)) if self.cat != "dir" else [],
                "act": ACTIONS,
            }
            order = ["conv", "tool", "act"]
            self.tab = next((t for t in order if self.tabs[t]), "act")
            if self.cat == "dir":
                self.tab = "act"
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
            self.set_default_size(150, 150)
            self.add_css_class("drop")
            self.busy = False

            handle = Gtk.WindowHandle()
            self.set_child(handle)
            ov = Gtk.Overlay()
            handle.set_child(ov)
            self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            self.box.add_css_class("drop-box")
            self.box.set_valign(Gtk.Align.FILL)
            self.box.set_halign(Gtk.Align.FILL)
            ov.set_child(self.box)
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            inner.set_valign(Gtk.Align.CENTER)
            inner.set_vexpand(True)
            self.box.append(inner)
            emoji = Gtk.Label(label="🍊")
            emoji.add_css_class("drop-emoji")
            inner.append(emoji)
            self.text = Gtk.Label(label="Trascina qui")
            self.text.add_css_class("drop-text")
            inner.append(self.text)

            close = Gtk.Button(label="×")
            close.add_css_class("close-btn")
            close.add_css_class("flat")
            close.set_halign(Gtk.Align.END)
            close.set_valign(Gtk.Align.START)
            close.set_margin_top(8)
            close.set_margin_end(8)
            close.connect("clicked", lambda _b: app.quit())
            ov.add_overlay(close)

            dt = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
            dt.connect("drop", self.on_drop)
            dt.connect("enter", self.on_enter)
            dt.connect("leave", self.on_leave)
            self.box.add_controller(dt)

        def on_enter(self, _t, _x, _y):
            self.box.add_css_class("hover")
            return Gdk.DragAction.COPY

        def on_leave(self, _t):
            self.box.remove_css_class("hover")

        def on_drop(self, _t, value, _x, _y):
            self.box.remove_css_class("hover")
            return self.on_drop_paths([f.get_path() for f in value.get_files() if f.get_path()])

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
            self.text.set_label("Lavoro…")

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

        def job_done(self, msg):
            self.busy = False
            self.set_title("Mandarino")
            self.text.set_label("Trascina qui")
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
