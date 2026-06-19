function loadTableData(rows) {
    const table = document.getElementById("filter-table-body");
    let colorize = table.classList.contains('colorize');

    for (let i = 0; i < rows.length; i++) {
        let tr = table.insertRow();

        if (colorize) { colorizeRow(i, tr); }

        for (let ix = 0; ix < rows[i].length; ix++) {
            tr.insertCell(ix).innerHTML = rows[i][ix];
        }
    }
}
function colorizeTable() {
    const tables = document.querySelectorAll(".colorize");
    for (let table of tables) {
        let tr = table.getElementsByTagName("tr");
        for (let i = 0; i < tr.length; i++) { colorizeRow(i, tr); }
    }
}
function filterTable(n1, n2, id='') {
    let input = document.getElementById(`filter-input${id}`);
    let table = document.getElementById(`filter-table${id}`);
    let tr = table.getElementsByTagName("tr");
    let colorize = table.classList.contains('colorize');

    if (input.value.length === 1) { return; }

    let r = 0;
    for (let i = 0; i < tr.length; i++) {
        let tdList = tr[i].getElementsByTagName("td");

        if (tdList.length < n2) { continue; }

        let matched = false;
        for (let f = n1; f < n2; f++) {
            if (tdList[f].textContent.indexOf(input.value) > -1) { matched = true; break; }
        }

        tr[i].style.display = matched ? "" : "none";

        if (matched) {
            if (colorize) { tr[i].className = (r % 2 === 0) ? "tr-even" : "tr-odd"; }
            r++;
        }
    }
}
function colorizeRow(i, tr) {
    if (i % 2 === 0) {
        tr[i].className = "tr-even";
    } else {
        tr[i].className = "tr-odd";
    }
}
