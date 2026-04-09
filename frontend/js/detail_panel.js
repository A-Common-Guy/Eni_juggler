/**
 * Detail panel for viewing and editing a selected slave's properties and PDOs.
 *
 * PDO display: the active PDO (the one with Sm set) is shown prominently and
 * expanded. Inactive alternative mappings are collapsed behind a disclosure
 * to avoid confusion, since only one TxPDO and one RxPDO is active at a time.
 */
const DetailPanel = {
    container: null,
    currentSlave: null,
    activeTab: 'properties',

    init(containerId) {
        this.container = document.getElementById(containerId);
    },

    showEmpty() {
        this.currentSlave = null;
        this.container.innerHTML = `
            <div class="detail-empty">
                <p>Select a slave from the chain to view and edit its properties.</p>
            </div>
        `;
    },

    async showSlave(slave) {
        this.currentSlave = slave;
        this._render();
    },

    _render() {
        const s = this.currentSlave;
        if (!s) return this.showEmpty();

        this.container.innerHTML = `
            <div class="detail-header">
                <h2>${this._esc(s.name)}</h2>
                <div class="detail-actions">
                    <button class="btn btn-sm btn-secondary" id="btnDuplicate">Duplicate</button>
                    <button class="btn btn-sm btn-danger" id="btnRemove">Remove</button>
                </div>
            </div>

            <div class="detail-tabs">
                <button class="detail-tab ${this.activeTab === 'properties' ? 'active' : ''}" data-tab="properties">Properties</button>
                <button class="detail-tab ${this.activeTab === 'pdos' ? 'active' : ''}" data-tab="pdos">PDO Mappings</button>
            </div>

            <div class="tab-content ${this.activeTab === 'properties' ? 'active' : ''}" id="tabProperties">
                <div class="prop-grid">
                    <label class="prop-label">Name</label>
                    <input class="prop-input" data-field="name" value="${this._esc(s.name)}">

                    <label class="prop-label">Vendor ID</label>
                    <input class="prop-input" data-field="vendor_id" type="number" value="${s.vendor_id}">

                    <label class="prop-label">Product Code</label>
                    <input class="prop-input" data-field="product_code" type="number" value="${s.product_code}">

                    <label class="prop-label">Revision No</label>
                    <input class="prop-input" data-field="revision_no" type="number" value="${s.revision_no}">

                    <label class="prop-label">Serial No</label>
                    <input class="prop-input" data-field="serial_no" type="number" value="${s.serial_no}">

                    <label class="prop-label">Physics</label>
                    <input class="prop-input" data-field="physics" value="${this._esc(s.physics)}">

                    <label class="prop-label">Phys Address</label>
                    <input class="prop-input" value="${s.phys_addr}" disabled>

                    <label class="prop-label">Auto Inc Addr</label>
                    <input class="prop-input" value="${s.auto_inc_addr}" disabled>

                    <label class="prop-label">Enabled</label>
                    <input class="prop-input" value="${s.enabled ? 'Yes' : 'No'}" disabled>

                    <label class="prop-label">Tx Bit Length</label>
                    <input class="prop-input" value="${s.tx_bit_length}" disabled>

                    <label class="prop-label">Rx Bit Length</label>
                    <input class="prop-input" value="${s.rx_bit_length}" disabled>
                </div>
            </div>

            <div class="tab-content ${this.activeTab === 'pdos' ? 'active' : ''}" id="tabPdos">
                <div id="pdoContainer"><p style="color:var(--text-dim)">Loading PDO mappings...</p></div>
            </div>
        `;

        this._bindTabs();
        this._bindProperties();
        this._bindActions();

        if (this.activeTab === 'pdos') {
            this._loadPdos();
        }
    },

    _bindTabs() {
        this.container.querySelectorAll('.detail-tab').forEach(tab => {
            tab.addEventListener('click', () => {
                this.activeTab = tab.dataset.tab;
                this.container.querySelectorAll('.detail-tab').forEach(t => t.classList.remove('active'));
                this.container.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                tab.classList.add('active');

                const contentId = {
                    properties: 'tabProperties',
                    pdos: 'tabPdos',
                }[this.activeTab];
                document.getElementById(contentId).classList.add('active');

                if (this.activeTab === 'pdos') {
                    this._loadPdos();
                }
            });
        });
    },

    _bindProperties() {
        let debounce = null;

        this.container.querySelectorAll('.prop-input[data-field]').forEach(input => {
            const original = input.value;

            input.addEventListener('input', () => {
                if (input.value !== original) {
                    input.classList.add('modified');
                } else {
                    input.classList.remove('modified');
                }
            });

            input.addEventListener('change', () => {
                clearTimeout(debounce);
                debounce = setTimeout(() => this._saveProperty(input.dataset.field, input), 300);
            });
        });
    },

    async _saveProperty(field, input) {
        const s = this.currentSlave;
        if (!s) return;

        let value = input.value;
        if (['vendor_id', 'product_code', 'revision_no', 'serial_no'].includes(field)) {
            value = parseInt(value) || 0;
        }

        try {
            const updated = await API.editSlave(s.id, { [field]: value });
            this.currentSlave = { ...this.currentSlave, ...updated };
            input.classList.remove('modified');
            App.toast('Property saved', 'success');
            await App.refreshSlaves();
        } catch (e) {
            App.toast('Failed: ' + e.message, 'error');
        }
    },

    _bindActions() {
        const btnDuplicate = document.getElementById('btnDuplicate');
        const btnRemove = document.getElementById('btnRemove');

        if (btnDuplicate) {
            btnDuplicate.addEventListener('click', async () => {
                try {
                    const newSlave = await API.duplicateSlave(this.currentSlave.id);
                    App.toast(`Duplicated as "${newSlave.name}"`, 'success');
                    await App.refreshSlaves();
                    SlaveList.addSlaveAfter(this.currentSlave.id, newSlave);
                } catch (e) {
                    App.toast('Failed: ' + e.message, 'error');
                }
            });
        }

        if (btnRemove) {
            btnRemove.addEventListener('click', async () => {
                const name = this.currentSlave.name;
                if (!confirm(`Remove slave "${name}" from the chain?`)) return;
                try {
                    await API.removeSlave(this.currentSlave.id);
                    App.toast(`Removed "${name}"`, 'success');
                    await App.refreshSlaves();
                    this.showEmpty();
                } catch (e) {
                    App.toast('Failed: ' + e.message, 'error');
                }
            });
        }
    },

    async _loadPdos() {
        const s = this.currentSlave;
        if (!s) return;

        try {
            const pdoData = await API.getPdos(s.id);
            this._pdoData = pdoData;

            const container = document.getElementById('pdoContainer');
            if (container) {
                PdoEditor.render(container, s.id, pdoData);
            }
        } catch (e) {
            App.toast('Failed to load PDOs: ' + e.message, 'error');
        }
    },

    refreshPdos() {
        if (this.currentSlave && this.activeTab === 'pdos') {
            this._loadPdos();
        }
    },

    _esc(str) {
        if (str == null) return '';
        const div = document.createElement('div');
        div.textContent = String(str);
        return div.innerHTML;
    },
};
