# from django.http import HttpResponse


# def index(request):
#     return HttpResponse(
#         f"Hello, world!"
#         f"<div>{request.user.username}</div>"
#         "<div><a href='./profile'>profile</a></div>"
#         "<div><a href='./account/login'>login</a></div>"
#         "<div><a href='./account/logout'>logout</a></div>"
#         )

from django.views.generic import TemplateView
# from django.shortcuts import render
# from .models import YourModel  # если есть модели

class IndexView(TemplateView):
    template_name = 'main_page/index.html'