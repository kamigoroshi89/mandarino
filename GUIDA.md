# Progetto: Mandarino – convertitore di file offline per Ubuntu

## Obiettivo
Crea un'app desktop per Ubuntu ispirata a Tangerine (https://tangerineformac.com/), un convertitore di file per Mac.
L'utente trascina uno o più file su una piccola zona sempre visibile. Si apre una ruota con tre sezioni:
- **Converti** (tasto Shift): cambia formato.
- **Strumenti** (tasto Ctrl): comprimi, ruota, dividi, unisci…
- **Azioni** (tasto Alt): operazioni sui file.

Tutto gira in locale, senza upload. I risultati vanno salvati accanto al file originale e non devono mai sovrascrivere nulla: se il nome esiste già, usa `nome (1).ext`, `nome (2).ext` e così via.

Se nella cartella di lavoro esiste già `mandarino.py`, partì da quello: è una prima versione non ancora testata. Altrimenti scrivilo da zero.

## Ambiente
- Ubuntu 24.04 o 26.04, sessione **Wayland**, GNOME.
- Uso personale: nessun pacchetto .deb, Flatpak o Snap.
- Linguaggio: **Python 3 + GTK4 (PyGObject)**, in un unico file: `~/.local/bin/mandarino.py`.
- Lo strumento di ogni conversione è un programma esterno chiamato con `subprocess`, mai tramite shell.

## Regole per l'agente
- Chiedi conferma prima di eseguire comandi con `sudo` e prima di eliminare o spostare file dell'utente.
- Lavora solo in una cartella di test (es. `~/mandarino-test/`) quando provi le funzioni.
- Alla fine, scrivi un breve resoconto: cosa funziona, cosa non funziona, cosa hai dovuto cambiare rispetto a questo documento.

## Dipendenze
```bash
sudo apt install python3-gi gir1.2-gtk-4.0 python3-pil imagemagick libheif-examples \
  poppler-utils ghostscript qpdf pandoc libreoffice-writer libnotify-bin
```
Verifica che ogni comando esista (`which`). Se un pacchetto ha un nome diverso sulla versione di Ubuntu in uso, trova quello corretto.

## Interfaccia

