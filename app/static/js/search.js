            //Search on compare table
            function tableSearch() {
                let phrase = document.getElementById("search-table");
                let table = document.getElementById("config-table");
                let regPhrase = new RegExp(phrase.value, "i");
                let beforeCount = -5;
                let afterCount = 5;
                let foundRows = [];
                for (let i = 1; i < table.rows.length; i++) {
                    let flag = false;
                    for (let j = table.rows[i].cells.length - 1; j >= 0; j--) {
                        flag = regPhrase.test(table.rows[i].cells[j].innerHTML);
                        if (flag) break;
                    }
                    if (flag) {
                        foundRows.push(i);

                    }
                    table.rows[i].style.display = "none";
                }
                let tmpRows = [];
                for (let i = beforeCount; i <= afterCount; i += 1) {
                    tmpRows.push(...foundRows.map(value => value + i));
                }
                let selectedRows = Array.from(new Set(tmpRows))
                    .filter(values => values >= 1)
                    .filter(values => values < table.rows.length);
                selectedRows.forEach(row => {table.rows[row].style.display = "" ; if (phrase.value == ""){table.rows[row].classList.remove("table-success")} else if (regPhrase.test(table.rows[row].innerText)) {table.rows[row].classList.add("table-success")} else {table.rows[row].classList.remove("table-success")} ;});
            }