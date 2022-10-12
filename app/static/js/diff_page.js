//Search on compare table
            function tableSearch() {
                var phrase = document.getElementById("search-table");
                var table = document.getElementById("diff_table");
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
               }


// diff function
//var $d = dojo.byId;
//dojo.require("dojo.io");
//var url = window.location.toString().split("#")[0];

//function diffUsingJS(viewType) {
//	"use strict";
//	var byId = function (id) { return document.getElementById(id); },
//		base = difflib.stringAsLines(byId("baseText").value),
//		newtxt = difflib.stringAsLines(byId("newText").value),
//		sm = new difflib.SequenceMatcher(base, newtxt),
//		opcodes = sm.get_opcodes(),
//		diffoutputdiv = byId("diffoutput"),
//		contextSize = byId("contextSize").value;
//
//	diffoutputdiv.innerHTML = "";
//	contextSize = contextSize || null;
//
//	diffoutputdiv.appendChild(diffview.buildView({
//		baseTextLines: base,
//		newTextLines: newtxt,
//		opcodes: opcodes,
//		baseTextName: "Previous config",
//		newTextName: "Last config",
//		contextSize: contextSize,
//		viewType: viewType
//	}));
//}

// start diff script after change element in date list
function changeFunc() {
    var selectBox = document.getElementById("date");
    var selectedValue = selectBox.options[selectBox.selectedIndex].value;
    document.getElementById("previous_config_label").innerHTML = "Previous config: " + document.getElementsByName("date")[0].value;
    change_config();
}

//function scrollFunction() {
//    if (document.body.scrollTop > 20 || document.documentElement.scrollTop > 20) {
//        mybutton.style.display = "block";
//    } else {
//        mybutton.style.display = "none";
//    }
//}
//
//// When the user clicks on the button, scroll to the top of the document
//function topFunction() {
//    document.body.scrollTop = 0; // For Safari
//    document.documentElement.scrollTop = 0; // For Chrome, Firefox, IE and Opera
//}