### Zona di rilascio
- Finestra piccola (circa 150×150), senza decorazioni, arancione (#ff8a1f), angoli arrotondati, con un'emoji 🍊 e la scritta "Trascina qui".
- Spostabile trascinandola: usa `Gtk.WindowHandle`. Il clic destro deve mostrare il menu finestra di GNOME, così l'utente può scegliere "Sempre in primo piano".
- Ha un piccolo pulsante × per chiudere l'app.
- Accetta file e cartelle con `Gtk.DropTarget` di tipo `Gdk.FileList` e azione COPY: il file originale non va mai spostato.
- Si scurisce mentre ci passa sopra un file. Durante un lavoro mostra "Lavoro…".
- Istanza unica: se l'app è già aperta, rilanciarla porta in primo piano la finestra esistente.

### Ruota
- Si apre dopo il rilascio, in una finestra modale circolare di circa 500×500, chiara, senza decorazioni.
- Al centro mostra: il nome del file (o "N elementi"), tre schede (Converti / Strumenti / Azioni) e un suggerimento con i tasti.
- Le voci sono pulsanti disposti in cerchio. Quella selezionata è evidenziata in arancione.
- Tastiera: Shift, Ctrl e Alt cambiano scheda; frecce per scegliere; Invio o Spazio per applicare; Esc per chiudere.
- Mouse: clic su schede e voci. Tutto deve funzionare anche solo con il mouse.
- Si apre sulla prima scheda che ha voci (per una cartella: Azioni).
- Le voci non devono sovrapporsi al blocco centrale, anche con 8 voci.

### Esecuzione
- Le conversioni girano in un thread separato, senza bloccare l'interfaccia. Aggiorna la UI solo con `GLib.idle_add`.
- Ogni file lavora in una cartella temporanea propria. Alla fine i risultati vengono spostati accanto all'originale.
- A lavoro finito, mostra una notifica con `notify-send`: elenco dei file creati, oppure un messaggio d'errore chiaro (es. "Programma mancante: pandoc").
- Con più file trascinati insieme, si usano quelli della stessa categoria del primo. Quelli già nel formato scelto vengono saltati.

## Funzioni

### Immagini
Formati di ingresso: JPG/JPEG, PNG, WebP, TIFF/TIF, BMP, GIF, e HEIC/HEIF/AVIF solo in ingresso.

**Converti in:** PNG, JPG, WebP, TIFF, BMP, GIF, PDF.
- HEIC/HEIF/AVIF vanno prima convertiti in PNG con `heif-convert`.
- Usa ImageMagick (`magick` se esiste, altrimenti `convert`).
- Per JPG e BMP, appiattisci la trasparenza su sfondo bianco.
- Da GIF verso un formato non-GIF, usa solo il primo frame.
- **Verso PDF usa Pillow, non ImageMagick**: la policy di Ubuntu blocca la scrittura di PDF da ImageMagick.

**Strumenti:**
- Comprimi: rimuove i metadati, qualità 75, suffisso `-compresso`. Da HEIC produce un JPG.
- Riduci al 50%: suffisso `-ridotto`.
- Ruota di 90°: suffisso `-ruotato`.
- Togli metadati: suffisso `-pulito`.
- Solo con più immagini: Unisci in PDF, che crea `<primo>-unito.pdf`.

### PDF
**Converti in:**
- DOCX e ODT: LibreOffice con `--infilter=writer_pdf_import`.
- PNG e JPG: `pdftoppm` a 300 DPI, un file per pagina.
- TXT: `pdftotext -layout`.

**Strumenti:**
- Comprimi: Ghostscript, `-dPDFSETTINGS=/ebook`, suffisso `-compresso`.
- Dividi pagine: `qpdf --split-pages`, file `-pagina-N`.
- Ruota di 90°: `qpdf --rotate=+90`, suffisso `-ruotato`.
- Solo con più PDF: Unisci, con `qpdf --empty --pages … --`.
- Nota: `qpdf` restituisce il codice 3 quando ci sono solo avvisi. Va considerato un successo.

### Documenti
Formati di ingresso: DOC, DOCX, ODT, RTF, TXT, Markdown (.md/.markdown), EPUB, HTML (.html/.htm).

**Converti in:** PDF, DOCX, ODT, Markdown, HTML, EPUB, RTF, TXT.
- Se il file d'origine è DOC, DOCX, ODT, RTF o TXT e il formato di destinazione è PDF, DOCX, ODT, RTF, TXT o HTML: usa direttamente LibreOffice headless.
- Altrimenti usa pandoc. Se pandoc non sa leggere l'origine (DOC, RTF, TXT), converti prima in DOCX con LibreOffice.
- Verso PDF, RTF e TXT da sorgenti pandoc: pandoc → DOCX → LibreOffice. **Non usare LaTeX.**
- Markdown in uscita: `-t gfm`. HTML in uscita: standalone, con immagini incorporate.
- LibreOffice va sempre lanciato con un profilo separato (`-env:UserInstallation=file:///tmp/mandarino-lo`). Altrimenti fallisce in silenzio se l'utente ha LibreOffice aperto. Controlla sempre che il file di uscita esista davvero.

**Strumenti:** nessuno per ora. Mostra "Niente da fare qui".

### Azioni (valide per qualunque file e anche per le cartelle)
- **Copia percorso:** copia i percorsi negli appunti di GTK, uno per riga.
- **Mostra in File:** `nautilus --select <file>`.
- **Terminale qui:** prova nell'ordine `ptyxis`, `gnome-terminal`, `kgx`, aprendo la cartella del file.
- **Cestino:** sposta nel cestino con `Gio.File.trash`, mai cancellazione definitiva.

## Vincoli di Wayland (da rispettare, non da aggirare)
- L'app non può scegliere la propria posizione né mettersi in primo piano da sola. Non tentare hack con X11.
- Non si possono intercettare tasti o trascinamenti globali: la ruota si apre **dopo** il rilascio.
- GNOME potrebbe non dare il focus della tastiera alla ruota. Verifica se succede. Se sì, prova soluzioni pulite (es. `present()` dopo il rilascio) e documenta il comportamento. Il mouse deve comunque bastare.

## Punti da verificare con attenzione
Questi punti sono incerti nella prima versione:
1. `Gdk.Clipboard.set(str)` in PyGObject: se non funziona, usa `Gdk.ContentProvider`.
2. Le opzioni di riga di comando di `ptyxis` per la cartella di lavoro.
3. L'uso di `--embed-resources` con la versione di pandoc installata.
4. Il supporto WebP in ImageMagick e la presenza di `heif-convert`.
5. Il CSS: sfondo trasparente delle finestre, angoli arrotondati, nessun avviso di parsing nel terminale.
6. Il programma non deve stampare warning GTK al lancio.

## Installazione finale
1. Copia lo script in `~/.local/bin/mandarino.py` e rendilo eseguibile.
2. Crea `~/.local/share/applications/mandarino.desktop` con `Exec=python3 /percorso/assoluto/mandarino.py`. Usa il percorso assoluto: `~` non viene espanso nei file .desktop.
3. Copia lo stesso .desktop in `~/.config/autostart/` per l'avvio all'accesso.

## Test di accettazione
Crea in `~/mandarino-test/` file d'esempio generati da te:
- un PNG con trasparenza;
- un JPG;
- una GIF animata;
- un PDF di 3 pagine;
- un DOCX;
- un file Markdown con titolo, elenco e un'immagine;
- un TXT.

Poi verifica, senza interfaccia, chiamando direttamente le funzioni di conversione:
- ogni conversione elencata sopra produce un file valido e non vuoto. Per i PDF, controlla con `pdfinfo`; per le immagini, con `identify`;
- PNG → JPG ha lo sfondo bianco, non nero;
- PDF → PNG produce 3 immagini; Dividi pagine produce 3 PDF;
- convertire due volte lo stesso file crea `nome (1).ext` e non sovrascrive;
- con LibreOffice aperto, le conversioni dei documenti funzionano lo stesso;
- se manca un programma, l'errore è leggibile e l'app non si chiude.

Infine avvia l'interfaccia e conferma che si apre senza errori. Poi chiedi all'utente di provare a mano il trascinamento, i tasti e il clic destro "Sempre in primo piano": su Wayland non puoi simularli tu in modo affidabile.

## Consegna
- `~/.local/bin/mandarino.py`, funzionante.
- I due file `.desktop`.
- Un `README.md` breve, nella cartella del progetto: cosa fa, come si usa, scorciatoie da tastiera, limiti noti.
- Il resoconto finale descritto in "Regole per l'agente".
