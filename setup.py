#!/usr/bin/python
# -*- coding: utf-8 -*-

from distutils.core import setup

setup(name='arsoft-web-filewatch',
		version='0.1',
		description='notify when a file changes',
		author='Andreas Roth',
		author_email='aroth@arsoft-online.com',
		url='http://www.arsoft-online.com/',
		packages=['arsoft.web.filewatch'],
		scripts=[],
		data_files=[
            ('/etc/arsoft/web/filewatch/static', ['arsoft/web/filewatch/static/main.css']),
            ('/etc/arsoft/web/filewatch/templates', ['arsoft/web/filewatch/templates/home.html']),
            ]
		)
