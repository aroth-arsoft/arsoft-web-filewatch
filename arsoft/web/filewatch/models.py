from django.db import models
from django import forms
from datetime import datetime

class FileWatchModel(models.Model):
    filename = models.CharField('Filename', max_length=512, unique=True, help_text='Enter full path for a file/directory to watch')
    recursive = models.BooleanField('Recursive', default=True, help_text='Check for files inside the given directory')
    notify = models.EmailField('notify', help_text='email address for the notification')

    class Meta:
        verbose_name = "file"
        verbose_name_plural = "files"

    def __unicode__(self):
        return '%s' % (self.filename)


class FileWatchItemModel(models.Model):
    watchid = models.ForeignKey(FileWatchModel)
    filename = models.CharField('Filename', max_length=512, unique=True, help_text='Enter full path for a file to watch')
    created = models.DateTimeField('Created')
    modified = models.DateTimeField('Modified')
    uid = models.IntegerField('uid')
    gid = models.IntegerField('gid')
    mode = models.IntegerField('mode')
    size = models.IntegerField('size')

    class Meta:
        verbose_name = "file"
        verbose_name_plural = "files"

    def __unicode__(self):
        return '%s' % (self.filename)

class FileWatchItemFromDisk(object):
    def __init__(self, filename, file_stats):
        self.filename = filename
        self.created = datetime.fromtimestamp(file_stats.st_ctime)
        self.modified = datetime.fromtimestamp(file_stats.st_mtime)
        self.uid = file_stats.st_uid
        self.gid = file_stats.st_gid
        self.mode = file_stats.st_mode
        self.size = file_stats.st_size
        
