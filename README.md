# Mandarino 🍊

Convertitore di file offline per Ubuntu (GNOME/Wayland), ispirato a Tangerine per Mac.
Python 3 + GTK4, un solo file: `mandarino.py`. Tutto gira in locale.

## Uso
1. Avvia l'app: compare un cerchio traslucido. Si sposta trascinandolo; clic destro → Esci.
2. Trascina uno o più file (o una cartella) sul cerchio: intorno si apre la ciambella. L'anello interno ha le schede
   (Converti, Strumenti, Azioni): passaci sopra per cambiare le voci dell'anello esterno.
3. Rilascia il file sullo spicchio della voce scelta. Se lo rilasci sul cerchio o sulle schede si apre la ruota classica
   (mouse o tastiera).
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
`estensione-gnome/` (da copiare in `~/.local/share/gnome-shell/extensions/mandarino-drop@local`).
Quando inizi a trascinare un file l'estensione avvia Mandarino (se non è già aperto) e mette il cerchio in diagonale
rispetto al puntatore, sempre in primo piano. A trascinamento finito lo chiude, ma solo quando non c'è più nulla da
fare: aspetta che finisca la conversione ("Mandarino · lavoro" nel titolo) e che si chiuda la ruota.
Attivazione: esci e rientra dalla sessione, poi `gnome-extensions enable mandarino-drop@local`.
Dopo una modifica a `logic.js` basta `gnome-extensions disable` + `enable`.
Log: `journalctl --user -f -o cat /usr/bin/gnome-shell | grep mandarino-drop`.
Poiché parte con qualunque trascinamento (anche di testo), può comparire anche quando non serve.
L'avvio automatico all'accesso non serve: l'estensione avvia l'app al bisogno.

## Dipendenze
```
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 python3-pil imagemagick libheif-examples \
  poppler-utils ghostscript qpdf pandoc libreoffice-writer libnotify-bin
```

## Installazione
Script in `~/.local/bin/mandarino.py` (l'estensione lo avvia da lì); lanciatore in
`~/.local/share/applications/mandarino.desktop`.

## Limiti noti
- Wayland: l'app non sceglie la propria posizione né si mette in primo piano da sola, e non intercetta tasti globali. La ruota si apre dopo il rilascio.
- GNOME può non dare subito il focus tastiera alla ruota: in quel caso basta un clic nella ruota; il mouse funziona sempre.
- HEIC/HEIF/AVIF solo in ingresso. Le GIF animate verso altri formati usano il primo frame.
- PDF → DOCX/ODT dipende da LibreOffice: l'impaginazione può non essere fedele.
- Con più file si usano solo quelli della stessa categoria del primo.
