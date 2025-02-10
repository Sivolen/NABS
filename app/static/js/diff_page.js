

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
function changeFunc1() {
    var selectBox = document.getElementById("date");
    var selectedValue = selectBox.options[selectBox.selectedIndex].value;
    document.getElementById("previous_config_label").innerHTML = "Previous config: " + document.getElementsByName("date")[0].value;
    changeConfig();
}
function changeFunc() {
    // Cache elements and use modern syntax
    const dateElement = document.getElementById("date");
    const configLabel = document.getElementById("previous_config_label");

    // Use textContent instead of innerHTML for security
    configLabel.textContent = `Previous config: ${dateElement.value}`;

    // Calling the main logic
    changeConfig();
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
