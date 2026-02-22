$(function () {
    $("#choseTeacherBox").click(function () {
        $("#password-div").show();
    });
    $("#choseStudentBox").click(function () {
        $("#password-div").hide();
    });

    $(".deleteMemberBtn").click(function () {
        var confirmDelete = confirm("是否确认删除用户？");
        if(confirmDelete === true) {
            $(location).attr('href', '/deleteMemberByManager/' + $(this).val());
        }

    });


})

