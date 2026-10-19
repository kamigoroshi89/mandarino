# Mandarino 🍊

Convertitore di file offline per Ubuntu (GNOME/Wayland), ispirato a Tangerine per Mac.
Python 3 + GTK4, un solo file: `mandarino.py`. Tutto gira in locale.

## Uso
1. Avvia l'app: compare un quadratino arancione. Si sposta trascinandolo; × per chiudere.
2. Trascina sopra uno o più file (o una cartella): si apre la ruota.
3. Scegli una voce con il mouse, oppure con la tastiera.
4. I risultati compaiono accanto all'originale, mai in sovrascrittura (`nome (1).ext`, …). A fine lavoro arriva una notifica.

Rilanciare l'app quando è già aperta porta in primo piano la finestra esistente.
Per tenerla sempre visibile: clic destro sulla barra/finestra → "Sempre in primo piano".

## Scorciatoie (ruota)
| Tasto | Azione |
|---|---|
| Shift | scheda Converti |
| Ctrl | scheda Strumenti |
| Alt | scheda Azioni |
| Frecce | scegli voce |
| Invio / Spazio | applica |
| Esc | chiudi |

## Funzioni
- **Immagini** (jpg, png, webp, tiff, bmp, gif, heic/heif/avif in ingresso): converti, comprimi, riduci 50%, ruota, togli metadati, unisci in PDF.
- **PDF**: in DOCX/ODT/PNG/JPG/TXT; comprimi, dividi, ruota, unisci.
- **Documenti** (doc, docx, odt, rtf, txt, md, epub, html): in PDF/DOCX/ODT/MD/HTML/EPUB/RTF/TXT.
- **Azioni** (anche per cartelle): copia percorso, mostra in File, terminale qui, cestino.

## Comparsa automatica al trascinamento (estensione GNOME Shell)
`~/.local/share/gnome-shell/extensions/mandarino-drop@local` (copia in `estensione-gnome/`).
Quando inizi a trascinare un file, mostra Mandarino (lo avvia se non è aperto) in basso al centro;
a trascinamento finito lo nasconde, aspettando che la ruota si chiuda. Se Mandarino era già
visibile, non lo tocca. Attivazione: esci e rientra dalla sessione, poi
`gnome-extensions enable mandarino-drop@local`. Log: `journalctl -f -o cat /usr/bin/gnome-shell | grep mandarino-drop`.
Poiché parte con qualunque trascinamento (anche di testo), può comparire anche quando non serve.
L'avvio automatico all'accesso non serve più: l'estensione lo avvia al bisogno.

## Dipendenze
```
sudo apt install python3-gi gir1.2-gtk-4.0 python3-pil imagemagick libheif-examples \
  poppler-utils ghostscript qpdf pandoc libreoffice-writer libnotify-bin
```

## Installazione
Script in `~/.local/bin/mandarino.py`; lanciatore in `~/.local/share/applications/mandarino.desktop`
e copia in `~/.config/autostart/` per l'avvio all'accesso.

## Limiti noti
- Wayland: l'app non sceglie la propria posizione né si mette in primo piano da sola, e non intercetta tasti globali. La ruota si apre dopo il rilascio.
- GNOME può non dare subito il focus tastiera alla ruota: in quel caso basta un clic nella ruota; il mouse funziona sempre.
- HEIC/HEIF/AVIF solo in ingresso. Le GIF animate verso altri formati usano il primo frame.
- PDF → DOCX/ODT dipende da LibreOffice: l'impaginazione può non essere fedele.
- Con più file si usano solo quelli della stessa categoria del primo.
