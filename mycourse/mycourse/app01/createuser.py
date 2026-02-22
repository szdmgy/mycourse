

from app01.loaduser import load_user_list
from app01.models import UserProfile
from django.contrib.auth.models import User


def create_student_user():
    users = load_user_list()
    for user in users:
        user_obj = User.objects.create_user(username=user[0], password='szu'+user[0][-6:])
        if user[2] == '男':
            sex = u'M'
        else:
            sex = u'F'
        UserProfile.objects.create(name=user[1], gender=sex, user_id=user_obj.id)




if __name__ == '__main__':
    print('hello')
    create_student_user()