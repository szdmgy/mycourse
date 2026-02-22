
function readWorkbookFromLocalFile(file, callback) {
        var reader = new FileReader();
        reader.onload = function(e) {
            var data = e.target.result;
            var workbook = XLSX.read(data, {type: 'binary'});
            if(callback) callback(workbook);
        };
        reader.readAsBinaryString(file);
}

 function readWorkbook(workbook) {
        var sheetNames = workbook.SheetNames; // 工作表名称集合
        var worksheet = workbook.Sheets[sheetNames[0]]; // 这里我们只读取第一张sheet
        var csv = XLSX.utils.sheet_to_csv(worksheet);
        csv = csv.replaceAll('\n', ';');
        console.log(csv)
        document.getElementById('addCourseStudentList').value = csv;
        // $("#result").csv2table(csv);

}

$(function () {
    document.getElementById('studentExcelUpload').addEventListener('change', function (e) {
        var files = e.target.files;
        console.log(files);
        if (files.length === 0) return;
        var f = files[0];
        console.log(f)
        if (!/\.xlsx$/g.test(f.name)) {
            alert('仅支持读取xlsx格式！');
            return;
        }
        readWorkbookFromLocalFile(f, function (workbook) {
            readWorkbook(workbook);
        });
    });
});
    function downloadStudentListTemplate() {
        var xhr = new XMLHttpRequest();
        xhr.open('GET', '/downloadStudentListTemplate', true);
        xhr.responseType = "blob";
        // xhr.setRequestHeader("X-CSRFtoken", csrfmiddlewaretoken)
        // xhr.setRequestHeader("Content-type","application/json");
        xhr.onload = function () {
            // 请求完成
            if (this.status === 200) {
                // 返回200
                filename = this.getResponseHeader('Content-Disposition');
                // 转成中文取出文件名
                filename = "学生导入模板.xlsx";
                console.log(filename);
                var blob = new Blob([this.response]);
                var csvUrl = URL.createObjectURL(blob);
                var link = document.createElement('a');
                link.href = csvUrl;
                link.download = filename;
                link.click();
                // alert("文件回传！");
                return true;
            }
        };
        // 发送ajax请求
        xhr.send();
    }





