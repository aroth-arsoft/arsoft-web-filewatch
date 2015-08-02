#!/usr/bin/python
# -*- coding: utf-8 -*-
# kate: space-indent on; indent-width 4; mixedindent off; indent-mode python;

from django.template import RequestContext, Template, Context, loader
from django.core.urlresolvers import reverse
from django.http import HttpResponse, StreamingHttpResponse
from django.core.mail import send_mail
from django.conf import settings
from arsoft.web.filewatch.models import FileWatchModel, FileWatchItemModel, FileWatchItemFromDisk
from django.db import transaction

import sys
import os, stat
try:
    from StringIO import StringIO
except ImportError:
    from io import StringIO
from datetime import datetime
from arsoft.timestamp import timestamp_from_datetime, as_local_time

# import the logging library
import logging

# Get an instance of a logger
logger = logging.getLogger(__name__)

def home(request):

    t = loader.get_template('home.html')
    c = RequestContext( request, { 
        'title':'home'
        })
    return HttpResponse(t.render(c))


def _get_request_param(request, paramname, default_value=None):
    if paramname in request.GET:
        if isinstance(default_value, int):
            ret = int(request.GET[paramname])
        elif isinstance(default_value, str) or isinstance(default_value, unicode):
            ret = str(request.GET[paramname])
        else:
            ret = request.GET[paramname]
    else:
        ret = default_value
    return ret

def _get_files_recursive(filename):
    ret = []
    files = []
    try:
        files = os.listdir(filename)
    except OSError:
        pass
    enc = sys.getfilesystemencoding()
    for f in files:
        if f == '.' or f == '..':
            continue
        try:
            full = os.path.join(filename, f)
        except UnicodeDecodeError as e:
            raise Exception('failure at %s: %s-%s, %s' % (enc, filename, f.decode('utf8'), e))
        try:
            s = os.stat(full)
            if stat.S_ISDIR(s.st_mode):
                subdir_files = _get_files_recursive(full)
                ret.extend(subdir_files)
            elif stat.S_ISREG(s.st_mode):
                ret.append( FileWatchItemFromDisk(full, s) )
        except FileNotFoundError:
            pass
    return ret

