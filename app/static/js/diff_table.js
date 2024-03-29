diffview = {
    /**
     * Builds and returns a visual diff view.  The single parameter, `params', should contain
     * the following values:
     *
     * - baseTextLines: the array of strings that was used as the base text input to SequenceMatcher
     * - newTextLines: the array of strings that was used as the new text input to SequenceMatcher
     * - opcodes: the array of arrays returned by SequenceMatcher.get_opcodes()
     * - baseTextName: the title to be displayed above the base text listing in the diff view; defaults
     *	   to "Base Text"
     * - newTextName: the title to be displayed above the new text listing in the diff view; defaults
     *	   to "New Text"
     * - contextSize: the number of lines of context to show around differences; by default, all lines
     *	   are shown
     * - viewType: if 0, a side-by-side diff view is generated (default); if 1, an inline diff view is
     *	   generated
     */
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

        var tdata = document.createElement("thead");
        var node = document.createElement("tr");
        tdata.appendChild(node);
        if (inline) {
            node.appendChild(document.createElement("th"));
            node.appendChild(document.createElement("th"));
            node.appendChild(ctelt("th", "row", baseTextName + " vs. " + newTextName));
        } else {
            node.appendChild(document.createElement("th"));
            node.appendChild(ctelt("th", "col", baseTextName));
            node.appendChild(document.createElement("th"));
            node.appendChild(ctelt("th", "col", newTextName));
        }
        tdata = [tdata];

        var rows = [];
        var node2;

        /**
         * Adds two cells to the given row; if the given row corresponds to a real
         * line number (based on the line index tidx and the endpoint of the
         * range in question tend), then the cells will contain the line number
         * and the line of text from textLines at position tidx (with the class of
         * the second cell set to the name of the change represented), and tidx + 1 will
         * be returned.	 Otherwise, tidx is returned, and two empty cells are added
         * to the given row.
         */

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

        function addCells_new(row, tidx, tend, textLines, change) {
          const cellText = textLines[tidx] ? textLines[tidx].replace(/\t/g, "\u00a0\u00a0\u00a0\u00a0") : "";
          row.appendChild(telt("th", (tidx + 1).toString()));
          row.appendChild(ctelt("td", change, cellText));
          return tidx < tend ? tidx + 1 : tidx;
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
            code = opcodes[idx];
            change = code[0];
            var b = code[1];
            var be = code[2];
            var n = code[3];
            var ne = code[4];
            var rowcnt = Math.max(be - b, ne - n);
            var toprows = [];
            var botrows = [];
            for (var i = 0; i < rowcnt; i++) {
                // jump ahead if we've alredy provided leading context or if this is the first range
                if (contextSize && opcodes.length > 1 && ((idx > 0 && i == contextSize) || (idx == 0 && i == 0)) && change == "equal") {
                    var jump = rowcnt - (idx == 0 ? 1 : 2) * contextSize;
                    if (jump > 1) {
                        toprows.push((node = document.createElement("tr")));

                        b += jump;
                        n += jump;
                        i += jump - 1;
                        node.appendChild(telt("th", "..."));
                        if (!inline) node.appendChild(ctelt("td", "skip", ""));
                        node.appendChild(telt("th", "..."));
                        node.appendChild(ctelt("td", "skip", ""));

                        // skip last lines if they're all equal
                        if (idx + 1 == opcodes.length) {
                            break;
                        } else {
                            continue;
                        }
                    }
                }

                toprows.push((node = document.createElement("tr")));
                if (inline) {
                    if (change == "insert") {
                        addCellsInline(node, null, n++, newTextLines, change);
                    } else if (change == "replace") {
                        botrows.push((node2 = document.createElement("tr")));
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
                                        // equal
                                        bnode.appendChild(ctelt("span", wchange, bw[wb]));
                                        nnode.appendChild(ctelt("span", wchange, bw[wb++]));
                                    }
                                }
                            }
                            if (b < be) addCellsNode(node, b++, null, bnode, "delete");
                            if (n < ne) addCellsNode(node2, null, n++, nnode, "insert");
                        } else {
                            if (b < be) addCellsInline(node, b++, null, baseTextLines, "delete");
                            if (n < ne) addCellsInline(node2, null, n++, newTextLines, "insert");
                        }
                    } else if (change == "delete") {
                        addCellsInline(node, b++, null, baseTextLines, change);
                    } else {
                        // equal
                        addCellsInline(node, b++, n++, baseTextLines, change);
                    }
                } else {
                    b = addCells(node, b, be, baseTextLines, change);
                    n = addCells(node, n, ne, newTextLines, change);

                 }
            }
            for (var i = 0; i < toprows.length; i++) rows.push(toprows[i]);
            for (var i = 0; i < botrows.length; i++) rows.push(botrows[i]);
        }

        tdata.push((node = document.createElement("tbody")));
        for (var idx in rows) rows.hasOwnProperty(idx) && node.appendChild(rows[idx]);
        node.classList.add('table-group-divider');
        node = celt("table", "table table-striped table-hover" + (inline ? " inlinediff" : ""));

        for (var idx in tdata) node.appendChild(tdata[idx]);
        return node;
    },
};
