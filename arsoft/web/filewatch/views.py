from django.template import RequestContext, Template, Context, loader
from django.core.urlresolvers import reverse
from django.http import HttpResponse
from django.core.mail import send_mail
from django.conf import settings
from arsoft.web.filewatch.models import FileWatchModel, FileWatchItemModel, FileWatchItemFromDisk

import os, stat
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
    for f in files:
        if f == '.' or f == '..':
            continue
        full = os.path.join(filename, f)
        s = os.stat(full)
        if stat.S_ISDIR(s.st_mode):
            subdir_files = _get_files_recursive(full)
            ret.extend(subdir_files)
        elif stat.S_ISREG(s.st_mode):
            ret.append( FileWatchItemFromDisk(full, s) )
    return ret

def _check_item(item):
    ret_changed = []
    ret_unchanged = []

    files_in_db = []
    files_on_disk = []

    try:
        files_in_db = FileWatchItemModel.objects.filter(watchid=item.id)
    except FileWatchItemModel.DoesNotExist:
        pass
    
    # expect all files from DB to be found on disk
    missing_files_from_db = []
    for db_item in files_in_db:
        missing_files_from_db.append(db_item)

    if os.path.exists(item.filename):
        if os.path.isdir(item.filename) and item.recursive:
            files_on_disk = _get_files_recursive(item.filename)
        else:
            s = os.stat(item.filename)
            files_on_disk.append( FileWatchItemFromDisk(item.filename, s))
    
    for disk_item in files_on_disk:
        found = False
        for db_item in files_in_db:
            if db_item.filename == disk_item.filename:
                found = True
                break
        changes = []
        if not found:
            model = FileWatchItemModel.objects.create(watchid=item, 
                                                      filename=disk_item.filename, 
                                                      created=disk_item.created,
                                                      modified=disk_item.modified,
                                                      uid=disk_item.uid,
                                                      gid=disk_item.gid,
                                                      mode=disk_item.mode,
                                                      size=disk_item.size
                                                      )
            changes.append( 'File added' )
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
                db_item.save()
            else:
                ret_unchanged.append( (db_item.filename, []) )

        if changes:
            ret_changed.append( (disk_item.filename, changes) )
    for db_item in missing_files_from_db:
        changes = ['File deleted']
        ret_changed.append( (db_item.filename, changes) )
        FileWatchItemModel.objects.delete(db_item)
    return (ret_changed, ret_unchanged)

def _send_email_notifications(request, item, check_result):
    changed_list, unchanged_list = check_result
    
    if not changed_list:
        return None
    
    stat_dict = { 
                'filename': item.filename, 
                'num_files': len(changed_list) + len(unchanged_list),
                'num_changed': len(changed_list), 
                'num_unchanged': len(unchanged_list) 
                }
    
    subject = settings.EMAIL_SUBJECT_FORMAT % stat_dict
    from_email = settings.EMAIL_SENDER
    recipient_list = []
    if isinstance(item.notify, list):
        recipient_list.extend(item.notify)
    elif ';' in item.notify:
        recipient_list.extend(item.notify.split(';'))
    else:
        recipient_list.append(item.notify)

    t = Template(FILEWATCH_CHECK_VIEW_TEMPLATE, name='check view template')
    c = RequestContext( request, { 
        'request':request,
        'item':item,
        'filename': item.filename, 
        'num_files': len(changed_list) + len(unchanged_list),
        'num_changed': len(changed_list), 
        'num_unchanged': len(unchanged_list),
        'changed_list':changed_list,
        'unchanged_list':unchanged_list,
        'report_unchanged': settings.REPORT_UNCHANGED,
        })
    send_mail(subject=subject, from_email=from_email, recipient_list=recipient_list, message='', html_message=t.render(c), fail_silently=False)
    return True

def check(request):
    
    verbose = _get_request_param(request, 'verbose', 0)
    
    response_status = 200
    response_data = ''
    changed_list = []
    unchanged_list = []
    num_mails_ok = 0
    num_mails_failed = 0
    for item in FileWatchModel.objects.all():
        item_changed_list, item_unchanged_list = _check_item(item)
        
        ret = _send_email_notifications(request, item, (item_changed_list, item_unchanged_list) )
        if ret is not None:
            if ret:
                num_mails_ok += 1
            else:
                num_mails_failed += 1
        
        changed_list.extend(item_changed_list)
        unchanged_list.extend(item_unchanged_list)
    if verbose:
        t = Template(FILEWATCH_CHECK_VIEW_TEMPLATE, name='check view template')
        c = RequestContext( request, { 
            'request':request,
            'num_mails_ok':num_mails_ok,
            'num_mails_failed':num_mails_failed,
            'num_files': len(changed_list) + len(unchanged_list),
            'num_changed': len(changed_list), 
            'num_unchanged': len(unchanged_list),
            'changed_list':changed_list,
            'unchanged_list':unchanged_list,
            'report_unchanged': settings.REPORT_UNCHANGED,
            })
        return HttpResponse(t.render(c), status=response_status)
    else:
        return HttpResponse(response_data, status=response_status, content_type="text/plain")        


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
