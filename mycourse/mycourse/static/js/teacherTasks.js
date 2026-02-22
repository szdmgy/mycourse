function selectAll() {
    var checkBoxList = document.getElementsByClassName("selectStudentHomework-checkbox");
    var checkBoxLength = checkBoxList.length;
    for(let i = 0; i < checkBoxLength; i++) {
        if(checkBoxList[i].checked === false) {
            checkBoxList[i].checked = true;
        }
    }
}

function selectNone() {
    var checkBoxList = document.getElementsByClassName("selectStudentHomework-checkbox");
    var checkBoxLength = checkBoxList.length;
    for(let i = 0; i < checkBoxLength; i++) {
        if(checkBoxList[i].checked === true) {
            checkBoxList[i].checked = false;
        }
    }
}

//下载学生作业
function downloadHomework(taskName, postURL, csrfmiddlewaretoken, taskId) {
    var checkBoxList = document.getElementsByClassName("selectStudentHomework-checkbox-" + taskId);
    var checkBoxLength = checkBoxList.length;
    var studentList = [];

    for(let i = 0; i < checkBoxLength; i++) {
        if(checkBoxList[i].checked === true) {
            studentList[studentList.length] = checkBoxList[i].parentNode.parentNode.childNodes[3].textContent;
        }
    }

    if(studentList.length === 0)
    {
        alert("文件下载失败！");
        return null;
    }
    console.log('hello world!');
    console.log(studentList);
    console.log(taskName);
    console.log(taskId);
    console.log("发送文件请求");
    console.log("----------------------开始接收文件-----------");

    var xhr = new XMLHttpRequest();
    xhr.open('POST', postURL, true);
    xhr.responseType = "blob";
    xhr.setRequestHeader("X-CSRFtoken", csrfmiddlewaretoken)
    xhr.setRequestHeader("Content-type","application/json");
    xhr.onload = function () {
        // 请求完成
        if (this.status === 200) {
            // 返回200
            filename = this.getResponseHeader('Content-Disposition');
            // 转成中文取出文件名
            filename = decodeURI(escape(filename.substring(20)));
            console.log(filename);
            // console.log(filename);
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
    var sendData = {"taskName":taskName,"taskId":taskId, "studentNumberList":studentList}
    sendData = JSON.stringify(sendData);
    xhr.send(sendData);
}

$(function () {
    $(".changeCourseName-div").dblclick(function () {
        console.log($(".changeCourseName-input").prop("disabled"));
        if($(".changeCourseName-input").prop("disabled") === true) {
            $(".changeCourseName-input").prop("disabled", false);
            $(".changeCourseNumber-input").prop("disabled", false);

        }
        else {
            $(".changeCourseName-input").prop("disabled", true);
            $(".changeCourseNumber-input").prop("disabled", true);
        }
    });

    $(".deleteTask-btn").click(function () {
        var sure = confirm("是否要删除该作业？这会丢失该作业的所有信息！");
        if(sure === false){
            return false;
        }
        $(location).attr('href', '/deleteTaskByTeacher/' + $(this).val());
    });

    $(".removeStudentByTeacher-btn").click(function () {
        var sure = confirm("是否要移除该学生？");
        if(sure === false){
            return false;
        }
        //$(location).attr('href', '/removeStudentFromCourse/' + $(".changeCourseNumber-input").val() + '/' + $(".changeCourseName-input").val() + '/' + $(this).val() + '/');
        $(location).attr('href', '/removeStudentFromCourse/1/2/3/');
    });

    $("#deleteCourseBtn").click(function () {
        console.log("aa");
        var courseName = $(this).attr("coursename");
        var courseNumber = $(this).attr("coursenumber");
        var sure = confirm("是否要删除该课程？这会丢失该课程的所有信息！");
        if(sure === false){
            return false;
        }
        $(location).attr('href', '/deleteCourse/' + courseNumber + '/' + courseName + '/');

    });


});
