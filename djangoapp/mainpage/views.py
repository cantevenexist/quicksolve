from django.http import HttpResponse


def index(request):
    return HttpResponse(
        f"Hello, world!"
        f"<div>{request.user.username}</div>"
        "<div><a href='./account/login'>login</a></div>"
        "<div><a href='./account/logout'>logout</a></div>"
        )