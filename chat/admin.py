from django.contrib import admin

from chat.models import RouterRule


# BO `라우팅 관리` 가 주 관리 UI. Django admin 은 비상 백업 (BO 가 일시 고장 날 때).
admin.site.register(RouterRule)