class CheckItemHandler(object):
    def __init__(self, request=None, item_id=None, verbose=False, notify=True):
        self._pos = 0
        self._request = request
        self._item_id = item_id
        self._verbose = verbose
        self._notify = notify
        self._handler_list = [ self._send_header, 
                              self._load_disk_files, 
                              self._load_db_files, 
                              self._compare_files,
                              self._send_email_notifications, 
                              self._send_footer ]
        self._result_item_list = []
        
    class ResultItem(object):
        def __init__(self, item):
            self.changed_list = []
            self.unchanged_list = []
            self.files_on_disk = []
            self.files_in_db = []
            self.item = item

        @property
        def id(self):
            return self.item.id

        @property
        def filename(self):
            return self.item.filename

        @property
        def recipient_list(self):
            if isinstance(self.item.notify, list):
                return self.item.notify
            elif ';' in self.item.notify:
                return self.item.notify.split(';')
            else:
                return [ self.item.notify ]


    def _send_header(self):
        if self._item_id:
            yield 'begin: check item %i\r\n' % self._item_id
        else:
            yield 'begin: check all items\r\n'
        
    def _send_footer(self):
        if self._item_id:
            yield 'complete: check item %i\r\n' % self._item_id
        else:
            yield 'complete: check all items\r\n'
        
    def _load_disk_files(self):

        item_list = []
        if self._item_id:
            try:
                item = FileWatchModel.objects.get(id=self._item_id)
                if item:
                    item_list.append(item)
            except FileWatchModel.DoesNotExist:
                pass
        else:
            item_list = FileWatchModel.objects.all()
                
        for item in item_list:
            result_item = CheckItemHandler.ResultItem(item)
            if os.path.exists(item.filename):
                yield 'disk: Scanning %s for files\r\n' % (result_item.filename)
                if os.path.isdir(item.filename) and item.recursive:
                    result_item.files_on_disk = _get_files_recursive(item.filename)
                else:
                    s = os.stat(item.filename)
                    result_item.files_on_disk = [ FileWatchItemFromDisk(item.filename, s) ]
            else:
                yield 'disk: %s does not exist\r\n' % (result_item.filename)
            self._result_item_list.append(result_item)
            yield 'disk: %s found %i files\r\n' % (result_item.filename, len(result_item.files_on_disk))

    def _load_db_files(self):
        for result_item in self._result_item_list:
            yield 'database: %s loading files\r\n' % (result_item.filename)
            try:
                result_item.files_in_db = FileWatchItemModel.objects.filter(watchid=result_item.id)
            except FileWatchItemModel.DoesNotExist:
                pass
            yield 'database: %s loaded %i files\r\n' % (result_item.filename, len(result_item.files_in_db))

    def _compare_files(self):

        for result_item in self._result_item_list:
            yield 'compare: %s start\r\n' % (result_item.filename)
            # expect all files from DB to be found on disk
            missing_files_from_db = []
            for db_item in result_item.files_in_db:
                missing_files_from_db.append(db_item)

            result_item.changed_list = []
            result_item.unchanged_list = []

            for disk_item in result_item.files_on_disk:
                found = False
                for db_item in result_item.files_in_db:
                    if db_item.filename == disk_item.filename:
                        found = True
                        break
                changes = []
                if not found:
                    with transaction.atomic():
                        model = FileWatchItemModel.objects.create(watchid=result_item.item, 
                                                                filename=disk_item.filename, 
                                                                created=disk_item.created,
                                                                modified=disk_item.modified,
                                                                uid=disk_item.uid,
                                                                gid=disk_item.gid,
                                                                mode=disk_item.mode,
                                                                size=disk_item.size
                                                                )
                    changes.append( 'File added' )
                    yield 'compare: %s: file %s added\r\n' % (result_item.filename, disk_item.filename)
                else:
                    missing_files_from_db.remove(db_item)

                    #logger.error('%s %s, %s' % (disk_item.filename, disk_item.created, as_local_time(disk_item.created)))
                    #logger.error('%s %s, %s' % (db_item.filename, db_item.created, as_local_time(db_item.created)))
                    db_item_dirty = False
                    if disk_item.created != db_item.created:
                        changes.append( 'Create time changed from %s to %s' % (as_local_time(db_item.created), as_local_time(disk_item.created)) )
                        db_item.created = disk_item.created
                        db_item_dirty = True
                    if disk_item.modified != db_item.modified:
                        changes.append( 'Modification time changed from %s to %s' % (as_local_time(db_item.modified), as_local_time(disk_item.modified)) )
                        db_item.modified = disk_item.modified
                        db_item_dirty = True
                    if disk_item.uid != db_item.uid:
                        changes.append( 'Owner changed from %i to %i' % (db_item.uid, disk_item.uid) )
                        db_item.uid = disk_item.uid
                        db_item_dirty = True
                    if disk_item.gid != db_item.gid:
                        changes.append( 'Group changed from %i to %i' % (db_item.gid, disk_item.gid) )
                        db_item.gid = disk_item.gid
                        db_item_dirty = True
                    if disk_item.mode != db_item.mode:
                        changes.append( 'Mode changed from %o to %o' % (db_item.mode, disk_item.mode) )
                        db_item.mode = disk_item.mode
                        db_item_dirty = True
                    if disk_item.size != db_item.size:
                        changes.append( 'Size changed from %o to %o' % (db_item.size, disk_item.size) )
                        db_item.size = disk_item.size
                        db_item_dirty = True
                    if db_item_dirty:
                        yield 'compare: %s: file %s changed\r\n' % (result_item.filename, disk_item.filename)
                        with transaction.atomic():
                            db_item.save()
                    else:
                        yield 'compare: %s: file %s unchanged\r\n' % (result_item.filename, disk_item.filename)
                        result_item.unchanged_list.append( (db_item.filename, []) )

                if changes:
                    result_item.changed_list.append( (disk_item.filename, changes) )
            for db_item in missing_files_from_db:
                changes = ['File deleted']
                result_item.changed_list.append( (db_item.filename, changes) )
                with transaction.atomic():
                    db_item.delete()
                yield 'compare: %s: file %s deleted\r\n' % (result_item.filename, db_item.filename)
            yield 'compare: %s done\r\n' % (result_item.filename)

    def _send_email_notifications(self):
        if not self._notify:
            yield 'send_notification: skipped\r\n'
            return

        for result_item in self._result_item_list:
            if not result_item.changed_list:
                continue
            stat_dict = { 
                        'filename': result_item.filename, 
                        'num_files': len(result_item.changed_list) + len(result_item.unchanged_list),
                        'num_changed': len(result_item.changed_list), 
                        'num_unchanged': len(result_item.unchanged_list) 
                        }
            
            subject = settings.EMAIL_SUBJECT_FORMAT % stat_dict
            from_email = settings.EMAIL_SENDER
            recipient_list = result_item.recipient_list

            t = Template(FILEWATCH_CHECK_VIEW_TEMPLATE, name='check view template')
            c = RequestContext( self._request, { 
                'request':self._request,
                'item':result_item.item,
                'filename': result_item.filename, 
                'num_files': len(result_item.changed_list) + len(result_item.unchanged_list),
                'num_changed': len(result_item.changed_list), 
                'num_unchanged': len(result_item.unchanged_list),
                'changed_list':result_item.changed_list,
                'unchanged_list':result_item.unchanged_list,
                'report_unchanged': settings.REPORT_UNCHANGED,
                })
            yield 'send_notification: about to %s sent to %s\r\n' % (result_item.filename, recipient_list)
            send_mail(subject=subject, from_email=from_email, recipient_list=recipient_list, message='', html_message=t.render(c), fail_silently=False)
            yield 'send_notification: %s sent to %s\r\n' % (result_item.filename, recipient_list)

    def __iter__(self):
        for func in self._handler_list:
            for func_result in func():
                yield func_result

