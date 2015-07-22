from django.template import RequestContext, Template, Context, loader
from django.core.urlresolvers import reverse
from django.http import HttpResponse
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

def check(request):
    
    changed_list = []
    unchanged_list = []
    for item in FileWatchModel.objects.all():
        item_changed_list, item_unchanged_list = _check_item(item)
        
        changed_list.extend(item_changed_list)
        unchanged_list.extend(item_unchanged_list)
   
    t = Template(FILEWATCH_CHECK_VIEW_TEMPLATE, name='check view template')
    c = RequestContext( request, { 
        'changed_list':changed_list,
        'unchanged_list':unchanged_list,
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

  <div id="explanation">
    <p>
      This page contains information to investigate issues with this web application.
    </p>
  </div>
</body>
</html>
"""
