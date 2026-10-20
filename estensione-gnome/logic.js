import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

const TITLE = 'Mandarino';        // titolo della finestra principale; "Mandarino · lavoro" durante una conversione
const OFFSET = 110;               // distanza del cerchio dal puntatore, in pixel logici
const IDLE_MS = 1500;             // quiete richiesta prima di chiudere
const SHOW_MS = 10;               // il cerchio compare questo tempo dopo l'inizio del trascinamento
const FADE_MS = 60;               // durata della dissolvenza d'ingresso
const APP_ID = 'it.mandarino.App';
const SCRIPT = GLib.build_filenamev([GLib.get_home_dir(), '.local', 'bin', 'mandarino.py']);

export class Logic {
    enable() {
        this._dragging = false;
        this._spawning = false;
        this._raiseTimer = 0;
        this._closeTimer = 0;
        this._revealTimer = 0;
        this._dragStart = 0;
        const h = Main.xdndHandler;
        if (!h) {
            console.error('[mandarino-drop] Main.xdndHandler non disponibile');
            return;
        }
        this._ids = [
            h.connect('drag-begin', () => this._begin()),
            h.connect('drag-end', () => this._end()),
        ];
        this._created = global.display.connect('window-created', (_d, w) => this._onCreated(w));
        console.log('[mandarino-drop] attiva');
    }

    disable() {
        for (const id of this._ids ?? [])
            Main.xdndHandler.disconnect(id);
        this._ids = [];
        if (this._created) {
            global.display.disconnect(this._created);
            this._created = 0;
        }
        this._stopRaise();
        this._cancelClose();
        this._cancelReveal();
    }

    // ───────── Finestre ─────────

    _isApp(w) {
        return [w.get_gtk_application_id?.(), w.get_wm_class(), w.get_wm_class_instance()]
            .some(v => v && v.toLowerCase().includes('mandarino'));
    }

    _windows() {
        return global.get_window_actors().map(a => a.meta_window).filter(w => this._isApp(w));
    }

    _main() {
        return this._windows().find(w => (w.get_title() ?? '').startsWith(TITLE)) ?? null;
    }

    // la ruota (o altre finestre di Mandarino) aperta
    _others() {
        return this._windows().filter(w => !(w.get_title() ?? '').startsWith(TITLE));
    }

    // porta davvero la finestra in cima: stato, ordine di Mutter e ordine di Clutter
    _toTop(w) {
        w.stick();
        w.make_above();
        w.raise();
        const actor = w.get_compositor_private();
        const parent = actor?.get_parent();
        if (parent)
            parent.set_child_above_sibling(actor, null);
    }

    // il cerchio sta al centro della finestra: lo mette in diagonale rispetto al puntatore, restando nello schermo
    _target(w) {
        const r = w.get_frame_rect();
        const [px, py] = global.get_pointer();
        const area = Main.layoutManager.getWorkAreaForMonitor(global.display.get_current_monitor());
        const cx = px + (px < area.x + area.width / 2 ? OFFSET : -OFFSET);
        const cy = py + (py < area.y + area.height / 2 ? OFFSET : -OFFSET);
        return {
            x: Math.min(Math.max(cx - r.width / 2, area.x), area.x + area.width - r.width),
            y: Math.min(Math.max(cy - r.height / 2, area.y), area.y + area.height - r.height),
        };
    }

    _place(w, t = this._target(w)) {
        w.move_frame(true, t.x, t.y);
        this._toTop(w);
    }

    // aspetta che la finestra appena creata abbia attore e dimensioni, poi esegue cb
    _whenReady(w, cb) {
        let tries = 0;
        GLib.timeout_add(GLib.PRIORITY_DEFAULT, 10, () => {
            if (w.get_compositor_private() && w.get_frame_rect().width > 0) {
                cb(w);
                return GLib.SOURCE_REMOVE;
            }
            return ++tries < 300 ? GLib.SOURCE_CONTINUE : GLib.SOURCE_REMOVE;
        });
    }

    // Finestra appena avviata da noi per un trascinamento: Mutter la centra alla prima comparsa e annulla
    // il primo spostamento, quindi la posizione (calcolata una volta) viene riapplicata per un attimo.
    _onCreated(w) {
        if (!this._spawning)
            return;   // l'avvio per un trascinamento lo facciamo noi; le altre finestre non ci riguardano
        // alla creazione la classe della finestra non è ancora nota: si controlla quando è pronta
        this._whenReady(w, ready => {
            if (!this._isApp(ready) || !this._spawning)
                return;
            this._spawning = false;
            const t = this._target(ready);
            console.log(`[mandarino-drop] finestra creata, la sposto in ${Math.round(t.x)},${Math.round(t.y)}`);
            this._place(ready, t);
            if (this._dragging) {
                this._conceal(ready);
                this._startRaise();
            }
            for (const ms of [60, 200, 500]) {
                GLib.timeout_add(GLib.PRIORITY_DEFAULT, ms, () => {
                    if (this._main() === ready)
                        this._place(ready, t);
                    return GLib.SOURCE_REMOVE;
                });
            }
        });
    }

