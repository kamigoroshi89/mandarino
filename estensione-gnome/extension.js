import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

// Carica la logica da logic.js con un parametro nuovo a ogni abilitazione:
// per applicare una modifica basta `gnome-extensions disable` + `enable`, senza riaccedere.
export default class MandarinoDrop extends Extension {
    enable() {
        this._logic = null;
        this._disabled = false;
        const token = Date.now();
        import(`${this.dir.get_uri()}/logic.js?v=${token}`).then(m => {
            if (this._disabled)
                return;
            this._logic = new m.Logic();
            this._logic.enable();
        }).catch(e => console.error(`[mandarino-drop] caricamento fallito: ${e.message}\n${e.stack}`));
    }

    disable() {
        this._disabled = true;
        this._logic?.disable();
        this._logic = null;
    }
}
