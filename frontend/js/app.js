/**
 * Main application controller for ENI Juggler.
 * Orchestrates file loading, slave management, and export workflows.
 */
const App = {
    currentFile: null,

    init() {
        SlaveList.init('slaveList', {
            onSelect: (slave) => this._onSlaveSelected(slave),
            onReorder: (ids) => this._onReorder(ids),
            onToggle: (id, enabled) => this._onToggle(id, enabled),
        });

        DetailPanel.init('detailPanel');

        document.getElementById('btnImport').addEventListener('click', () => this.showFilePicker());
        document.getElementById('btnEmptyImport').addEventListener('click', () => this.showFilePicker());

        document.getElementById('btnUpload').addEventListener('click', () => document.getElementById('fileInput').click());
        document.getElementById('btnEmptyUpload').addEventListener('click', () => document.getElementById('fileInput').click());
        document.getElementById('fileInput').addEventListener('change', (e) => this._onFileUpload(e));

        document.getElementById('btnExport').addEventListener('click', () => this.showExportDialog());
        document.getElementById('btnExportFromLog').addEventListener('click', () => this.showExportDialog());
        document.getElementById('btnCancelPicker').addEventListener('click', () => this.hideFilePicker());
        document.getElementById('btnCancelExport').addEventListener('click', () => this.hideExportDialog());
        document.getElementById('btnDownload').addEventListener('click', () => this._doExport());
        document.getElementById('btnSaveServer').addEventListener('click', () => this._doSave());

        ChatPanel.init('chatPanel');
        document.getElementById('btnAiToggle').addEventListener('click', () => ChatPanel.toggle());

        this._ensureToastContainer();
    },

    // ── File Picker ───────────────────────────────────────────

    async showFilePicker() {
        try {
            const files = await API.getFiles();
            const list = document.getElementById('fileList');
            list.innerHTML = '';

            if (files.length === 0) {
                list.innerHTML = '<p style="color:var(--text-dim);padding:16px">No ENI files found in eni_files/</p>';
            } else {
                files.forEach(f => {
                    const item = document.createElement('div');
                    item.className = 'file-list-item';
                    const sizeKB = (f.size / 1024).toFixed(1);
                    item.innerHTML = `
                        <span class="fname">${this._esc(f.name)}</span>
                        <span class="fsize">${sizeKB} KB</span>
                    `;
                    item.addEventListener('click', () => {
                        this.hideFilePicker();
                        this.loadFile(f.name);
                    });
                    list.appendChild(item);
                });
            }

            document.getElementById('filePickerOverlay').classList.add('active');
        } catch (e) {
            this.toast('Failed to load file list: ' + e.message, 'error');
        }
    },

    hideFilePicker() {
        document.getElementById('filePickerOverlay').classList.remove('active');
    },

    async loadFile(filename) {
        try {
            this.toast(`Loading ${filename}...`);
            const result = await API.parseFile(filename);
            this.currentFile = filename;

            document.getElementById('fileInfo').textContent = `${filename} (${result.slave_count} slaves)`;
            document.getElementById('btnExport').disabled = false;
            document.getElementById('emptyState').style.display = 'none';
            document.getElementById('workspace').style.display = 'grid';
            document.getElementById('changeLogBar').style.display = 'flex';

            SlaveList.setSlaves(result.slaves);
            DetailPanel.showEmpty();

            this.toast(`Loaded ${result.slave_count} slaves from ${filename}`, 'success');
        } catch (e) {
            this.toast('Failed to load file: ' + e.message, 'error');
        }
    },

    // ── Upload ────────────────────────────────────────────────

    async _onFileUpload(e) {
        const file = e.target.files[0];
        if (!file) return;
        e.target.value = '';

        try {
            this.toast(`Uploading ${file.name}...`);
            await API.uploadFile(file);
            this.toast(`Uploaded ${file.name}`, 'success');
            await this.loadFile(file.name);
        } catch (err) {
            this.toast('Upload failed: ' + err.message, 'error');
        }
    },

    // ── Export ─────────────────────────────────────────────────

    async showExportDialog() {
        const filenameInput = document.getElementById('exportFilename');
        const base = this.currentFile || 'exported.xml';
        const name = base.replace('.xml', '') + '_modified.xml';
        filenameInput.value = name;

        try {
            const ops = await API.getOperations();
            const summaryEl = document.getElementById('changeSummary');

            const editOps = ops.operations.filter(o => o.op !== 'load_file' && o.op !== 'export_file');
            summaryEl.innerHTML = editOps.length === 0
                ? '<p style="color:var(--text-dim)">No modifications made yet.</p>'
                : editOps.map(o => `<div class="op-item">${this._esc(this.describeOp(o))}</div>`).join('');
        } catch (e) {
            document.getElementById('changeSummary').innerHTML = '<p>Could not load change summary.</p>';
        }

        document.getElementById('exportOverlay').classList.add('active');
    },

    hideExportDialog() {
        document.getElementById('exportOverlay').classList.remove('active');
    },

    async _doExport() {
        const filename = document.getElementById('exportFilename').value.trim() || 'exported.xml';
        this.hideExportDialog();

        try {
            const res = await API.exportConfig(filename);
            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            a.click();
            URL.revokeObjectURL(url);
            this.toast(`Exported as ${filename}`, 'success');
        } catch (e) {
            this.toast('Export failed: ' + e.message, 'error');
        }
    },

    async _doSave() {
        const filename = document.getElementById('exportFilename').value.trim() || 'exported.xml';
        this.hideExportDialog();

        try {
            const result = await API.saveConfig(filename);
            this.toast(`Saved ${result.saved} to server`, 'success');
        } catch (e) {
            this.toast('Save failed: ' + e.message, 'error');
        }
    },

    // ── Slave events ──────────────────────────────────────────

    _onSlaveSelected(slave) {
        if (slave) DetailPanel.showSlave(slave);
    },

    async _onReorder(slaveIds) {
        try {
            const slaves = await API.reorderSlaves(slaveIds);
            SlaveList.setSlaves(slaves);
            this.toast('Reordered', 'success');
        } catch (e) {
            this.toast('Reorder failed: ' + e.message, 'error');
            await this.refreshSlaves();
        }
    },

    async _onToggle(slaveId, enabled) {
        try {
            const updated = await API.toggleSlave(slaveId, enabled);
            SlaveList.updateSlave(updated);
            this.toast(`${updated.name} ${enabled ? 'enabled' : 'disabled'}`, 'success');
            await this.refreshSlaves();
        } catch (e) {
            this.toast('Toggle failed: ' + e.message, 'error');
            await this.refreshSlaves();
        }
    },

    async refreshSlaves() {
        try {
            const slaves = await API.getSlaves();
            SlaveList.setSlaves(slaves);
            const enabled = slaves.filter(s => s.enabled).length;
            document.getElementById('fileInfo').textContent =
                `${this.currentFile} (${enabled}/${slaves.length} slaves)`;

            // Refresh detail panel if a slave is currently shown
            if (DetailPanel.currentSlave) {
                const fresh = slaves.find(s => s.id === DetailPanel.currentSlave.id);
                if (fresh) {
                    await DetailPanel.showSlave(fresh);
                } else {
                    DetailPanel.showEmpty();
                }
            }

            await this.refreshLog();
        } catch (e) {
            console.error('Failed to refresh:', e);
        }
    },

    // ── Toast notifications ───────────────────────────────────

    _ensureToastContainer() {
        if (!document.querySelector('.toast-container')) {
            const container = document.createElement('div');
            container.className = 'toast-container';
            document.body.appendChild(container);
        }
    },

    toast(message, type = '') {
        const container = document.querySelector('.toast-container');
        const el = document.createElement('div');
        el.className = `toast ${type}`;
        el.textContent = message;
        container.appendChild(el);
        setTimeout(() => {
            el.style.opacity = '0';
            el.style.transition = 'opacity 0.3s';
            setTimeout(() => el.remove(), 300);
        }, 3000);
    },

    describeOp(o) {
        const d = o.details;
        switch (o.op) {
            case 'remove_slave':      return `Removed slave "${d.name}"`;
            case 'toggle_slave':      return `${d.enabled ? 'Enabled' : 'Disabled'} slave "${d.name}"`;
            case 'reorder':           return `Reordered slave chain`;
            case 'duplicate_slave':   return `Duplicated "${d.slave_name}"`;
            case 'edit_slave_info':   return `"${d.slave_name || d.slave_id}" — ${d.field}: ${d.old} → ${d.new}`;
            case 'edit_pdo_entry':    return `"${d.slave_name}" — ${d.entry_name} (${d.pdo_index}): ${d.field} ${d.old} → ${d.new}`;
            case 'add_pdo_entry':     return `"${d.slave_name}" — added "${d.entry_name}" to ${d.pdo_index}`;
            case 'remove_pdo_entry':  return `"${d.slave_name}" — removed "${d.entry_name}" from ${d.pdo_index}`;
            default:                  return o.op;
        }
    },

    async refreshLog() {
        const logEl = document.getElementById('changeLog');
        if (!logEl) return;
        try {
            const ops = await API.getOperations();
            const editOps = ops.operations.filter(o => o.op !== 'load_file' && o.op !== 'export_file');
            if (editOps.length === 0) {
                logEl.innerHTML = '<p class="log-empty">No changes yet.</p>';
            } else {
                logEl.innerHTML = editOps.map(o =>
                    `<div class="log-item">${this._esc(this.describeOp(o))}</div>`
                ).join('');
                logEl.scrollTop = logEl.scrollHeight;
            }
        } catch { /* ignore */ }
    },

    _esc(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    },
};

document.addEventListener('DOMContentLoaded', () => App.init());
