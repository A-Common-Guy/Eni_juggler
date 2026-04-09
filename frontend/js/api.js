/**
 * API client for communicating with the ENI Juggler backend.
 */
const API = {
    BASE: '/api',

    async _fetch(path, opts = {}) {
        const url = this.BASE + path;
        const res = await fetch(url, {
            headers: { 'Content-Type': 'application/json', ...opts.headers },
            ...opts,
        });
        if (!res.ok) {
            const body = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(body.detail || `HTTP ${res.status}`);
        }
        return res;
    },

    async getFiles() {
        const res = await this._fetch('/files');
        return res.json();
    },

    async uploadFile(file) {
        const form = new FormData();
        form.append('file', file);
        const res = await fetch(this.BASE + '/upload', { method: 'POST', body: form });
        if (!res.ok) {
            const body = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(body.detail || `HTTP ${res.status}`);
        }
        return res.json();
    },

    async parseFile(filename) {
        const res = await this._fetch(`/parse/${encodeURIComponent(filename)}`, { method: 'POST' });
        return res.json();
    },

    async getSlaves() {
        const res = await this._fetch('/slaves');
        return res.json();
    },

    async reorderSlaves(slaveIds) {
        const res = await this._fetch('/slaves/reorder', {
            method: 'PUT',
            body: JSON.stringify({ slave_ids: slaveIds }),
        });
        return res.json();
    },

    async removeSlave(slaveId) {
        const res = await this._fetch(`/slaves/${slaveId}`, { method: 'DELETE' });
        return res.json();
    },

    async toggleSlave(slaveId, enabled) {
        const res = await this._fetch(`/slaves/${slaveId}/toggle`, {
            method: 'PUT',
            body: JSON.stringify({ enabled }),
        });
        return res.json();
    },

    async editSlave(slaveId, data) {
        const res = await this._fetch(`/slaves/${slaveId}`, {
            method: 'PUT',
            body: JSON.stringify(data),
        });
        return res.json();
    },

    async getPdos(slaveId) {
        const res = await this._fetch(`/slaves/${slaveId}/pdos`);
        return res.json();
    },

    async editPdoEntry(slaveId, pdoType, pdoIdx, entryIdx, data) {
        const res = await this._fetch(
            `/slaves/${slaveId}/pdos/${pdoType}/${pdoIdx}/entries/${entryIdx}`,
            { method: 'PUT', body: JSON.stringify(data) }
        );
        return res.json();
    },

    async addPdoEntry(slaveId, pdoType, pdoIdx, data = {}) {
        const res = await this._fetch(
            `/slaves/${slaveId}/pdos/${pdoType}/${pdoIdx}/entries`,
            { method: 'POST', body: JSON.stringify(data) }
        );
        return res.json();
    },

    async removePdoEntry(slaveId, pdoType, pdoIdx, entryIdx) {
        const res = await this._fetch(
            `/slaves/${slaveId}/pdos/${pdoType}/${pdoIdx}/entries/${entryIdx}`,
            { method: 'DELETE' }
        );
        return res.json();
    },

    async setActivePdo(slaveId, pdoType, pdoIdx) {
        const res = await this._fetch(
            `/slaves/${slaveId}/pdos/${pdoType}/active`,
            { method: 'PUT', body: JSON.stringify({ pdo_idx: pdoIdx }) }
        );
        return res.json();
    },

    async duplicateSlave(slaveId) {
        const res = await this._fetch(`/slaves/${slaveId}/duplicate`, { method: 'POST' });
        return res.json();
    },

    async exportConfig(filename) {
        const res = await this._fetch('/export', {
            method: 'POST',
            body: JSON.stringify({ filename }),
        });
        return res;
    },

    async saveConfig(filename) {
        const res = await this._fetch('/save', {
            method: 'POST',
            body: JSON.stringify({ filename }),
        });
        return res.json();
    },

    async getOperations() {
        const res = await this._fetch('/operations');
        return res.json();
    },

    async aiStatus() {
        const res = await this._fetch('/ai/status');
        return res.json();
    },

    async aiChat(message) {
        const res = await this._fetch('/ai/chat', {
            method: 'POST',
            body: JSON.stringify({ message }),
        });
        return res.json();
    },

    async aiClear() {
        const res = await this._fetch('/ai/clear', { method: 'POST' });
        return res.json();
    },

    async getSettings() {
        const res = await this._fetch('/settings');
        return res.json();
    },

    async saveSettings(data) {
        const res = await this._fetch('/settings', {
            method: 'POST',
            body: JSON.stringify(data),
        });
        return res.json();
    },
};