@transaction.non_atomic_requests
def check(request):
    
    verbose = _get_request_param(request, 'verbose', 0)
    notify = _get_request_param(request, 'notify', 1)

    response_status = 200
    response = StreamingHttpResponse(streaming_content=CheckItemHandler(request=request, verbose=verbose, notify=notify), 
                                     status=response_status, content_type="text/plain")
    return response

FILEWATCH_CHECK_VIEW_TEMPLATE = """
{% load type %}
{% load base_url %}
{% load static_url %}
{% load media_url %}
<!DOCTYPE html>
<html lang="en">
<head>
  <meta http-equiv="content-type" content="text/html; charset=utf-8">
  {% if filename %}
  <title>Filewatch report for {{ filename }}</title>
  {% else %}
  <title>Filewatch report</title>
  {% endif %}
  <meta name="robots" content="NONE,NOARCHIVE">
  <style type="text/css">
    html * { padding:0; margin:0; }
    body * { padding:10px 20px; }
    body * * { padding:0; }
    body { font:small sans-serif; background:#eee; }
    body>div { border-bottom:1px solid #ddd; }
    h1 { font-weight:normal; margin-bottom:.4em; }
    h1 span { font-size:60%; color:#666; font-weight:normal; }
    table { border:none; border-collapse: collapse; width:100%; }
    td, th { vertical-align:top; padding:2px 3px; }
    th { width:12em; text-align:right; color:#666; padding-right:.5em; }
    #changed { background:#f6f6f6; }
    #changed ol { margin: 0.5em 4em; }
    #changed ol li { font-family: monospace; }
    #unchanged { background:#f6f6f6; }
    #unchanged ol { margin: 0.5em 4em; }
    #unchanged ol li { font-family: monospace; }
    #summary { background: #ffc; }
    #explanation { background:#eee; border-bottom: 0px none; }
  </style>
</head>
<body>
  <div id="summary">
  {% if filename %}
  <h1>Filewatch report for {{ filename }}</h1>
  {% else %}
  <h1>Filewatch report</h1>
  {% endif %}
    <table class="meta">
  {% if filename %}
    <tr>
      <th>Filename:</th>
      <td><pre>{{ filename }}</pre></td>
    </tr>
  {% else %}
    <tr>
      <th>Number of mails:</th>
      <td>{{ num_mails_ok }} ok / {{ num_mails_failed }} failed</td>
    </tr>
  {% endif %}
    <tr>
      <th>Total number of files:</th>
      <td>{{ num_files }}</td>
    </tr>
    <tr>
      <th>Changed files:</th>
      <td>{{ num_changed }}</td>
    </tr>
    <tr>
      <th>Unchanged files:</th>
      <td>{{ num_unchanged }}</td>
    </tr>
    </table>
  </div>
{% if num_changed != 0 %}
  <div id="changed">
    <p>Changed files</p>
      <ol>
        {% for item in changed_list %}
          <li>
            {{ item.0 }}
            <ol>
                {% for change_item in item.1 %}
                    <li>{{change_item}}</li>
                {% endfor %}
            </ol>
            
          </li>
        {% endfor %}
      </ol>
  </div>
{% endif %}
{% if report_unchanged and num_unchanged != 0 %}
  <div id="unchanged">
    <p>Unchanged files</p>
      <ol>
        {% for item in unchanged_list %}
          <li>
            {{ item.0 }}
            <ol>
                {% for change_item in item.1 %}
                    <li>{{change_item}}</li>
                {% endfor %}
            </ol>
            
          </li>
        {% endfor %}
      </ol>
  </div>
{% endif %}
  <div id="explanation">
    <p>
      This report was automatically generated. Please do not respond to this mail.
    </p>
  </div>
</body>
</html>
"""
