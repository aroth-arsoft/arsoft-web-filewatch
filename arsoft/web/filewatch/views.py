from django.template import RequestContext, Template, Context, loader
from django.core.urlresolvers import reverse
from django.http import HttpResponse
from arsoft.web.filewatch.models import FileWatchModel, FileWatchItemModel, FileWatchItemFromDisk

import os, stat
from datetime import datetime
from arsoft.timestamp import timestamp_from_datetime

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
    ret = []

    files_in_db = []
    files_on_disk = []

    try:
        files_in_db = FileWatchItemModel.objects.filter(watchid=item.id)
    except FileWatchItemModel.DoesNotExist:
        pass
    
    # expect all files from DB to be found on disk
    missing_files_from_db = []
    for db_item in files_in_db:
        missing_files_from_db.append(db_item.filename)

    if os.path.exists(item.filename):
        if os.path.isdir(item.filename) and item.recursive:
            files_on_disk = _get_files_recursive(item.filename)
        else:
            s = os.stat(item.filename)
            files_on_disk.append( FileWatchItemFromDisk(item.filename, s))
    logger.warning('_check_item %s: %s<>%s' % (item.filename, files_on_disk, files_in_db))
    
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
            missing_files_from_db.remove(db_item.filename)

            logger.error('%s %s' % (disk_item.filename, disk_item.created))
            logger.error('%s %s' % (db_item.filename, db_item.created))
            if disk_item.created != db_item.created:
                changes.append( 'Create time changed from %s to %s' % (db_item.created.strftime('%c'), disk_item.created.strftime('%c')) )
            if disk_item.modified != db_item.modified:
                changes.append( 'Modification time changed from %s to %s' % (db_item.modified.strftime('%c'), disk_item.modified.strftime('%c')) )
            if disk_item.uid != db_item.uid:
                changes.append( 'Owner changed from %i to %i' % (db_item.uid, disk_item.uid) )
            if disk_item.gid != db_item.gid:
                changes.append( 'Group changed from %i to %i' % (db_item.gid, disk_item.gid) )
            if disk_item.mode != db_item.mode:
                changes.append( 'Mode changed from %o to %o' % (db_item.mode, disk_item.mode) )
            if disk_item.size != db_item.size:
                changes.append( 'Size changed from %o to %o' % (db_item.size, disk_item.size) )
        
        if changes:
            ret.append( (disk_item.filename, changes) )
    for f in missing_files_from_db:
        changes = ['File deleted']
        ret.append( (f, changes) )
    return ret

def check(request):
    
    change_list = []
    for item in FileWatchModel.objects.all():
        item_change_list = _check_item(item)
        
        change_list.extend(item_change_list)
   
    t = Template(FILEWATCH_CHECK_VIEW_TEMPLATE, name='check view template')
    c = RequestContext( request, { 
        'change_list':change_list,
        })
    return HttpResponse(t.render(c))


FILEWATCH_CHECK_VIEW_TEMPLATE = """
{% load type %}
{% load base_url %}
{% load static_url %}
{% load media_url %}
<!DOCTYPE html>
<html lang="en">
<head>
  <meta http-equiv="content-type" content="text/html; charset=utf-8">
  <title>URL handler info</title>
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
    #info { background:#f6f6f6; }
    #info ol { margin: 0.5em 4em; }
    #info ol li { font-family: monospace; }
    #summary { background: #ffc; }
    #explanation { background:#eee; border-bottom: 0px none; }
  </style>
</head>
<body>
  <div id="summary">
    <h1>URL handler info</h1>
    <table class="meta">
      <tr>
        <th>Request Method:</th>
        <td>{{ request.META.REQUEST_METHOD }}</td>
      </tr>
      <tr>
        <th>Request URL:</th>
        <td>{{ request.build_absolute_uri|escape }}</td>
      </tr>
    <tr>
      <th>Script prefix:</th>
      <td><pre>{{ script_prefix|escape }}</pre></td>
    </tr>
    <tr>
      <th>Base URL:</th>
      <td><pre>{% base_url %}</pre></td>
    </tr>
    <tr>
      <th>Static URL:</th>
      <td><pre>{% static_url %}</pre></td>
    </tr>
    <tr>
      <th>Media URL:</th>
      <td><pre>{% media_url %}</pre></td>
    </tr>
      <tr>
        <th>Django Version:</th>
        <td>{{ django_version_info }}</td>
      </tr>
      <tr>
        <th>Python Version:</th>
        <td>{{ sys_version_info }}</td>
      </tr>
    <tr>
      <th>Python Executable:</th>
      <td>{{ sys_executable|escape }}</td>
    </tr>
    <tr>
      <th>Python Version:</th>
      <td>{{ sys_version_info }}</td>
    </tr>
    <tr>
      <th>Python Path:</th>
      <td><pre>{{ sys_path|pprint }}</pre></td>
    </tr>
    <tr>
      <th>Server time:</th>
      <td>{{server_time|date:"r"}}</td>
    </tr>
      <tr>
        <th>Installed Applications:</th>
        <td><ul>
          {% for item in settings.INSTALLED_APPS %}
            <li><code>{{ item }}</code></li>
          {% endfor %}
        </ul></td>
      </tr>
      <tr>
        <th>Installed Middleware:</th>
        <td><ul>
          {% for item in settings.MIDDLEWARE_CLASSES %}
            <li><code>{{ item }}</code></li>
          {% endfor %}
        </ul></td>
      </tr>
      <tr>
        <th>settings module:</th>
        <td><code>{{ settings.SETTINGS_MODULE }}</code></td>
      </tr>
    </table>
  </div>
  <div id="info">
      <ol>
        {% for item in change_list %}
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

  <div id="explanation">
    <p>
      This page contains information to investigate issues with this web application.
    </p>
  </div>
</body>
</html>
"""
