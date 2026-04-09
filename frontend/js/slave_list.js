/**
 * Slave chain list component with drag-and-drop reordering.
 */
const SlaveList = {
    container: null,
    slaves: [],
    selectedId: null,
    onSelect: null,
    onReorder: null,
    onToggle: null,

    _dragSrcId: null,

    init(containerId, { onSelect, onReorder, onToggle }) {
        this.container = document.getElementById(containerId);
        this.onSelect = onSelect;
        this.onReorder = onReorder;
        this.onToggle = onToggle;
    },

    setSlaves(slaves) {
        this.slaves = slaves;
        this.render();
    },

    updateSlave(updated) {
        const idx = this.slaves.findIndex(s => s.id === updated.id);
        if (idx !== -1) {
            this.slaves[idx] = { ...this.slaves[idx], ...updated };
            this.render();
        }
    },

    removeSlave(slaveId) {
        this.slaves = this.slaves.filter(s => s.id !== slaveId);
        if (this.selectedId === slaveId) {
            this.selectedId = null;
        }
        this.render();
    },

    addSlaveAfter(afterId, newSlave) {
        const idx = this.slaves.findIndex(s => s.id === afterId);
        if (idx !== -1) {
            this.slaves.splice(idx + 1, 0, newSlave);
        } else {
            this.slaves.push(newSlave);
        }
        this.render();
    },

    selectSlave(slaveId) {
        this.selectedId = slaveId;
        this.render();
        if (this.onSelect) {
            const slave = this.slaves.find(s => s.id === slaveId);
            this.onSelect(slave);
        }
    },

    render() {
        if (!this.container) return;

        const countEl = document.getElementById('slaveCount');
        if (countEl) {
            const enabled = this.slaves.filter(s => s.enabled).length;
            countEl.textContent = `${enabled}/${this.slaves.length}`;
        }

        this.container.innerHTML = '';

        this.slaves.forEach((slave, idx) => {
            const el = document.createElement('div');
            el.className = 'slave-item';
            el.dataset.id = slave.id;

            if (slave.id === this.selectedId) el.classList.add('selected');
            if (!slave.enabled) el.classList.add('disabled');

            el.draggable = true;

            const vendorHex = '0x' + slave.vendor_id.toString(16).toUpperCase();
            const productHex = '0x' + slave.product_code.toString(16).toUpperCase();

            el.innerHTML = `
                <span class="slave-drag-handle" title="Drag to reorder">&#x2630;</span>
                <span class="slave-position">${idx + 1}</span>
                <div class="slave-info">
                    <div class="slave-name" title="${this._esc(slave.name)}">${this._esc(slave.name)}</div>
                    <div class="slave-meta">VID:${vendorHex} PID:${productHex} Addr:${slave.phys_addr}</div>
                </div>
                <div class="slave-toggle">
                    <input type="checkbox" ${slave.enabled ? 'checked' : ''} title="Enable/Disable">
                </div>
            `;

            el.addEventListener('click', (e) => {
                if (e.target.type === 'checkbox') return;
                this.selectSlave(slave.id);
            });

            const cb = el.querySelector('input[type="checkbox"]');
            cb.addEventListener('change', () => {
                if (this.onToggle) this.onToggle(slave.id, cb.checked);
            });

            el.addEventListener('dragstart', (e) => this._onDragStart(e, slave.id));
            el.addEventListener('dragover', (e) => this._onDragOver(e, el));
            el.addEventListener('dragleave', () => el.classList.remove('drag-over'));
            el.addEventListener('drop', (e) => this._onDrop(e, el, slave.id));
            el.addEventListener('dragend', () => this._onDragEnd());

            this.container.appendChild(el);
        });
    },

    _onDragStart(e, slaveId) {
        this._dragSrcId = slaveId;
        e.target.classList.add('dragging');
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', slaveId);
    },

    _onDragOver(e, el) {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        el.classList.add('drag-over');
    },

    _onDrop(e, el, targetId) {
        e.preventDefault();
        el.classList.remove('drag-over');

        const srcId = this._dragSrcId;
        if (!srcId || srcId === targetId) return;

        const srcIdx = this.slaves.findIndex(s => s.id === srcId);
        const tgtIdx = this.slaves.findIndex(s => s.id === targetId);
        if (srcIdx === -1 || tgtIdx === -1) return;

        const [moved] = this.slaves.splice(srcIdx, 1);
        this.slaves.splice(tgtIdx, 0, moved);

        this.render();

        if (this.onReorder) {
            this.onReorder(this.slaves.map(s => s.id));
        }
    },

    _onDragEnd() {
        this._dragSrcId = null;
        this.container.querySelectorAll('.slave-item').forEach(el => {
            el.classList.remove('dragging', 'drag-over');
        });
    },

    _esc(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    },
};