    // Il cerchio nasce subito (l'app è residente) ma resta trasparente fino a SHOW_MS dall'inizio del trascinamento.
    _conceal(w) {
        const wait = SHOW_MS - (GLib.get_monotonic_time() - this._dragStart) / 1000;
        const actor = w.get_compositor_private();
        if (!actor || wait <= 0)
            return;
        actor.opacity = 0;
        this._cancelReveal();
        this._revealTimer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, Math.ceil(wait), () => {
            this._revealTimer = 0;
            const cur = this._main()?.get_compositor_private();
            if (cur === actor && this._dragging)
                actor.ease({opacity: 255, duration: FADE_MS});
            return GLib.SOURCE_REMOVE;
        });
    }

    _cancelReveal() {
        if (this._revealTimer) {
            GLib.source_remove(this._revealTimer);
            this._revealTimer = 0;
        }
    }

    // ───────── Trascinamento ─────────

    _begin() {
        this._dragging = true;
        this._dragStart = GLib.get_monotonic_time();
        this._cancelClose();
        const w = this._main();
        console.log(`[mandarino-drop] drag-begin, finestra ${w ? 'trovata' : 'assente (la avvio)'}`);
        if (w) {
            this._place(w);
            this._startRaise();
        } else if (!this._spawning) {
            this._spawning = true;
            GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 5, () => {
                this._spawning = false;
                return GLib.SOURCE_REMOVE;
            });
            this._launch();
        }
    }

    // L'app resta in vita con la finestra nascosta: basta riattivarla via D-Bus (pochi ms).
    // Se non è in esecuzione (prima volta, o chiusa con "Esci") la si avvia.
    _launch() {
        Gio.DBus.session.call(APP_ID, `/${APP_ID.replaceAll('.', '/')}`, 'org.freedesktop.Application', 'Activate',
            new GLib.Variant('(a{sv})', [{}]), null, Gio.DBusCallFlags.NONE, -1, null, (conn, res) => {
                try {
                    conn.call_finish(res);
                } catch (e) {
                    console.log(`[mandarino-drop] app non in esecuzione (${e.message}), la avvio`);
                    this._spawn();
                }
            });
    }

    _spawn() {
        try {
            GLib.spawn_async(null, ['python3', SCRIPT], null, GLib.SpawnFlags.SEARCH_PATH, null);
        } catch (e) {
            console.error(`[mandarino-drop] avvio fallito: ${e.message}`);
            this._spawning = false;
        }
    }

    _end() {
        this._dragging = false;
        this._stopRaise();
        this._scheduleClose();
    }

    _startRaise() {
        if (this._raiseTimer)
            return;
        this._raiseTimer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 100, () => {
            const w = this._main();
            if (w)
                this._toTop(w);
            return GLib.SOURCE_CONTINUE;
        });
    }

    _stopRaise() {
        if (this._raiseTimer) {
            GLib.source_remove(this._raiseTimer);
            this._raiseTimer = 0;
        }
    }

    // ───────── Chiusura a lavoro finito ─────────

    _cancelClose() {
        if (this._closeTimer) {
            GLib.source_remove(this._closeTimer);
            this._closeTimer = 0;
        }
    }

    // Chiude Mandarino dopo IDLE_MS di quiete: né trascinamento, né conversione ("Mandarino · lavoro"), né ruota aperta.
    _scheduleClose() {
        this._cancelClose();
        let idleSince = GLib.get_monotonic_time();
        this._closeTimer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 300, () => {
            const w = this._main();
            if (!w && this._spawning && !this._dragging)
                return GLib.SOURCE_CONTINUE;   // il trascinamento è finito prima che l'app fosse pronta
            if (this._dragging || !w) {
                this._closeTimer = 0;
                return GLib.SOURCE_REMOVE;
            }
            const now = GLib.get_monotonic_time();
            if (w.get_title() !== TITLE || this._others().length > 0)
                idleSince = now;
            if (now - idleSince < IDLE_MS * 1000)
                return GLib.SOURCE_CONTINUE;
            this._closeTimer = 0;
            w.delete(global.get_current_time());
            return GLib.SOURCE_REMOVE;
        });
    }
}
