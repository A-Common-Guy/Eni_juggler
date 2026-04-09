/**
 * PDO editor component.
 *
 * Renders PDO mappings with a clear separation between the active mapping
 * (the one actually used in the process data exchange) and the inactive
 * alternatives. Only one TxPDO and one RxPDO can be active at a time.
 *
 * Active PDO: shown expanded with editable entry table.
 * Alternatives: collapsed behind a disclosure, with a "Set Active" button.
 */
const PdoEditor = {
    DATA_TYPES: ['BOOL', 'SINT', 'INT', 'DINT', 'USINT', 'UINT', 'UDINT', 'REAL', 'LREAL', 'STRING'],

    render(container, slaveId, pdoData) {
        container.innerHTML = '';

        const hasAny = pdoData.tx_pdos.length > 0 || pdoData.rx_pdos.length > 0;
        if (!hasAny) {
            container.innerHTML = '<p style="color:var(--text-dim)">No PDO mappings for this slave.</p>';
            return;
        }

        if (pdoData.tx_pdos.length > 0) {
            container.appendChild(this._renderPdoGroup(slaveId, 'tx', 'TxPDO (Slave \u2192 Master)', pdoData.tx_pdos));
        }

        if (pdoData.rx_pdos.length > 0) {
            container.appendChild(this._renderPdoGroup(slaveId, 'rx', 'RxPDO (Master \u2192 Slave)', pdoData.rx_pdos));
        }
    },

    _renderPdoGroup(slaveId, pdoType, title, pdos) {
        const group = document.createElement('div');
        group.className = 'pdo-group';

        const groupHeader = document.createElement('h3');
        groupHeader.className = 'pdo-group-header';
        groupHeader.textContent = title;
        group.appendChild(groupHeader);

        const active = pdos.find(p => p.is_active);
        const alternatives = pdos.filter(p => !p.is_active);

        if (active) {
            group.appendChild(this._renderActivePdo(slaveId, pdoType, active));
        } else if (pdos.length > 0) {
            const note = document.createElement('p');
            note.className = 'pdo-no-active';
            note.textContent = 'No active mapping selected. Choose one from the alternatives below.';
            group.appendChild(note);
        }

        if (alternatives.length > 0) {
            group.appendChild(this._renderAlternatives(slaveId, pdoType, alternatives));
        }

        return group;
    },

    _renderActivePdo(slaveId, pdoType, pdo) {
        const section = document.createElement('div');
        section.className = 'pdo-active-section';

        const header = document.createElement('div');
        header.className = 'pdo-header';
        header.innerHTML = `
            <div class="pdo-header-left">
                <span class="pdo-badge-active">ACTIVE</span>
                <span class="pdo-index">${pdo.index}</span>
                <span class="pdo-name">${this._esc(pdo.name)}</span>
                <span class="pdo-bits">${pdo.total_bit_length} bits</span>
            </div>
            <button class="btn btn-sm btn-secondary pdo-add-btn">+ Add Entry</button>
        `;
        section.appendChild(header);

        header.querySelector('.pdo-add-btn').addEventListener('click', () =>
            this._addEntry(slaveId, pdoType, pdo.arr_idx)
        );

        if (pdo.entries.length === 0) {
            const empty = document.createElement('p');
            empty.className = 'pdo-empty-msg';
            empty.textContent = 'No entries. Click "+ Add Entry" to create one.';
            section.appendChild(empty);
        } else {
            section.appendChild(this._renderEntryTable(slaveId, pdoType, pdo.arr_idx, pdo.entries));
        }

        return section;
    },

    _renderAlternatives(slaveId, pdoType, alternatives) {
        const wrapper = document.createElement('div');
        wrapper.className = 'pdo-alternatives';

        const toggle = document.createElement('button');
        toggle.className = 'pdo-alt-toggle';
        toggle.innerHTML = `
            <span class="pdo-alt-arrow">\u25B6</span>
            ${alternatives.length} alternative mapping${alternatives.length > 1 ? 's' : ''} available
        `;

        const content = document.createElement('div');
        content.className = 'pdo-alt-content';
        content.style.display = 'none';

        toggle.addEventListener('click', () => {
            const visible = content.style.display !== 'none';
            content.style.display = visible ? 'none' : 'block';
            toggle.querySelector('.pdo-alt-arrow').textContent = visible ? '\u25B6' : '\u25BC';
        });

        alternatives.forEach(pdo => {
            content.appendChild(this._renderAltPdo(slaveId, pdoType, pdo));
        });

        wrapper.appendChild(toggle);
        wrapper.appendChild(content);
        return wrapper;
    },

    _renderAltPdo(slaveId, pdoType, pdo) {
        const section = document.createElement('div');
        section.className = 'pdo-alt-section';

        const header = document.createElement('div');
        header.className = 'pdo-header';
        header.innerHTML = `
            <div class="pdo-header-left">
                <span class="pdo-badge-inactive">INACTIVE</span>
                <span class="pdo-index">${pdo.index}</span>
                <span class="pdo-name">${this._esc(pdo.name)}</span>
                <span class="pdo-bits">${pdo.total_bit_length} bits</span>
            </div>
            <button class="btn btn-sm btn-primary pdo-activate-btn">Set Active</button>
        `;
        section.appendChild(header);

        header.querySelector('.pdo-activate-btn').addEventListener('click', () =>
            this._setActive(slaveId, pdoType, pdo.arr_idx)
        );

        if (pdo.entries.length > 0) {
            const preview = document.createElement('div');
            preview.className = 'pdo-alt-preview';
            preview.innerHTML = pdo.entries.map(e =>
                `<span class="pdo-alt-entry">${this._esc(e.name)} <span class="pdo-alt-entry-type">${e.data_type}/${e.bit_len}b</span></span>`
            ).join('');
            section.appendChild(preview);
        }

        return section;
    },

    _renderEntryTable(slaveId, pdoType, pdoIdx, entries) {
        const table = document.createElement('table');
        table.className = 'pdo-table';
        table.innerHTML = `
            <thead>
                <tr>
                    <th style="width:30px">#</th>
                    <th style="width:90px">Index</th>
                    <th style="width:50px">Sub</th>
                    <th style="width:55px">Bits</th>
                    <th style="width:80px">Type</th>
                    <th>Name</th>
                    <th style="width:40px"></th>
                </tr>
            </thead>
            <tbody></tbody>
        `;

        const tbody = table.querySelector('tbody');
        entries.forEach((entry, entryIdx) => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td style="color:var(--text-dim)">${entryIdx + 1}</td>
                <td class="cell-index">
                    <input class="pdo-cell-edit" value="${this._esc(entry.index)}" data-field="index">
                </td>
                <td>
                    <input class="pdo-cell-edit num" value="${this._esc(entry.subindex)}" data-field="subindex">
                </td>
                <td>
                    <input class="pdo-cell-edit num" type="number" value="${entry.bit_len}" data-field="bit_len">
                </td>
                <td class="cell-type">
                    <select class="pdo-cell-edit" data-field="data_type">
                        ${this.DATA_TYPES.map(t =>
                            `<option value="${t}" ${t === entry.data_type ? 'selected' : ''}>${t}</option>`
                        ).join('')}
                        ${!this.DATA_TYPES.includes(entry.data_type) ?
                            `<option value="${entry.data_type}" selected>${entry.data_type}</option>` : ''}
                    </select>
                </td>
                <td>
                    <input class="pdo-cell-edit" value="${this._esc(entry.name)}" data-field="name">
                </td>
                <td class="cell-actions">
                    <button class="btn-icon pdo-del-btn" title="Remove entry">&#x2715;</button>
                </td>
            `;

            tr.querySelectorAll('.pdo-cell-edit').forEach(input => {
                input.addEventListener('change', () => {
                    const field = input.dataset.field;
                    let value = input.value;
                    if (field === 'bit_len') value = parseInt(value) || 0;
                    this._editEntry(slaveId, pdoType, pdoIdx, entryIdx, field, value);
                });
            });

            tr.querySelector('.pdo-del-btn').addEventListener('click', () => {
                this._removeEntry(slaveId, pdoType, pdoIdx, entryIdx);
            });

            tbody.appendChild(tr);
        });

        return table;
    },

    async _setActive(slaveId, pdoType, pdoIdx) {
        try {
            await API.setActivePdo(slaveId, pdoType, pdoIdx);
            App.toast('Active mapping changed', 'success');
            await App.refreshSlaves();
            DetailPanel.refreshPdos();
        } catch (e) {
            App.toast('Failed: ' + e.message, 'error');
        }
    },

    async _editEntry(slaveId, pdoType, pdoIdx, entryIdx, field, value) {
        try {
            await API.editPdoEntry(slaveId, pdoType, pdoIdx, entryIdx, { [field]: value });
            App.toast('Entry updated', 'success');
            await App.refreshSlaves();
            DetailPanel.refreshPdos();
        } catch (e) {
            App.toast('Failed: ' + e.message, 'error');
        }
    },

    async _addEntry(slaveId, pdoType, pdoIdx) {
        try {
            await API.addPdoEntry(slaveId, pdoType, pdoIdx);
            App.toast('Entry added', 'success');
            await App.refreshSlaves();
            DetailPanel.refreshPdos();
        } catch (e) {
            App.toast('Failed: ' + e.message, 'error');
        }
    },

    async _removeEntry(slaveId, pdoType, pdoIdx, entryIdx) {
        try {
            await API.removePdoEntry(slaveId, pdoType, pdoIdx, entryIdx);
            App.toast('Entry removed', 'success');
            await App.refreshSlaves();
            DetailPanel.refreshPdos();
        } catch (e) {
            App.toast('Failed: ' + e.message, 'error');
        }
    },

    _esc(str) {
        if (str == null) return '';
        const div = document.createElement('div');
        div.textContent = String(str);
        return div.innerHTML;
    },
};
