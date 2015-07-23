#!/usr/bin/python
# -*- coding: utf-8 -*-
# kate: space-indent on; indent-width 4; mixedindent off; indent-mode python;

from django.contrib import admin
from django import forms
from arsoft.web.filewatch.models import FileWatchModel

class FileWatchForm(forms.ModelForm):
    exclude = []
    class Meta:
        model = FileWatchModel

class FileWatchAdmin(admin.ModelAdmin):

    list_display = ('filename', 'recursive', 'notify')
    fields = ['filename', 'recursive', 'notify']
    form = FileWatchForm

admin.site.register(FileWatchModel, FileWatchAdmin)
