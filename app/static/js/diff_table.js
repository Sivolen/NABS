diffview = {
    buildView: function (params) {
        var baseTextLines = params.baseTextLines;
        var newTextLines = params.newTextLines;
        var opcodes = params.opcodes;
        var baseTextName = params.baseTextName ? params.baseTextName : "Base Text";
        var newTextName = params.newTextName ? params.newTextName : "New Text";
        var contextSize = params.contextSize;
        var inline = params.viewType == 0 || params.viewType >= 1 ? params.viewType : 0;
        var wordlevel = params.viewType > 1;

        if (baseTextLines == null) throw "Cannot build diff view; baseTextLines is not defined.";
        if (newTextLines == null) throw "Cannot build diff view; newTextLines is not defined.";
        if (!opcodes) throw "Cannot build diff view; opcodes is not defined.";

        // ----- Вспомогательные функции -----
        function celt(name, clazz) {
            var e = document.createElement(name);
            e.className = clazz;
            e.setAttribute("id", "diff_table");
            return e;
        }
        function telt(name, text) {
            var e = document.createElement(name);
            e.appendChild(document.createTextNode(text));
            return e;
        }
        function ctelt(name, clazz, text) {
            var e = document.createElement(name);
            e.className = clazz;
            e.appendChild(document.createTextNode(text));
            return e;
        }
        function ctel(name, clazz, node) {
            var e = document.createElement(name);
            e.className = clazz;
            e.appendChild(node);
            return e;
        }

        // ----- Функции для копирования (с fallback) -----
        function fallbackCopy(text, btn) {
            var textarea = document.createElement('textarea');
            textarea.value = text;
            document.body.appendChild(textarea);
            textarea.select();
            var success = false;
            try {
                success = document.execCommand('copy');
            } catch (err) {
                console.error('Fallback copy failed:', err);
            }
            document.body.removeChild(textarea);
            if (success) {
                showSuccess(btn);
            } else {
                btn.classList.add('btn-outline-danger');
                setTimeout(function() {
                    btn.classList.remove('btn-outline-danger');
                }, 2000);
            }
        }

        function showSuccess(btn) {
            var originalHtml = btn.innerHTML;
            btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" fill="currentColor" class="bi bi-check-lg" viewBox="0 0 16 16"><path d="M12.736 3.97a.733.733 0 0 1 1.047 0c.286.289.29.756.01 1.05L7.88 12.01a.733.733 0 0 1-1.065.02L3.217 8.384a.757.757 0 0 1 0-1.06.733.733 0 0 1 1.047 0l3.052 3.093 5.4-6.425a.247.247 0 0 1 .02-.022Z"/></svg>';
            btn.classList.add('btn-success');
            setTimeout(function() {
                btn.innerHTML = originalHtml;
                btn.classList.remove('btn-success');
            }, 2000);
        }

        function setupCopyButton(btn, configType) {
            btn.onclick = function(e) {
                e.stopPropagation();
                var textarea = document.getElementById(configType === 'prev' ? 'previousConfig' : 'lastConfig');
                if (!textarea) return;
                var text = textarea.value;
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(text).then(function() {
                        showSuccess(btn);
                    }).catch(function(err) {
                        console.error('Clipboard write failed:', err);
                        fallbackCopy(text, btn);
                    });
                } else {
                    fallbackCopy(text, btn);
                }
            };
        }

        function createCopyButton(configType, title) {
            var btn = document.createElement('button');
            btn.className = 'btn btn-sm btn-outline-secondary ms-2 copy-diff-btn';
            btn.title = title;
            btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" fill="currentColor" class="bi bi-clipboard" viewBox="0 0 16 16"><path d="M4 1.5H3a2 2 0 0 0-2 2V14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V3.5a2 2 0 0 0-2-2h-1v1h1a1 1 0 0 1 1 1V14a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3.5a1 1 0 0 1 1-1h1v-1z"/><path d="M9.5 1a.5.5 0 0 1 .5.5v1a.5.5 0 0 1-.5.5h-3a.5.5 0 0 1-.5-.5v-1a.5.5 0 0 1 .5-.5h3zm-3-1A1.5 1.5 0 0 0 5 1.5v1A1.5 1.5 0 0 0 6.5 4h3A1.5 1.5 0 0 0 11 2.5v-1A1.5 1.5 0 0 0 9.5 0h-3z"/></svg>';
            setupCopyButton(btn, configType);
            return btn;
        }

        // ----- Создание заголовка таблицы с обёрткой для выравнивания -----
        var tdata = document.createElement("thead");
        var tr = document.createElement("tr");
        tdata.appendChild(tr);

        // Функция создания ячейки с обёрткой (текст слева, кнопка справа)
        function createAlignedHeaderCell(text, button) {
            var th = document.createElement("th");
            if (inline) th.className = "row";
            else th.className = "col";
            var wrapper = document.createElement("div");
            wrapper.style.display = "flex";
            wrapper.style.justifyContent = "space-between";
            wrapper.style.alignItems = "center";
            wrapper.style.width = "100%";
            wrapper.appendChild(document.createTextNode(text));
            if (button) wrapper.appendChild(button);
            th.appendChild(wrapper);
            return th;
        }

        if (inline) {
            // Пустые ячейки для номеров строк
            tr.appendChild(document.createElement("th"));
            tr.appendChild(document.createElement("th"));
            // Основная ячейка с названиями и двумя кнопками
            var btnGroup = document.createElement('span');
            btnGroup.className = 'copy-buttons-group ms-2';
            btnGroup.appendChild(createCopyButton('prev', 'Copy previous config'));
            btnGroup.appendChild(createCopyButton('last', 'Copy last config'));
            var titleCell = createAlignedHeaderCell(baseTextName + " vs. " + newTextName, btnGroup);
            tr.appendChild(titleCell);
        } else {
            // Пустая ячейка для номеров строк
            tr.appendChild(document.createElement("th"));
            // Ячейка "Previous config" с кнопкой
            var prevCell = createAlignedHeaderCell(baseTextName, createCopyButton('prev', 'Copy previous config'));
            tr.appendChild(prevCell);
            // Пустая разделительная ячейка
            tr.appendChild(document.createElement("th"));
            // Ячейка "Last config" с кнопкой
            var lastCell = createAlignedHeaderCell(newTextName, createCopyButton('last', 'Copy last config'));
            tr.appendChild(lastCell);
        }
        tdata = [tdata];

        // ----- Генерация строк таблицы (оригинальный код, без изменений) -----
        var rows = [];
        var node2;

        function addCells(row, tidx, tend, textLines, change) {
            if (!textLines[tidx]) {
                row.appendChild(telt("th", (tidx + 1).toString()))
                row.appendChild(ctelt("td", change, " "))
                return tidx + 1;
            }
            if (tidx < tend) {
                row.appendChild(telt("th", (tidx + 1).toString()));
                row.appendChild(ctelt("td", change, textLines[tidx].replace(/\t/g, "\u00a0\u00a0\u00a0\u00a0")))
                return tidx + 1;
            } else {
                row.appendChild(document.createElement("th"));
                row.appendChild(celt("td", "empty"));
                return tidx;
            }
        }

        function addCellsInline(row, tidx, tidx2, textLines, change) {
            row.appendChild(telt("th", tidx == null ? "" : (tidx + 1).toString()));
            row.appendChild(telt("th", tidx2 == null ? "" : (tidx2 + 1).toString()));
            row.appendChild(ctelt("td", change, textLines[tidx != null ? tidx : tidx2].replace(/\t/g, "\u00a0\u00a0\u00a0\u00a0")));
        }

        function addCellsNode(row, tidx, tidx2, node, change) {
            row.appendChild(telt("th", tidx == null ? "" : (tidx + 1).toString()));
            row.appendChild(telt("th", tidx2 == null ? "" : (tidx2 + 1).toString()));
            row.appendChild(ctel("td", change, node));
        }

        for (var idx = 0; idx < opcodes.length; idx++) {
            var code = opcodes[idx];
            var change = code[0];
            var b = code[1];
            var be = code[2];
            var n = code[3];
            var ne = code[4];
            var rowcnt = Math.max(be - b, ne - n);
            var toprows = [];
            var botrows = [];
            for (var i = 0; i < rowcnt; i++) {
                if (contextSize && opcodes.length > 1 && ((idx > 0 && i == contextSize) || (idx == 0 && i == 0)) && change == "equal") {
                    var jump = rowcnt - (idx == 0 ? 1 : 2) * contextSize;
                    if (jump > 1) {
                        toprows.push((node2 = document.createElement("tr")));
                        b += jump;
                        n += jump;
                        i += jump - 1;
                        node2.appendChild(telt("th", "..."));
                        if (!inline) node2.appendChild(ctelt("td", "skip", ""));
                        node2.appendChild(telt("th", "..."));
                        node2.appendChild(ctelt("td", "skip", ""));
                        if (idx + 1 == opcodes.length) {
                            break;
                        } else {
                            continue;
                        }
                    }
                }
                toprows.push((node2 = document.createElement("tr")));
                if (inline) {
                    if (change == "insert") {
                        addCellsInline(node2, null, n++, newTextLines, change);
                    } else if (change == "replace") {
                        botrows.push((node3 = document.createElement("tr")));
                        if (wordlevel) {
                            var baseTextLine = baseTextLines[b];
                            var newTextLine = newTextLines[n];
                            var wordrule = /([^\S]+|[a-zA-Z0-9_-]+|.)(?:(?!<)[^\S\s])?/;
                            var bw = baseTextLine.split(wordrule);
                            var nw = newTextLine.split(wordrule);
                            var wsm = new difflib.SequenceMatcher(bw, nw);
                            var wopcodes = wsm.get_opcodes();
                            var bnode = document.createElement("span");
                            var nnode = document.createElement("span");
                            for (var k = 0; k < wopcodes.length; k++) {
                                var wcode = wopcodes[k];
                                var wchange = wcode[0];
                                var wb = wcode[1];
                                var wbe = wcode[2];
                                var wn = wcode[3];
                                var wne = wcode[4];
                                var wcnt = Math.max(wbe - wb, wne - wn);
                                for (var m = 0; m < wcnt; m++) {
                                    if (wchange == "insert") {
                                        nnode.appendChild(ctelt("ins", "table", nw[wn++]));
                                    } else if (wchange == "replace") {
                                        if (wb < wbe) bnode.appendChild(ctelt("del", "table", bw[wb++]));
                                        if (wn < wne) nnode.appendChild(ctelt("ins", "table", nw[wn++]));
                                    } else if (wchange == "delete") {
                                        bnode.appendChild(ctelt("del", "table", bw[wb++]));
                                    } else {
                                        bnode.appendChild(ctelt("span", wchange, bw[wb]));
                                        nnode.appendChild(ctelt("span", wchange, bw[wb++]));
                                    }
                                }
                            }
                            if (b < be) addCellsNode(node2, b++, null, bnode, "delete");
                            if (n < ne) addCellsNode(node3, null, n++, nnode, "insert");
                        } else {
                            if (b < be) addCellsInline(node2, b++, null, baseTextLines, "delete");
                            if (n < ne) addCellsInline(node3, null, n++, newTextLines, "insert");
                        }
                    } else if (change == "delete") {
                        addCellsInline(node2, b++, null, baseTextLines, change);
                    } else {
                        addCellsInline(node2, b++, n++, baseTextLines, change);
                    }
                } else {
                    b = addCells(node2, b, be, baseTextLines, change);
                    n = addCells(node2, n, ne, newTextLines, change);
                }
            }
            for (var i = 0; i < toprows.length; i++) rows.push(toprows[i]);
            for (var i = 0; i < botrows.length; i++) rows.push(botrows[i]);
        }

        tdata.push((node2 = document.createElement("tbody")));
        for (var idx in rows) rows.hasOwnProperty(idx) && node2.appendChild(rows[idx]);
        node2.classList.add('table-group-divider');
        var table = celt("table", "table table-striped table-hover" + (inline ? " inlinediff" : ""));
        for (var idx in tdata) table.appendChild(tdata[idx]);
        return table;
    },
};