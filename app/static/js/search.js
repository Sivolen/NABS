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



//Search on compare table
function tableSearch() {
    var phrase = document.getElementById("search-table");
    var table = document.getElementById("diff_table");
    var regPhrase = new RegExp(phrase.value, "i");
    var flag = false;
    for (var i = 1; i < table.rows.length; i++) {
        flag = false;
        for (var j = table.rows[i].cells.length - 1; j >= 0; j--) {
            flag = regPhrase.test(table.rows[i].cells[j].innerHTML);
            if (flag) break;
        }
        if (flag) {
            table.rows[i].style.display = "";
        } else {
            table.rows[i].style.display = "none";
        }
    }
}



            //Search on compare table
            function tableSearch() {
                var phrase = document.getElementById("search-table");
                var table = document.getElementById("config-table");
                var regPhrase = new RegExp(phrase.value, "i");
                var beforeCount = -5;
                var afterCount = 5;
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
                    table.rows[i].style.backgroundColor = "";
                }
                let tmpRows = [];
                for (let i = beforeCount; i <= afterCount; i += 1) {
                    tmpRows.push(...foundRows.map(value => value + i));
                }
                // console.log('tmpRows', tmpRows)
                let selectedRows = Array.from(new Set(tmpRows))
                    .filter(values => values >= 1)
                    .filter(values => values < table.rows.length);
                // console.log('selectedRows', selectedRows)
                selectedRows.forEach(row => table.rows[row].style.display = "");
                {foundRows.forEach(row => {if (phrase.value == ""){table.rows[row].style.backgroundColor = ""} else {table.rows[row].style.backgroundColor = "#d1e7dd"}});}
               }




                           //Search on compare table
            function tableSearch() {
                var phrase = document.getElementById("search-table");
                var table = document.getElementById("config-table");
                var regPhrase = new RegExp(phrase.value, "i");
                var flag = false;
                let start_count = 7;
                for (var i = 1; i < table.rows.length; i++) {
                    flag = false;
                    for (var j = table.rows[i].cells.length - 1; j >= 0; j--) {
                        flag = regPhrase.test(table.rows[i].cells[j].innerHTML);
                        if (flag) break;
                    }
                    if (flag) {
                        table.rows[i].style.display = "";
                        table.rows[i].classList.add("table-success");
                        for (let count = 1; count <= start_count; count++) {
                            if (i < table.rows.length - 1) {
                                table.rows[i + count].style.display = "";
                            }
                            if (i > count) {
                                table.rows[i - count].style.display = "";
                            }
                        }
                        if (phrase.value == "") {
                            table.rows[i].classList.remove("table-success");
                        }
                    } else {
                        table.rows[i].style.display = "none";
                        table.rows[i].classList.remove("table-success");
                    }
                }
            }